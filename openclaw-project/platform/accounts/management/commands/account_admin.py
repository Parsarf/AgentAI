"""Host-only administrative bootstrap. No browser superuser or blanket customer access."""
import getpass
import sys
import uuid
from datetime import timedelta
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.validators import validate_email
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice
from accounts.models import Identity, OperatorGrant
from accounts.services import audit, create_invite, deliver, models_f_epoch

class Command(BaseCommand):
    help='Host-only audited create-account/operator/invite/grant/role-change. Passwords and MFA enrollment require a private terminal.'
    def add_arguments(self,p):
        p.add_argument('action',choices=['create-account','operator','invite','grant','role-change'])
        p.add_argument('--account'); p.add_argument('--email'); p.add_argument('--permission',choices=[x[0] for x in OperatorGrant._meta.get_field('action').choices])
        p.add_argument('--role',choices=['customer','operator','service'])
    def handle(self,*args,**o):
        action=o['action']; account=o.get('account'); email=(o.get('email') or '').strip().lower(); request=uuid.uuid4(); op=uuid.uuid4()
        if email: validate_email(email)
        if action=='operator' and not sys.stdin.isatty(): raise CommandError('Operator enrollment requires a private terminal')
        if action in ['create-account','invite','grant'] and (not account or len(account)>64): raise CommandError('Provide an account ID of at most 64 characters')
        if action=='invite':
            user,raw=create_invite(email,account,'host-admin',request)
            sent=deliver(user,'onboarding',raw,request)
            self.stdout.write('verification_pending; delivery='+('sent' if sent else 'uncertain')); return
        with transaction.atomic():
            if action=='create-account':
                with connection.cursor() as c: c.execute("INSERT INTO accounts(id,status) VALUES (%s,'active')",[account])
                audit('host-admin',account,account,'account.create','pending',request,op)
            else:
                user=User.objects.get(email__iexact=email) if action!='operator' else None
                audit('host-admin',account if action=='grant' else None, user.pk if user else 'operator', 'host.'+action,'pending',request,op)
                if action=='operator':
                    password=getpass.getpass('New operator password: ')
                    if password!=getpass.getpass('Confirm password: '): raise CommandError('Passwords differ')
                    user=User(username=uuid.uuid4().hex,email=email,is_staff=False,is_superuser=False)
                    validate_password(password,user); user.set_password(password); user.save()
                    Identity.objects.create(user=user,role='operator',verified=True)
                    device=TOTPDevice.objects.create(user=user,name='operator',confirmed=False)
                    # Intentional credential presentation only to the private enrollment terminal.
                    self.stdout.write(device.config_url)
                    code=getpass.getpass('Current authenticator code to confirm enrollment: ')
                    if not device.verify_token(code): raise CommandError('Invalid MFA enrollment')
                    device.confirmed=True; device.save(update_fields=['confirmed'])
                elif action=='grant':
                    if not o['permission']: raise CommandError('An explicit permission is required')
                    OperatorGrant.objects.update_or_create(user=user,account_id=account,action=o['permission'],defaults={'expires_at':timezone.now()+timedelta(hours=1)})
                elif action=='role-change':
                    if not o['role']: raise CommandError('A role is required')
                    identity=user.identity
                    # Existing memberships are revoked, and every session invalidated.
                    with connection.cursor() as c: c.execute("UPDATE memberships SET status='revoked' WHERE actor_id=%s",[str(user.pk)])
                    if o['role']=='customer': raise CommandError('Use a new verified invitation for customer access')
                    identity.role=o['role']; identity.account_id=None; identity.epoch+=1; identity.save()
                    OperatorGrant.objects.filter(user=user).delete()
                    if o['role']=='operator' and not TOTPDevice.objects.filter(user=user,confirmed=True).exists(): raise CommandError('Enroll a separate operator identity with MFA first')
            audit('host-admin',account if action in ['create-account','grant'] else None,account or 'identity','host.'+action,'completed',request,op)
        self.stdout.write('Completed audited host administration')
