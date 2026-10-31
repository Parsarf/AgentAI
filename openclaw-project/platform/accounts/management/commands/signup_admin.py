"""Host-only owner controls for sign-ups and customers (called by the private dashboard as root; audited as host-admin).

  list                      JSON of every sign-up and customer with state, email and dates
  approve|decline --account activate (seed allowance, create the assistant cell, email them) or refuse
  suspend|resume --account  pause or restore an existing customer (sessions end immediately)
  limit --count N           how many customer assistants this server may carry
No customer content is ever shown; only email, state and dates.
"""
import json
from io import StringIO
import time
import uuid
from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from accounts.lifecycle import coordinator
from accounts.models import Identity
from accounts.services import audit, models_f_epoch
from agentai_platform.lifecycle.capacity import max_cells, set_max_cells
from agentai_platform.lifecycle.types import Conflict

PROFILE = 'trial-unmeasured-v1'


def _mail(user, subject, body):
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
        return True
    except Exception:
        return False


def customers():
    with connection.cursor() as c:
        c.execute('''SELECT a.id,a.status,u.email,s.state,s.created_epoch,s.decided_epoch,
                (SELECT d.state FROM deployments d WHERE d.account_id=a.id ORDER BY d.generation DESC LIMIT 1)
            FROM accounts a JOIN accounts_identity i ON i.account_id=a.id AND i.role='customer' JOIN auth_user u ON u.id=i.user_id
            LEFT JOIN signups s ON s.account_id=a.id WHERE a.status!='deleted' ORDER BY coalesce(s.created_epoch,0) DESC,u.email''')
        rows = c.fetchall()
    return [{'account': r[0], 'status': r[1], 'email': r[2], 'signup': r[3], 'created_epoch': r[4], 'decided_epoch': r[5], 'assistant': r[6]} for r in rows]


def active_count():
    with connection.cursor() as c:
        c.execute("SELECT count(*) FROM lifecycle_cells l JOIN deployments d ON d.account_id=l.account_id AND d.id=l.deployment_id WHERE d.state!='deleted'")
        return c.fetchone()[0]


def overview():
    """Aggregate numbers for the owner home page: counts, queue, spend. Never message content."""
    now = int(time.time())
    out = {'limit': max_cells(), 'assistants': active_count(), 'generated_epoch': now}
    with connection.cursor() as c:
        c.execute('''SELECT CASE WHEN s.state IS NOT NULL AND s.state!='approved' THEN s.state ELSE a.status END, count(*)
            FROM accounts a JOIN accounts_identity i ON i.account_id=a.id AND i.role='customer' LEFT JOIN signups s ON s.account_id=a.id
            WHERE a.status!='deleted' GROUP BY 1''')
        out['customers'] = {k: v for k, v in c.fetchall()}
        c.execute("SELECT observed_state,count(*) FROM lifecycle_cells GROUP BY 1")
        out['cells'] = {k: v for k, v in c.fetchall()}
        c.execute("SELECT state,count(*) FROM customer_requests WHERE created_epoch>=%s GROUP BY 1", [now - 7 * 86400])
        out['tasks_7d'] = {k: v for k, v in c.fetchall()}
        c.execute("SELECT count(*) FROM customer_requests WHERE state IN ('waiting','starting','running','uncertain')")
        out['tasks_active'] = c.fetchone()[0]
        for key, since in (('today', now - now % 86400), ('d30', now - 30 * 86400)):
            c.execute("SELECT coalesce(sum(amount_microusd),0) FROM provider_receipts WHERE observed_epoch>=%s", [since])
            out['spend_' + key] = c.fetchone()[0]
        c.execute('''SELECT u.email,coalesce(sum(r.amount_microusd),0) FROM provider_receipts r JOIN accounts_identity i ON i.account_id=r.account_id AND i.role='customer'
            JOIN auth_user u ON u.id=i.user_id WHERE r.observed_epoch>=%s GROUP BY u.email ORDER BY 2 DESC LIMIT 5''', [now - 30 * 86400])
        out['top_spenders'] = [{'email': e, 'microusd': v} for e, v in c.fetchall()]
    from accounts.billing import access_mode
    out['billing_mode'] = access_mode()
    return out


