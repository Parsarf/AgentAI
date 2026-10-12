import io
import json
import os
import re
import tempfile
import time
from unittest.mock import patch
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from agentai_platform.billing import signature_header
from agentai_platform.switches import SwitchStore
from tests.billing_fixture import FakeStripe, Events, PRICE, SECRET
from .tests import AccountBoundaryTests


class BillingHTTPChecks(TestCase):
    new_client = AccountBoundaryTests.new_client
    post = AccountBoundaryTests.post
    signed = AccountBoundaryTests.signed
    setUp = AccountBoundaryTests.setUp

    def configure(self, switch=True):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        paths = {name: os.path.join(d.name, name) for name in ('key', 'secret', 'plan', 'switches', 'facts')}
        open(paths['key'], 'w').write('sk_test_' + 'a' * 24)
        open(paths['secret'], 'w').write(SECRET + '\n')
        plan = json.loads(open(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'product', 'plan.json')).read())
        json.dump(plan, open(paths['plan'], 'w'))
        if switch:
            store = SwitchStore(paths['switches'], facts_path=paths['facts'])
            json.dump({k: True for k in ('stripe_test_keys_present', 'stripe_price_configured', 'webhook_secret_present', 'webhook_endpoint_registered')}, open(paths['facts'], 'w'))
            store.confirm('billing_checkout', 'test_mode_only', 'owner'); store.confirm('billing_checkout', 'pauses_free_users', 'owner'); store.set('billing_checkout', True, 'owner')
        overrides = override_settings(BILLING_SECRET_KEY_FILE=paths['key'], BILLING_WEBHOOK_SECRET_FILE=paths['secret'], BILLING_PLAN_FILE=paths['plan'],
                                      BILLING_PRICE_ID=PRICE, BILLING_API_VERSION='2025-09-30.clover', SWITCHES_FILE=paths['switches'] if switch else '',
                                      SWITCH_FACTS_FILE=paths['facts'] if switch else '')
        overrides.enable(); self.addCleanup(overrides.disable)
        self.api = FakeStripe(lambda: int(time.time()))
        patcher = patch('accounts.billing.StripeHttp', lambda *a, **k: self.api); patcher.start(); self.addCleanup(patcher.stop)
        self.events = Events(lambda: int(time.time()))

    def seed_trial(self, account):
        limits = {'period_start_epoch': int(time.time()) - 100, 'period_microusd': 1_000_000, 'daily_microusd': 1_000_000,
                  'task_microusd': 5_000_000, 'max_queued_tasks': 3}
        with connection.cursor() as c:
            c.execute("INSERT INTO entitlements VALUES (%s,'trial-v1','launch-v1-proposed','trial',%s,datetime('now','+7 days'))", [account, json.dumps(limits)])

    def webhook(self, event, secret=SECRET, client=None, **extra):
        body = self.events.body(event)
        return (client or self.new_client()).post('/v1/billing/webhook', body, content_type='application/json', secure=True,
                                                   HTTP_STRIPE_SIGNATURE=signature_header(body, secret, int(time.time())), **extra)

    def worker(self):
        out = io.StringIO(); call_command('billing_worker', stdout=out); return json.loads(out.getvalue())

    def test_routes_gate_identity_and_the_webhook_fails_closed_unconfigured(self):
        anon = self.new_client()
        self.assertEqual(anon.get('/v1/account/billing', secure=True).status_code, 401)
        self.assertEqual(self.post(anon, '/v1/account/billing/checkout', {}).status_code, 401)
        self.assertEqual(self.post(anon, '/v1/account/billing/portal', {}).status_code, 401)
        self.assertEqual(anon.get('/v1/billing/webhook', secure=True).status_code, 405)
        self.assertEqual(anon.post('/v1/billing/webhook', '{}', content_type='application/json', secure=True).status_code, 503)

    def test_default_overview_is_trial_and_buttons_are_off(self):
        a = self.signed(); self.seed_trial('a')
        body = a.get('/v1/account/billing', secure=True).json()
        self.assertEqual((body['status'], body['checkout_available'], body['manage_available'], body['new_tasks_allowed']), ('none', False, False, True))   # invitation trial is still eligible
        self.assertEqual(body['access_mode'], 'invite_only')
        self.assertNotIn('sk_', json.dumps(body))
        page = a.get('/account/billing/', secure=True).content.decode()
        self.assertIn('Subscriptions are not open yet', page); self.assertNotIn('Subscribe —', page)
        self.assertEqual(self.post(a, '/v1/account/billing/checkout', {}).json()['error'], 'feature_off')
        self.assertEqual(self.post(a, '/v1/account/billing/portal', {}).status_code, 503)
        self.assertEqual(self.post(a, '/v1/account/billing/checkout', {'price': 'price_cheap', 'account_id': 'b'}).status_code, 400)

    def test_switch_on_without_provider_configuration_still_fails_closed(self):
        self.configure()
        with override_settings(BILLING_SECRET_KEY_FILE=''):
            a = self.signed()
            self.assertEqual(self.post(a, '/v1/account/billing/checkout', {}).json()['error'], 'not_configured')

    def test_full_flow_checkout_webhook_worker_and_access(self):
        self.configure(); a, b = self.signed('a'), self.signed('b'); self.seed_trial('a'); self.seed_trial('b')
        self.assertTrue(a.get('/v1/account/billing', secure=True).json()['checkout_available'])
        url = self.post(a, '/v1/account/billing/checkout', {}).json()['url']
        self.assertTrue(url.startswith('https://checkout.stripe.com/'))
        self.assertEqual(a.get('/v1/account/billing', secure=True).json()['status'], 'none')   # redirect grants nothing
        session = next(iter(self.api.sessions)); sub = self.api.complete_checkout(session)
        completed = self.events.make('checkout.session.completed', {'id': session})
        self.assertEqual(self.webhook(completed).json(), {'ok': True, 'status': 'stored'})
        self.assertEqual(self.webhook(completed).json()['status'], 'duplicate')
        self.assertEqual(a.get('/v1/account/billing', secure=True).json()['status'], 'none')   # stored is not applied
        self.assertEqual(self.worker()['applied'], 1)
        view = a.get('/v1/account/billing', secure=True).json()
        self.assertEqual((view['status'], view['new_tasks_allowed'], view['plan']['monthly_price_usd']), ('active', True, '79.00'))
        self.assertEqual(a.get('/v1/costs', secure=True).json()['period_limit_microusd'], 25_000_000)
        self.assertEqual(b.get('/v1/account/billing', secure=True).json()['status'], 'none')
        self.assertEqual(b.get('/v1/costs', secure=True).json()['period_limit_microusd'], 1_000_000)
        self.assertEqual(b.get('/v1/account/billing', secure=True).json()['invoices'], [])
        page = a.get('/account/billing/?checkout=return', secure=True).content.decode()
        for text in ('Your plan is active', 'waiting for Stripe to confirm', 'https://invoice.stripe.com/', 'Manage payment, plan or cancel'):
            self.assertIn(text, page)
        self.assertNotIn('sk_test', page); self.assertNotIn(SECRET, page)
        self.assertEqual(self.post(a, '/v1/account/billing/checkout', {}).status_code, 409)
        portal = self.post(a, '/v1/account/billing/portal', {}).json()['url']
        self.assertTrue(portal.startswith('https://billing.stripe.com/'))

    def test_form_checkout_redirects_straight_to_the_hosted_page(self):
        self.configure(); a = self.signed()
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', a.get('/account/billing/', secure=True).content.decode()).group(1)
        r = a.post('/v1/account/billing/checkout', 'csrfmiddlewaretoken=' + token, content_type='application/x-www-form-urlencoded', secure=True, HTTP_ORIGIN='https://localhost')
        self.assertEqual(r.status_code, 302); self.assertTrue(r['Location'].startswith('https://checkout.stripe.com/'))

    def test_webhook_rejects_bad_signature_tampering_size_and_stale_timestamps(self):
        self.configure(switch=False); event = self.events.make('customer.created', {'id': 'cus_zzzzzz'})
        self.assertEqual(self.webhook(event, secret='whsec_' + 'z' * 32).status_code, 400)
        body = self.events.body(event)
        tampered = self.new_client().post('/v1/billing/webhook', body + b' ', content_type='application/json', secure=True,
                                          HTTP_STRIPE_SIGNATURE=signature_header(body, SECRET, int(time.time())))
        self.assertEqual(tampered.status_code, 400)
        stale = self.new_client().post('/v1/billing/webhook', body, content_type='application/json', secure=True,
                                       HTTP_STRIPE_SIGNATURE=signature_header(body, SECRET, int(time.time()) - 3600))
        self.assertEqual(stale.status_code, 400)
        self.assertEqual(self.new_client().post('/v1/billing/webhook', b'x' * 300000, content_type='application/json', secure=True).status_code, 413)
        self.assertEqual(self.new_client().post('/v1/billing/webhook', b'{}', content_type='application/json', secure=True).status_code, 400)
        with connection.cursor() as c:
            c.execute('SELECT count(*) FROM billing_inbox'); self.assertEqual(c.fetchone()[0], 0)

    def test_worker_requires_configuration_and_reports_counts_only(self):
        out = io.StringIO(); call_command('billing_worker', '--check', stdout=out)
        self.assertEqual(json.loads(out.getvalue())['provider_configured'], False)
        out = io.StringIO(); call_command('billing_worker', stdout=out)   # no provider configured: only free-access sync runs
        report = json.loads(out.getvalue()); self.assertEqual((report['provider'], report['access_mode']), ('not configured', 'invite_only'))

    def test_retention_and_account_deletion_leave_billing_records_alone(self):
        with connection.cursor() as c:
            c.execute("INSERT INTO billing_invoices VALUES ('in_keepkeep','a','sub_keepkeep','paid',7900,7900,'usd','https://invoice.stripe.com/i/x',1,2,3,4)")
            c.execute("INSERT INTO billing_inbox(event_id,event_type,provider_created,payload_sha256,status,received_epoch) VALUES ('evt_keepkeep','x',1,%s,'applied',1)", ['0' * 64])
            c.execute("UPDATE accounts SET status='deleted' WHERE id='a'")
        call_command('retention_accounts', stdout=io.StringIO())
        with connection.cursor() as c:
            c.execute('SELECT count(*) FROM billing_invoices'); self.assertEqual(c.fetchone()[0], 1)
            c.execute('SELECT count(*) FROM billing_inbox'); self.assertEqual(c.fetchone()[0], 1)

    def test_free_access_until_payments_are_turned_on(self):
        self.configure(switch=False)
        from django.test import override_settings as ov
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        switches, facts = os.path.join(d.name, 's.json'), os.path.join(d.name, 'f.json')
        store = SwitchStore(switches, facts_path=facts)
        with ov(SWITCHES_FILE=switches, SWITCH_FACTS_FILE=facts):
            a, b = self.signed('a'), self.signed('b'); self.seed_trial('a')
            self.assertEqual(a.get('/v1/account/billing', secure=True).json()['access_mode'], 'invite_only')
            with self.assertRaises(Exception): store.set('open_access', True, 'owner')            # needs the cost confirmation
            store.confirm('open_access', 'cost_accepted', 'owner'); store.set('open_access', True, 'owner')
            report = self.worker(); self.assertEqual(report['access_mode'], 'open'); self.assertEqual(report['open_access']['granted'], 2)
            for client in (a, b):
                self.assertEqual(client.get('/v1/costs', secure=True).json()['period_limit_microusd'], 25_000_000)
                self.assertTrue(client.get('/v1/costs', secure=True).json()['admission_eligible'])
            view = b.get('/v1/account/billing', secure=True).json()
            self.assertEqual((view['access_mode'], view['new_tasks_allowed'], view['checkout_available']), ('open', True, False))
            self.assertIn('Free access is on', b.get('/account/billing/', secure=True).content.decode())
            self.assertEqual(self.worker()['open_access'], {'granted': 0, 'refreshed': 0, 'ended': 0})   # idempotent
            # Turning payments on ends free access for everyone without a paid plan.
            json.dump({k: True for k in ('stripe_test_keys_present', 'stripe_price_configured', 'webhook_secret_present', 'webhook_endpoint_registered')}, open(facts, 'w'))
            store.confirm('billing_checkout', 'test_mode_only', 'owner'); store.confirm('billing_checkout', 'pauses_free_users', 'owner')
            store.set('billing_checkout', True, 'owner')
            self.assertEqual(b.get('/v1/account/billing', secure=True).json()['access_mode'], 'paid_required')
            self.assertEqual(self.worker()['open_access']['ended'], 2)
            self.assertFalse(b.get('/v1/costs', secure=True).json()['admission_eligible'])
            page = b.get('/account/billing/', secure=True).content.decode(); self.assertIn('A paid plan is required', page); self.assertNotIn('Free access is on', page)
            # And back: payments off means free access again within one worker pass.
            store.set('billing_checkout', False, 'owner')
            self.assertEqual(self.worker()['open_access']['refreshed'], 2)   # re-activated rows
            self.assertTrue(b.get('/v1/costs', secure=True).json()['admission_eligible'])


class IngressLimitChecks(TestCase):
    new_client = AccountBoundaryTests.new_client
    post = AccountBoundaryTests.post
    signed = AccountBoundaryTests.signed
    setUp = AccountBoundaryTests.setUp

    def test_anonymous_ingress_is_limited_per_source_but_probes_and_webhooks_are_not(self):
        c = self.new_client()
        codes = [c.get('/account/login/', secure=True).status_code for _ in range(125)]
        self.assertEqual(codes[:120].count(429), 0); self.assertEqual(codes[120:], [429] * 5)
        for path in ('/healthz', '/readyz'): self.assertNotEqual(c.get(path, secure=True).status_code, 429)
        self.assertNotEqual(c.post('/v1/billing/webhook', '{}', content_type='application/json', secure=True).status_code, 429)

    def test_task_creation_is_limited_per_account(self):
        a = self.signed()
        from unittest.mock import patch
        with patch('accounts.requests.rate') as limited:
            self.post(a, '/v1/requests', {'message': 'hello', 'key': 'k1'})
            limited.assert_any_call('task.create', limited.call_args_list[0][0][1], 30, 3600)
