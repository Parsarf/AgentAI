import hashlib
import secrets
import uuid
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.db import connection, transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac
from .models import ActionToken, Audit, Identity, OperatorGrant, RateBucket

class Denied(Exception): pass
class Limited(Exception): pass

def audit(actor, account, object_id, action, outcome, request_id, operation=None):
    return Audit.objects.create(actor=str(actor), account_id=account, object_id=str(object_id), action=action,
                                outcome=outcome, request_id=request_id, operation_id=operation or uuid.uuid4())

def rate(scope, key, limit, seconds=600):
    now = timezone.now()
    window = int(now.timestamp()) // seconds
    digest = salted_hmac('agentai.rate', f'{scope}:{key}:{window}').hexdigest()
    with transaction.atomic():
        bucket, _ = RateBucket.objects.get_or_create(key=digest, defaults={'expires_at': now + timedelta(seconds=seconds*2)})
        if bucket.count >= limit: raise Limited()
        bucket.count += 1
        bucket.save(update_fields=['count'])

def token_for(user, purpose):
    identity = user.identity
    ActionToken.objects.filter(user=user, purpose=purpose, consumed_at=None).update(consumed_at=timezone.now())
    raw = secrets.token_urlsafe(32)
    ActionToken.objects.create(digest=hashlib.sha256(raw.encode()).hexdigest(), user=user, purpose=purpose,
                              expires_at=timezone.now()+timedelta(minutes=15), epoch=identity.epoch)
    return raw

def deliver(user, purpose, raw, request_id):
    identity = user.identity
    op = uuid.uuid4()
    audit('system', identity.account_id, user.pk, 'mail.'+purpose, 'pending', request_id, op)
    try:
        page = 'activate' if purpose == 'onboarding' else 'reset'
        count = send_mail('AgentAI account verification' if page == 'activate' else 'AgentAI account recovery',
                         f'Open {settings.PUBLIC_ORIGIN}/account/{page}/ and paste this single-use code within 15 minutes:\n{raw}\n',
                         settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
        if count != 1: raise RuntimeError('Mail delivery uncertain')
    except Exception:
        # Delivery may have succeeded before timeout. Never retry automatically.
        audit('system', identity.account_id, user.pk, 'mail.'+purpose, 'uncertain', request_id, op)
        return False
    audit('system', identity.account_id, user.pk, 'mail.'+purpose, 'completed', request_id, op)
    return True

def create_invite(email, account, actor, request_id):
    with transaction.atomic():
        with connection.cursor() as c:
            c.execute('SELECT status FROM accounts WHERE id=%s', [account])
            row = c.fetchone()
            if not row or row[0] != 'active': raise Denied()
        op = uuid.uuid4()
        audit(actor, account, account, 'identity.invite', 'pending', request_id, op)
        user = User.objects.create(username=uuid.uuid4().hex, email=email.strip().lower(), is_active=False)
        user.set_unusable_password(); user.save(update_fields=['password'])
        Identity.objects.create(user=user, account_id=account, role='customer')
        with connection.cursor() as c:
            c.execute("INSERT INTO memberships(account_id,actor_id,role,status) VALUES (%s,%s,'customer','active')", [account,str(user.pk)])
        raw = token_for(user, 'onboarding')
        audit(actor, account, user.pk, 'identity.invite', 'completed', request_id, op)
    return user, raw

def consume(raw, purpose, password, request_id):
    from django.contrib.auth.password_validation import validate_password
    digest = hashlib.sha256(raw.encode()).hexdigest()
    # IMMEDIATE transaction serializes SQLite token consumption and identity writes.
    with transaction.atomic():
        token = ActionToken.objects.select_related('user').filter(digest=digest, purpose=purpose,
                    consumed_at=None, expires_at__gt=timezone.now()).first()
        if not token: raise Denied()
        user = token.user; identity = Identity.objects.get(user=user)
        if identity.role != 'customer' or token.epoch != identity.epoch: raise Denied()
        with connection.cursor() as c:
            c.execute("SELECT 1 FROM accounts a JOIN memberships m ON m.account_id=a.id WHERE a.id=%s AND a.status='active' AND m.actor_id=%s AND m.status='active' AND m.role='customer'", [identity.account_id,str(user.pk)])
            if not c.fetchone(): raise Denied()
        validate_password(password, user)
        op = uuid.uuid4()
        audit(user.pk, identity.account_id, user.pk, 'identity.'+purpose, 'pending', request_id, op)
        token.consumed_at = timezone.now(); token.save(update_fields=['consumed_at'])
        user.set_password(password); user.is_active=True; user.save(update_fields=['password','is_active'])
        identity.verified=True; identity.epoch+=1; identity.save(update_fields=['verified','epoch'])
        ActionToken.objects.filter(user=user, consumed_at=None).update(consumed_at=timezone.now())
        audit(user.pk, identity.account_id, user.pk, 'identity.'+purpose, 'completed', request_id, op)

def customer_scope(user, epoch):
    identity = Identity.objects.filter(user=user, role='customer', verified=True, epoch=epoch).first()
    if not identity or not user.is_active: raise Denied()
    with connection.cursor() as c:
        c.execute("SELECT 1 FROM memberships m JOIN accounts a ON a.id=m.account_id WHERE m.account_id=%s AND m.actor_id=%s AND m.status='active' AND m.role='customer' AND a.status='active'", [identity.account_id,str(user.pk)])
        if not c.fetchone(): raise Denied()
    return identity.account_id

def operator_scope(request, account, action):
    identity = Identity.objects.filter(user=request.user, role='operator', verified=True, epoch=request.session.get('epoch')).first()
    if not identity or not request.user.is_verified() or not request.user.otp_device.confirmed: raise Denied()
    if not OperatorGrant.objects.filter(user=request.user,account_id=account,action=action,expires_at__gt=timezone.now()).exists(): raise Denied()
    return identity

def revoke(actor, account, user_id, request_id):
    op=uuid.uuid4()
    with transaction.atomic():
        audit(actor,account,user_id,'membership.revoke','pending',request_id,op)
        with connection.cursor() as c:
            c.execute("UPDATE memberships SET status='revoked' WHERE account_id=%s AND actor_id=%s",[account,user_id])
            if c.rowcount!=1: raise Denied()
        Identity.objects.filter(account_id=account,user_id=user_id).update(epoch=models_f_epoch())
        audit(actor,account,user_id,'membership.revoke','completed',request_id,op)

def models_f_epoch():
    from django.db.models import F
    return F('epoch')+1