class Command(BaseCommand):
    help = 'Owner controls for sign-ups and customers.'

    def add_arguments(self, p):
        p.add_argument('action', choices=['list', 'overview', 'approve', 'decline', 'suspend', 'resume', 'limit'])
        p.add_argument('--account')
        p.add_argument('--count', type=int)

    def handle(self, *args, **o):
        action, account = o['action'], o.get('account')
        if action == 'list':
            self.stdout.write(json.dumps({'limit': max_cells(), 'assistants': active_count(), 'customers': customers()}))
            return
        if action == 'overview':
            self.stdout.write(json.dumps(overview()))
            return
        if action == 'limit':
            try:
                self.stdout.write(json.dumps({'limit': set_max_cells(o.get('count'))}))
            except ValueError as exc:
                raise CommandError(str(exc))
            return
        if not account or len(account) > 64:
            raise CommandError('Provide --account')
        request, op = uuid.uuid4(), uuid.uuid4()
        identity = Identity.objects.filter(account_id=account, role='customer').select_related('user').first()
        if identity is None:
            raise CommandError('Unknown account')
        user = identity.user
        if action == 'approve':
            self._approve(account, user, request, op)
        elif action == 'decline':
            with transaction.atomic(), connection.cursor() as c:
                c.execute("UPDATE signups SET state='declined',decided_epoch=%s,decided_by='owner' WHERE account_id=%s AND state IN ('pending','unverified')", [int(time.time()), account])
                if c.rowcount != 1:
                    raise CommandError('That sign-up is not waiting')
                audit('host-admin', account, account, 'signup.decline', 'completed', request, op)
            _mail(user, 'About your Lumina sign-up', 'Thank you for your interest. We are not able to offer you access right now.\n')
            self.stdout.write(json.dumps({'ok': True, 'state': 'declined'}))
        elif action == 'suspend':
            with transaction.atomic(), connection.cursor() as c:
                c.execute("UPDATE accounts SET status='suspended' WHERE id=%s AND status='active'", [account])
                if c.rowcount != 1:
                    raise CommandError('Only an active customer can be suspended')
                Identity.objects.filter(account_id=account).update(epoch=models_f_epoch())      # ends their sessions
                audit('host-admin', account, account, 'customer.suspend', 'completed', request, op)
            self.stdout.write(json.dumps({'ok': True, 'status': 'suspended'}))
        elif action == 'resume':
            with transaction.atomic(), connection.cursor() as c:
                c.execute("SELECT state FROM signups WHERE account_id=%s", [account]); row = c.fetchone()
                if row and row[0] != 'approved':
                    raise CommandError('Approve the sign-up first')
                c.execute("UPDATE accounts SET status='active' WHERE id=%s AND status='suspended'", [account])
                if c.rowcount != 1:
                    raise CommandError('Only a suspended customer can be resumed')
                audit('host-admin', account, account, 'customer.resume', 'completed', request, op)
            self.stdout.write(json.dumps({'ok': True, 'status': 'active'}))

    def _approve(self, account, user, request, op):
        with connection.cursor() as c:
            c.execute('SELECT state FROM signups WHERE account_id=%s', [account]); row = c.fetchone()
        if not row or row[0] != 'pending':
            raise CommandError('That sign-up is not waiting for approval (it must have confirmed its email)')
        with connection.cursor() as c:
            c.execute("SELECT 1 FROM lifecycle_cells WHERE account_id=%s", [account]); has_cell = c.fetchone() is not None
        if not has_cell and active_count() >= max_cells():
            raise CommandError(f'Customer limit reached ({max_cells()}). Raise the limit first.')
        with transaction.atomic():
            with connection.cursor() as c:
                c.execute("UPDATE accounts SET status='active' WHERE id=%s AND status='suspended'", [account])
                c.execute("UPDATE signups SET state='approved',decided_epoch=%s,decided_by='owner' WHERE account_id=%s AND state='pending'", [int(time.time()), account])
                c.execute('SELECT 1 FROM projects WHERE account_id=%s', [account])
                if not c.fetchone():
                    c.execute("INSERT INTO projects(account_id,id,name) VALUES (%s,%s,'My project')", [account, uuid.uuid4().hex])
            from accounts.billing import access_mode
            if access_mode() == 'invite_only':          # open/paid modes are applied by the billing worker; the private beta gets the small trial
                from django.core.management import call_command
                call_command('seed_trial', account=account, stdout=StringIO())
            try:
                coordinator().host_create(account, key='signup-' + account, target_profile=PROFILE)
            except Conflict as exc:
                raise CommandError('Approval could not queue the assistant; no approval was saved. Please retry.') from exc
            audit('host-admin', account, account, 'signup.approve', 'completed', request, op)
        _mail(user, 'Your Lumina account is ready', f'Your account is approved. Sign in at {settings.PUBLIC_ORIGIN}/app/ with the email and password you chose.\n')
        self.stdout.write(json.dumps({'ok': True, 'state': 'approved'}))
