"""Prepare a local entitlement; does not invite, provision, charge or dispatch."""
import json
import uuid
from datetime import timedelta
from django.core.management.base import BaseCommand,CommandError
from django.db import connection,transaction
from django.utils import timezone
from accounts.services import audit

class Command(BaseCommand):
    help='Seed the seven-day/$1 trial once for an existing account. No live provider access.'
    def add_arguments(self,p):p.add_argument('--account',required=True)
    def handle(self,*args,**o):
        account=o['account'];now=timezone.now();operation=uuid.uuid4();request=uuid.uuid4()
        with transaction.atomic():
            with connection.cursor() as c:
                c.execute("SELECT 1 FROM accounts WHERE id=%s AND status='active'",[account])
                if not c.fetchone():raise CommandError('Account unavailable')
                c.execute("SELECT 1 FROM entitlements WHERE account_id=%s",[account])
                if c.fetchone():raise CommandError('Entitlement already exists; trial does not reset allowance')
                limits={'period_start_epoch':int(now.timestamp()),'period_microusd':1000000,
                        'daily_microusd':1000000,'task_microusd':5000000,'max_queued_tasks':3}
                audit('host-admin',account,account,'budget.seed_trial','pending',request,operation)
                c.execute("INSERT INTO entitlements VALUES (%s,'trial-v1','launch-v1-proposed','trial',%s,%s)",
                          [account,json.dumps(limits,sort_keys=True),now+timedelta(days=7)])
                audit('host-admin',account,account,'budget.seed_trial','completed',request,operation)
        self.stdout.write('Trial entitlement prepared; provider execution remains disabled')
