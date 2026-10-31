import json
import os
import re
import tempfile
import time
from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings
from agentai_platform.switches import SwitchStore
from .models import Identity
from .tests import AccountBoundaryTests

PW = 'A-long-passphrase-9'


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', DEFAULT_FROM_EMAIL='owner@example.invalid')
class SignupChecks(TestCase):
    new_client = AccountBoundaryTests.new_client
    post = AccountBoundaryTests.post
    setUp = AccountBoundaryTests.setUp

    def open_door(self, on=True):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        sw, facts = os.path.join(d.name, 'sw.json'), os.path.join(d.name, 'facts.json')
        json.dump({'mail_ready': True}, open(facts, 'w'))
        store = SwitchStore(sw, facts_path=facts)
        store.confirm('open_signups', 'approval_only', 'owner')
        if on:
            store.set('open_signups', True, 'owner')
        cap = os.path.join(d.name, 'signup-settings.json')
        o = override_settings(SWITCHES_FILE=sw, SWITCH_FACTS_FILE=facts); o.enable(); self.addCleanup(o.disable)
        self.cap = cap
        from unittest.mock import patch
        p = patch('agentai_platform.lifecycle.capacity.PATH', cap); p.start(); self.addCleanup(p.stop)
        return store

    def signup(self, email='new@example.invalid', password=PW, c=None, **extra):
        return self.post(c or self.new_client(), '/auth/signup', {'email': email, 'password': password, **extra})

    def code_from_mail(self):
        body = mail.outbox[-1].body
        return re.search(r'code=([A-Za-z0-9_-]+)', body).group(1)

    def test_closed_door_refuses_and_config_says_so(self):
        self.open_door(on=False)
        self.assertEqual(self.signup().status_code, 403)
        self.assertEqual(self.new_client().get('/v1/signup/config', secure=True).json(), {'open': False})
        self.assertEqual(User.objects.filter(email='new@example.invalid').count(), 0)

    def test_full_flow_sign_up_confirm_wait_approve_sign_in(self):
        self.open_door()
        c = self.new_client()
        self.assertEqual(c.get('/v1/signup/config', secure=True).json(), {'open': True})
        self.assertEqual(self.signup(c=c).status_code, 202)
        user = User.objects.get(email='new@example.invalid')
        self.assertFalse(user.is_active)
        with connection.cursor() as cur:
            cur.execute('SELECT s.state,a.status FROM signups s JOIN accounts a ON a.id=s.account_id JOIN accounts_identity i ON i.account_id=a.id WHERE i.user_id=%s', [user.pk])
            self.assertEqual(cur.fetchone(), ('unverified', 'suspended'))
        self.assertEqual(self.post(self.new_client(), '/auth/login', {'email': 'new@example.invalid', 'password': PW}).status_code, 401)   # not confirmed yet
        code = self.code_from_mail()
        self.assertEqual(self.post(self.new_client(), '/auth/signup/verify', {'code': 'wrong'}).status_code, 404)
        self.assertEqual(self.post(self.new_client(), '/auth/signup/verify', {'code': code}).json(), {'state': 'pending'})
        self.assertEqual(self.post(self.new_client(), '/auth/signup/verify', {'code': code}).status_code, 404)           # single use
        self.assertIn('waiting for approval', mail.outbox[-1].subject)                                                    # the owner is told
        r = self.post(self.new_client(), '/auth/login', {'email': 'new@example.invalid', 'password': PW})
        self.assertEqual((r.status_code, r.json()['error']), (403, 'pending_approval'))
        self.assertEqual(self.post(self.new_client(), '/auth/login', {'email': 'new@example.invalid', 'password': 'wrong-password-1'}).status_code, 401)  # no hint without the password
        account = Identity.objects.get(user=user).account_id
        call_command('signup_admin', 'approve', account=account)                          # the real coordinator: a create operation is queued for the host
        with connection.cursor() as cur:
            cur.execute("SELECT o.kind,o.state FROM operations o WHERE o.account_id=%s", [account]); self.assertEqual(cur.fetchall(), [('create', 'pending')])
            cur.execute("SELECT count(*) FROM lifecycle_cells WHERE account_id=%s", [account]); self.assertEqual(cur.fetchone()[0], 1)
        self.assertEqual(mail.outbox[-1].to, ['new@example.invalid'])
        c2 = self.new_client()
        self.assertEqual(self.post(c2, '/auth/login', {'email': 'new@example.invalid', 'password': PW}).status_code, 200)
        self.assertEqual(c2.get('/v1/projects', secure=True).json()['projects'][0]['name'], 'My project')
        with connection.cursor() as cur:
            cur.execute('SELECT state FROM signups WHERE account_id=%s', [account]); self.assertEqual(cur.fetchone()[0], 'approved')
            cur.execute('SELECT status FROM entitlements WHERE account_id=%s', [account]); self.assertEqual(cur.fetchone()[0], 'trial')

    def test_no_account_enumeration_and_weak_inputs(self):
        self.open_door()
        first = self.signup(email='a@example.invalid')
        again = self.signup(email='a@example.invalid')
        existing = self.signup(email='a@example.invalid')   # an existing customer address (from setUp) answers the same way
        for r in (first, again, existing):
            self.assertEqual((r.status_code, r.json()), (202, {'accepted': True}))
        self.assertEqual(self.signup(email='not-an-email').status_code, 400)
        self.assertEqual(self.signup(email='b2@example.invalid', password='12345678').status_code, 400)
        self.assertEqual(self.signup(email='b3@example.invalid', password=PW, website='http://spam').status_code, 202)   # honeypot answers the same...
        self.assertFalse(User.objects.filter(email='b3@example.invalid').exists())                                       # ...but creates nothing

    def test_approval_rolls_back_if_cell_creation_cannot_be_queued(self):
        from unittest.mock import patch
        from agentai_platform.lifecycle.types import Conflict
        self.open_door()
        self.signup()
        self.post(self.new_client(), '/auth/signup/verify', {'code': self.code_from_mail()})
        account = Identity.objects.get(user__email='new@example.invalid').account_id
        before = len(mail.outbox)
        with patch('accounts.management.commands.signup_admin.coordinator') as coordinator:
            coordinator.return_value.host_create.side_effect = Conflict('capacity changed')
            with self.assertRaises(CommandError): call_command('signup_admin', 'approve', account=account)
        with connection.cursor() as cur:
            cur.execute('SELECT s.state,a.status FROM signups s JOIN accounts a ON a.id=s.account_id WHERE a.id=%s', [account])
            self.assertEqual(cur.fetchone(), ('pending', 'suspended'))
            cur.execute('SELECT count(*) FROM lifecycle_cells WHERE account_id=%s', [account])
            self.assertEqual(cur.fetchone()[0], 0)
        self.assertEqual(len(mail.outbox), before)
        call_command('signup_admin', 'approve', account=account)
        with connection.cursor() as cur:
            cur.execute("SELECT count(*) FROM operations WHERE account_id=%s AND kind='create'", [account])
            self.assertEqual(cur.fetchone()[0], 1)

    def test_rate_limits_and_resend_for_unconfirmed(self):
        self.open_door()
        for i in range(3):
            self.assertEqual(self.signup(email='r@example.invalid').status_code, 202)
        self.assertEqual(self.signup(email='r@example.invalid').status_code, 429)             # per address
        self.assertGreaterEqual(len(mail.outbox), 2)                                           # the 2nd and 3rd tries re-sent the link
        self.assertEqual(User.objects.filter(email='r@example.invalid').count(), 1)

    def test_decline_suspend_resume_and_limit(self):
        self.open_door()
        self.signup(email='d@example.invalid'); code = self.code_from_mail()
        self.post(self.new_client(), '/auth/signup/verify', {'code': code})
        account = Identity.objects.get(user__email='d@example.invalid').account_id
        call_command('signup_admin', 'decline', account=account)
        r = self.post(self.new_client(), '/auth/login', {'email': 'd@example.invalid', 'password': PW})
        self.assertEqual((r.status_code, r.json()['error']), (403, 'not_approved'))
        with self.assertRaises(CommandError):
            call_command('signup_admin', 'approve', account=account)                          # declined cannot be approved by accident
        # an existing customer can be suspended (sessions end) and resumed
        c = AccountBoundaryTests.signed(self, 'a')
        call_command('signup_admin', 'suspend', account='a')
        self.assertEqual(c.get('/v1/projects', secure=True).status_code, 401)
        call_command('signup_admin', 'resume', account='a')
        self.assertEqual(AccountBoundaryTests.signed(self, 'a').get('/v1/projects', secure=True).status_code, 200)
        with self.assertRaises(CommandError):
            call_command('signup_admin', 'limit', count=0)
        call_command('signup_admin', 'limit', count=7)
        from agentai_platform.lifecycle.capacity import max_cells
        self.assertEqual(max_cells(), 7)

    def test_approval_respects_the_customer_limit(self):
        self.open_door()
        self.signup(email='cap@example.invalid'); self.post(self.new_client(), '/auth/signup/verify', {'code': self.code_from_mail()})
        account = Identity.objects.get(user__email='cap@example.invalid').account_id
        call_command('signup_admin', 'limit', count=1)
        with connection.cursor() as cur:
            cur.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES ('a','dcap',1,'pending')")
            cur.execute("INSERT INTO lifecycle_cells(account_id,deployment_id,tenant_ref,profile_revision) VALUES ('a','dcap','aa-cap','trial-unmeasured-v1')")
        with self.assertRaises(CommandError):
            call_command('signup_admin', 'approve', account=account)
        with connection.cursor() as cur:
            cur.execute('SELECT status FROM accounts WHERE id=%s', [account]); self.assertEqual(cur.fetchone()[0], 'suspended')

    def test_unconfirmed_signups_expire_and_listing_shows_only_email_and_state(self):
        self.open_door()
        self.signup(email='old@example.invalid')
        with connection.cursor() as cur:
            cur.execute("UPDATE signups SET created_epoch=%s WHERE state='unverified'", [int(time.time()) - 25 * 3600])
        self.signup(email='fresh@example.invalid', c=self.new_client())
        self.assertFalse(User.objects.filter(email='old@example.invalid').exists())
        import io
        out = io.StringIO(); call_command('signup_admin', 'list', stdout=out)
        data = json.loads(out.getvalue())
        self.assertTrue(any(x['email'] == 'fresh@example.invalid' and x['signup'] == 'unverified' for x in data['customers']))
        self.assertEqual(set(data['customers'][0]), {'account', 'status', 'email', 'signup', 'created_epoch', 'decided_epoch', 'assistant'})

    def test_overview_has_only_aggregates_and_emails(self):
        self.open_door()
        self.signup(email='ov@example.invalid'); self.post(self.new_client(), '/auth/signup/verify', {'code': self.code_from_mail()})
        import io
        out = io.StringIO(); call_command('signup_admin', 'overview', stdout=out)
        data = json.loads(out.getvalue())
        self.assertEqual(data['customers'].get('pending'), 1)
        self.assertEqual(data['limit'], 2); self.assertIn('spend_today', data); self.assertIn(data['billing_mode'], ('invite_only', 'open', 'paid_required'))
        self.assertNotIn('message', json.dumps(data).lower().replace('message_', ''))
