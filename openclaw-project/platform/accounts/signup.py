"""Self-service sign-up with owner approval.

Flow: a person submits an email and a password -> an inactive user and a *suspended* account are created and a single-use link
is emailed -> the link confirms the email (state: pending) -> nothing works until the owner approves in the dashboard
(`signup_admin approve`), which activates the account, seeds its allowance and creates its assistant cell.

Privacy and abuse: the answer is the same whether or not the email is already registered (no account enumeration); sign-ups are
rate limited per address and per source; unconfirmed sign-ups are removed after 24 hours; the number of waiting sign-ups is capped.
Nothing is created for the person in the assistant runtime until the owner approves.
"""
import time
import uuid
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import connection, transaction
from django.http import JsonResponse
from django.utils import timezone
from agentai_platform.switches import SwitchStore
from .models import ActionToken, Identity
from .services import Denied, audit, rate, token_for
from .views import endpoint

PURPOSE = 'signup'
MAX_WAITING = 200
UNCONFIRMED_HOURS = 24
ACCEPTED = {'accepted': True}


def signups_open():
    return SwitchStore(settings.SWITCHES_FILE or None, facts_path=settings.SWITCH_FACTS_FILE or None).is_on('open_signups')


def _purge_unconfirmed(limit=20):
    """Remove sign-ups that never confirmed their email (their rows hold nothing but the address)."""
    cutoff = int(time.time()) - UNCONFIRMED_HOURS * 3600
    with connection.cursor() as c:
        c.execute("SELECT account_id FROM signups WHERE state='unverified' AND created_epoch<%s LIMIT %s", [cutoff, limit])
        stale = [r[0] for r in c.fetchall()]
    for account in stale:
        with transaction.atomic():
            ids = list(Identity.objects.filter(account_id=account).values_list('user_id', flat=True))
            ActionToken.objects.filter(user_id__in=ids).delete()
            Identity.objects.filter(account_id=account).delete()
            User.objects.filter(pk__in=ids, is_active=False).delete()
            with connection.cursor() as c:
                c.execute('DELETE FROM memberships WHERE account_id=%s', [account])
                c.execute('DELETE FROM signups WHERE account_id=%s', [account])
                c.execute("UPDATE accounts SET status='deleted' WHERE id=%s", [account])


def _mail(to, subject, body):
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to], fail_silently=False)
        return True
    except Exception:
        return False


@endpoint(['GET'])
def config(request):
    return JsonResponse({'open': signups_open()})


@endpoint(['POST'], ['email', 'password', 'website'])
def signup(request):
    """Create a waiting account. Always answers 202 with the same body unless the request itself is invalid or the door is closed."""
    if not signups_open():
        return JsonResponse({'error': 'signups_closed'}, status=403)
    if request.input.get('website'):                       # honeypot: real people never see or fill this field
        return JsonResponse(ACCEPTED, status=202)
    email = request.input.get('email', '').strip().lower()
    password = request.input.get('password', '')
    try:
        validate_email(email)
        if len(email) > 254:
            raise ValidationError('too long')
    except ValidationError:
        return JsonResponse({'error': 'invalid_email'}, status=400)
    try:
        validate_password(password)
    except ValidationError as exc:
        return JsonResponse({'error': 'weak_password', 'detail': ' '.join(exc.messages)[:300]}, status=400)
    rate('signup.ip', request.client_ip, 5, 3600)
    rate('signup.email', email, 3, 86400)
    _purge_unconfirmed()
    with connection.cursor() as c:
        c.execute("SELECT count(*) FROM signups WHERE state IN ('unverified','pending')")
        waiting = c.fetchone()[0]
    if waiting >= MAX_WAITING:
        return JsonResponse({'error': 'signups_full'}, status=503)
    existing = User.objects.filter(email__iexact=email).first()
    if existing is not None:
        # Same answer either way: no way to learn who has an account. A person who never confirmed gets a fresh link.
        identity = Identity.objects.filter(user=existing, role='customer', verified=False).first()
        with connection.cursor() as c:
            c.execute("SELECT 1 FROM signups WHERE account_id=%s AND state='unverified'", [identity.account_id if identity else ''])
            unconfirmed = c.fetchone() is not None
        if identity is not None and unconfirmed:
            _mail(email, 'Confirm your Lumina email', f'Open this link within 15 minutes to confirm your email:\n{settings.PUBLIC_ORIGIN}/app/verify?code={token_for(existing, PURPOSE)}\n')
        audit('anonymous', None, 'signup', 'signup.duplicate', 'denied', request.request_id)
        return JsonResponse(ACCEPTED, status=202)
    account = 'su' + uuid.uuid4().hex[:30]
    op = uuid.uuid4()
    with transaction.atomic():
        with connection.cursor() as c:
            c.execute("INSERT INTO accounts(id,status) VALUES (%s,'suspended')", [account])
            audit('anonymous', account, account, 'signup.create', 'pending', request.request_id, op)
            user = User(username=uuid.uuid4().hex, email=email, is_active=False)
            user.set_password(password)
            user.save()
            Identity.objects.create(user=user, account_id=account, role='customer', verified=False)
            c.execute("INSERT INTO memberships(account_id,actor_id,role,status) VALUES (%s,%s,'customer','active')", [account, str(user.pk)])
            c.execute("INSERT INTO signups(account_id,state,created_epoch) VALUES (%s,'unverified',%s)", [account, int(time.time())])
        raw = token_for(user, PURPOSE)
        audit('anonymous', account, account, 'signup.create', 'completed', request.request_id, op)
    link = f'{settings.PUBLIC_ORIGIN}/app/verify?code={raw}'
    sent = _mail(email, 'Confirm your Lumina email',
                 f'Open this link within 15 minutes to confirm your email:\n{link}\n\nAfter that your sign-up waits for approval. We will email you when your account is ready.\nIf you did not ask for this, ignore this message.\n')
    if not sent:
        audit('system', account, account, 'mail.signup', 'uncertain', request.request_id)
    return JsonResponse(ACCEPTED, status=202)


@endpoint(['POST'], ['code'])
def verify(request):
    """Confirm the email. The account then waits for the owner; it cannot sign in or use anything yet."""
    import hashlib
    raw = request.input.get('code', '')
    if not raw or len(raw) > 128:
        raise Denied()
    rate('signup.verify', request.client_ip, 20, 900)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    with transaction.atomic():
        token = ActionToken.objects.select_related('user').filter(digest=digest, purpose=PURPOSE, consumed_at=None, expires_at__gt=timezone.now()).first()
        if not token:
            raise Denied()
        user = token.user
        identity = Identity.objects.get(user=user)
        if token.epoch != identity.epoch:
            raise Denied()
        token.consumed_at = timezone.now()
        token.save(update_fields=['consumed_at'])
        user.is_active = True
        user.save(update_fields=['is_active'])
        identity.verified = True
        identity.save(update_fields=['verified'])
        with connection.cursor() as c:
            c.execute("UPDATE signups SET state='pending',verified_epoch=%s WHERE account_id=%s AND state='unverified'", [int(time.time()), identity.account_id])
        audit(user.pk, identity.account_id, identity.account_id, 'signup.verify', 'completed', request.request_id)
    owner = settings.DEFAULT_FROM_EMAIL
    _mail(owner, 'Lumina: a new sign-up is waiting for approval',
          f'{user.email} confirmed their email and is waiting. Approve or decline in the Customers page of your dashboard.\n')
    return JsonResponse({'state': 'pending'})
