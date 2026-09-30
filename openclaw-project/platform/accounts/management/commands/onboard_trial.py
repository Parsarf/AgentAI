"""Prepare an account, login invitation job and trial with no automatic agent start."""
import uuid
from django.core.management import call_command
from django.core.management.base import BaseCommand,CommandError
from django.contrib.auth.models import User
from django.core.validators import validate_email
from django.db import connection,transaction
from accounts.models import Identity,EmailJob
from accounts.services import audit

class Command(BaseCommand):
    help='Add one invited trial customer and queue onboarding email; no agent/provider call.'
    def add_arguments(self,p):p.add_argument('--email',required=True)
    def handle(self,*args,**o):
        email=o['email'].strip().lower();validate_email(email);account=uuid.uuid4().hex;operation=uuid.uuid4();request=uuid.uuid4()
        with transaction.atomic():
            if User.objects.filter(email__iexact=email).exists():raise CommandError('Email already registered')
            with connection.cursor() as c:
                c.execute("SELECT count(*) FROM accounts a WHERE a.status!='deleted' AND EXISTS(SELECT 1 FROM accounts_identity i WHERE i.account_id=a.id AND i.role='customer')")
                if c.fetchone()[0]>=2:raise CommandError('Two-account trial limit reached')
                c.execute("INSERT INTO accounts(id,status) VALUES (%s,'active')",[account])
                audit('host-admin',account,account,'trial.onboard','pending',request,operation)
                user=User(username=uuid.uuid4().hex,email=email,is_active=False);user.set_unusable_password();user.save()
                Identity.objects.create(user=user,account_id=account,role='customer')
                c.execute("INSERT INTO memberships VALUES (%s,%s,'customer','active')",[account,str(user.pk)])
                c.execute("INSERT INTO projects(account_id,id,name) VALUES (%s,%s,'My project')",[account,uuid.uuid4().hex])
            call_command('seed_trial',account=account,stdout=self.stdout)
            EmailJob.objects.create(user=user,purpose='onboarding')
            audit('host-admin',account,account,'trial.onboard','completed',request,operation)
        self.stdout.write('Account prepared: '+account+'; onboarding email queued. No agent was started.')
