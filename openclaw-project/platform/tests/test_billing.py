"""Billing scenarios against a Stripe-shaped test provider. No network, no key, no live mode."""
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
from agentai_platform.billing import (BillingService, BillingConflict, BillingNotConfigured, Plan, PayloadTooLarge,
    ProviderUnavailable, SignatureInvalid, StripeHttp, derive_access, encode_form, micro, normalize_subscription,
    plan_from_plan_json, safe_invoice_url, signature_header, verify_signature, BillingError, MAX_ATTEMPTS)
from agentai_platform.budget import BudgetLedger, BudgetDenied
from agentai_platform.security import NotFound, Principal
from agentai_platform.store import Store
from tests.billing_fixture import FakeStripe, Events, PRICE, SECRET, MONTH

PLAN_JSON = json.loads((Path(__file__).resolve().parents[3] / 'product' / 'plan.json').read_text())
PLUS = Plan('builder-plus', 'price_plus_test', '149.00', micro('60.00'), micro('10.00'), micro('5.00'), 3)
HOUR = 3600


class Kit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'state' / 'db.sqlite3'); self.store.initialize()
        self.now = 2_000_000_000
        self.clock = lambda: self.now
        self.api = FakeStripe(self.clock); self.events = Events(self.clock)
        self.plan = plan_from_plan_json(PLAN_JSON, PRICE)
        self.svc = BillingService(self.store, self.api, [self.plan, PLUS], webhook_secrets=[SECRET], clock=self.clock)
        self.a, self.b = Principal('a', 'actor-a', 'customer'), Principal('b', 'actor-b', 'customer')
        self.ledger = BudgetLedger(self.store, service_limit_microusd=10**9, clock=self.clock)
        with self.store.connect() as con:
            for acct in ('a', 'b'):
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')", (acct,))
                con.execute("INSERT INTO memberships VALUES (?,?,'customer','active')", (acct, 'actor-' + acct))
                con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES (?,?,1,'stopped')", (acct, 'd-' + acct))
                con.execute('INSERT INTO projects(account_id,id,name) VALUES (?,?,?)', (acct, 'p-' + acct, 'P'))
                con.execute('INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES (?,?,?,?)', (acct, 'p-' + acct, 'c-' + acct, 'd-' + acct))
                limits = {'period_start_epoch': self.now - 100, 'period_microusd': 1_000_000, 'daily_microusd': 1_000_000,
                          'task_microusd': 5_000_000, 'max_queued_tasks': 3}
                con.execute("INSERT INTO entitlements VALUES (?,?,'launch-v1-proposed','trial',?,datetime(?,'unixepoch'))",
                            (acct, 'trial-v1', json.dumps(limits), self.now + 7 * 86400))

    # -- helpers
    def deliver(self, kind, obj, **kw): return self.events.deliver(self.svc, self.events.make(kind, obj, **kw))
    def drain(self): return self.svc.process(100)

    def subscribe(self, principal=None, price=PRICE):
        principal = principal or self.a
        out = self.svc.start_checkout(principal)
        sub = self.api.complete_checkout(out['session_id'], price)
        self.deliver('checkout.session.completed', {'id': out['session_id']})
        self.drain()
        return sub

    def entitlements(self, account='a'):
        with self.store.connect() as con:
            return {r['id']: (r['status'], r['plan_version']) for r in con.execute('SELECT * FROM entitlements WHERE account_id=?', (account,)).fetchall()}

    def sub_row(self, sub_id):
        with self.store.connect() as con:
            return dict(con.execute('SELECT * FROM billing_subscriptions WHERE provider_subscription_id=?', (sub_id,)).fetchone())

    def admit(self, task='t1', principal=None, amount=100_000):
        actor = principal or self.a
        return self.ledger.admit(actor, task=task, project='p-' + actor.account_id, conversation='c-' + actor.account_id, key=task,
                                 amount_microusd=amount, upper_bound_verified=True)

    def audit_count(self, like):
        with self.store.connect() as con:
            return con.execute("SELECT count(*) FROM audit_events WHERE action LIKE ?", (like,)).fetchone()[0]


class SignatureChecks(unittest.TestCase):
    BODY = b'{"id":"evt_1abcdef"}'
    def test_valid_and_tampered_and_wrong_secret(self):
        header = signature_header(self.BODY, SECRET, 1000)
        verify_signature(self.BODY, header, [SECRET], now=1000)
        for body, secret in [(self.BODY + b' ', SECRET), (self.BODY, 'whsec_' + 'b' * 32)]:
            with self.assertRaises(SignatureInvalid): verify_signature(body, signature_header(self.BODY, SECRET, 1000) if secret == SECRET else header, [secret], now=1000)
    def test_tolerance_replay_and_downgrade(self):
        header = signature_header(self.BODY, SECRET, 1000)
        verify_signature(self.BODY, header, [SECRET], now=1300)
        with self.assertRaises(SignatureInvalid): verify_signature(self.BODY, header, [SECRET], now=1301)
        with self.assertRaises(SignatureInvalid): verify_signature(self.BODY, header, [SECRET], now=699)
        with self.assertRaises(ValueError): verify_signature(self.BODY, header, [SECRET], now=1000, tolerance=0)
        v0 = header.replace(',v1=', ',v0=')
        with self.assertRaises(SignatureInvalid): verify_signature(self.BODY, v0, [SECRET], now=1000)
        for bad in ['', 't=abc,v1=' + 'a' * 64, 'v1=' + 'a' * 64, 't=1000', 't=1000,v1=zz']:
            with self.assertRaises(SignatureInvalid): verify_signature(self.BODY, bad, [SECRET], now=1000)
    def test_secret_rotation_accepts_either_and_missing_config_fails_closed(self):
        old, new = 'whsec_' + 'o' * 32, 'whsec_' + 'n' * 32
        for secret in (old, new): verify_signature(self.BODY, signature_header(self.BODY, secret, 1000), [old, new], now=1000)
        with self.assertRaises(BillingNotConfigured): verify_signature(self.BODY, signature_header(self.BODY, SECRET, 1000), [], now=1000)
    def test_one_header_can_carry_both_rolling_signatures(self):
        old, new = 'whsec_' + 'o' * 32, 'whsec_' + 'n' * 32
        header = signature_header(self.BODY, old, 1000) + ',v1=' + signature_header(self.BODY, new, 1000).split('v1=')[1]
        verify_signature(self.BODY, header, [new], now=1000)


class PolicyChecks(unittest.TestCase):
    def sub(self, **kw):
        base = dict(provider_status='active', current_period_end=10_000, cancel_at_period_end=0, past_due_since=None, fully_refunded=0, disputed=0)
        base.update(kw); return base
    def test_active_runs_to_period_end_even_when_cancelling(self):
        self.assertEqual(derive_access(self.sub(), 5000).status, 'active')
        self.assertEqual(derive_access(self.sub(cancel_at_period_end=1), 5000).reason, 'cancel_at_period_end')
        self.assertEqual(derive_access(self.sub(), 10_000).status, 'expired')
    def test_past_due_gets_exactly_the_grace_window(self):
        s = self.sub(provider_status='past_due', past_due_since=1000)
        self.assertEqual(derive_access(s, 1000 + 72 * HOUR - 1).status, 'grace')
        self.assertEqual(derive_access(s, 1000 + 72 * HOUR).status, 'expired')
    def test_every_other_provider_state_denies_and_refund_dispute_override(self):
        for status in ('canceled', 'unpaid', 'incomplete', 'incomplete_expired', 'paused', 'trialing', 'mystery'):
            self.assertEqual(derive_access(self.sub(provider_status=status), 5000).status, 'expired', status)
        self.assertEqual(derive_access(self.sub(disputed=1), 5000).status, 'suspended')
        self.assertEqual(derive_access(self.sub(fully_refunded=1), 5000).status, 'expired')
    def test_subscription_periods_come_from_items_and_multiple_lines_fail_closed(self):
        raw = {'id': 'sub_abc123', 'customer': 'cus_abc123', 'status': 'active', 'items': {'data': [
            {'current_period_start': 10, 'current_period_end': 20, 'price': {'id': 'price_x'}}]}}
        snap = normalize_subscription(raw)
        self.assertEqual((snap['current_period_start'], snap['current_period_end'], snap['price_id']), (10, 20, 'price_x'))
        raw['items']['data'].append({'current_period_start': 10, 'current_period_end': 30, 'price': {'id': 'price_y'}})
        self.assertIsNone(normalize_subscription(raw)['price_id'])
        with self.assertRaises(BillingError): normalize_subscription({'id': 'nope', 'customer': 'cus_abc123'})
    def test_invoice_links_must_be_provider_hosted_https(self):
        self.assertTrue(safe_invoice_url('https://invoice.stripe.com/i/x'))
        for bad in ['http://invoice.stripe.com/i', 'https://evil.example/i', 'https://stripe.com.evil.example/i', 'javascript:alert(1)', None]:
            self.assertIsNone(safe_invoice_url(bad))


class CheckoutChecks(Kit):
    def test_everything_sensitive_is_derived_server_side(self):
        out = self.svc.start_checkout(self.a)
        params = self.api.sessions[out['session_id']]['params']
        self.assertEqual((params['mode'], params['client_reference_id'], params['line_items']), ('subscription', 'a', [{'price': PRICE, 'quantity': 1}]))
        self.assertTrue(params['success_url'].startswith('https://getlumina.pro/account/billing/'))
        self.assertEqual(self.api.customers[params['customer']]['metadata']['account_id'], 'a')
    def test_redirect_alone_never_grants_access(self):
        self.svc.start_checkout(self.a)
        self.assertEqual(self.svc.overview(self.a)['status'], 'none')
        self.assertEqual(self.ledger.summary(self.a)['period_limit_microusd'], 1_000_000)   # still the $1 trial allowance
        self.assertNotIn('paid', self.entitlements())
    def test_duplicate_click_reuses_the_hosted_session(self):
        first = self.svc.start_checkout(self.a); second = self.svc.start_checkout(self.a)
        self.assertEqual(first['session_id'], second['session_id']); self.assertTrue(second['reused'])
        self.assertEqual(self.api.calls.count('create_checkout_session'), 1)
    def test_outage_then_retry_reuses_the_same_idempotency_key(self):
        self.api.down = 0
        self.svc._customer(self.a)
        self.api.down = 1
        with self.assertRaises(ProviderUnavailable): self.svc.start_checkout(self.a)
        with self.store.connect() as con:
            op = con.execute("SELECT state,idempotency_key FROM billing_operations WHERE kind='create_checkout'").fetchone()
        self.assertEqual(op['state'], 'uncertain')
        out = self.svc.start_checkout(self.a)
        with self.store.connect() as con:
            ops = con.execute("SELECT state,idempotency_key FROM billing_operations WHERE kind='create_checkout'").fetchall()
        self.assertEqual(len(ops), 1); self.assertEqual(ops[0]['state'], 'applied'); self.assertEqual(ops[0]['idempotency_key'], op['idempotency_key'])
        self.assertEqual(len(self.api.sessions), 1); self.assertTrue(out['url'].startswith('https://checkout.stripe.com/'))
    def test_already_subscribed_cannot_check_out_again_and_accounts_do_not_mix(self):
        self.subscribe(self.a)
        with self.assertRaises(BillingConflict): self.svc.start_checkout(self.a)
        out_b = self.svc.start_checkout(self.b)
        self.assertNotEqual(self.api.sessions[out_b['session_id']]['customer'], next(iter(self.api.customers)))
        self.assertEqual(self.svc.overview(self.b)['status'], 'none')
    def test_portal_needs_a_customer_and_a_customer_role(self):
        with self.assertRaises(NotFound): self.svc.portal_url(self.a)
        self.svc.start_checkout(self.a)
        self.assertTrue(self.svc.portal_url(self.a)['url'].startswith('https://billing.stripe.com/'))
        with self.assertRaises(NotFound): self.svc.start_checkout(Principal('a', 'x', 'operator'))
        with self.assertRaises(NotFound): self.svc.start_checkout(Principal('ghost', 'x', 'customer'))


class WebhookChecks(Kit):
    def test_invalid_oversize_and_live_events_are_refused_and_not_stored(self):
        body = self.events.body(self.events.make('customer.subscription.updated', {'id': 'sub_x1x1x1'}))
        with self.assertRaises(SignatureInvalid): self.svc.ingest(body, signature_header(body, 'whsec_' + 'z' * 32, self.now))
        with self.assertRaises(PayloadTooLarge): self.svc.ingest(b'x' * 300000, 'sig')
        live = self.events.body(self.events.make('customer.subscription.updated', {'id': 'sub_x1x1x1'}, livemode=True))
        with self.assertRaises(BillingError): self.svc.ingest(live, signature_header(live, SECRET, self.now))
        with self.assertRaises(BillingError): self.svc.ingest(b'not json', signature_header(b'not json', SECRET, self.now))
        with self.assertRaises(BillingError):
            bad = json.dumps({'id': 'evil', 'type': 'x', 'created': 1}).encode(); self.svc.ingest(bad, signature_header(bad, SECRET, self.now))
        with self.store.connect() as con: self.assertEqual(con.execute('SELECT count(*) FROM billing_inbox').fetchone()[0], 0)
    def test_acknowledged_only_after_persistence_and_duplicates_collapse(self):
        event = self.events.make('customer.created', {'id': 'cus_zzzzzz'})
        self.assertEqual(self.events.deliver(self.svc, event), 'stored')
        self.assertEqual(self.events.deliver(self.svc, event), 'duplicate')      # lost acknowledgment: provider retries
        with self.store.connect() as con: self.assertEqual(con.execute('SELECT count(*) FROM billing_inbox').fetchone()[0], 1)
    def test_unknown_event_types_are_ignored_not_failed(self):
        self.deliver('radar.something.new', {'id': 'x'})
        self.assertEqual(self.drain()['ignored'], 1)


class LifecycleChecks(Kit):
    def test_checkout_to_active_closes_the_trial_and_admits_tasks(self):
        sub = self.subscribe()
        self.assertEqual(self.entitlements()['paid'][0], 'active'); self.assertEqual(self.entitlements()['trial-v1'][0], 'expired')
        self.assertEqual(self.sub_row(sub['id'])['access_state'], 'active')
        self.assertTrue(self.admit()['state'] == 'active')
        view = self.svc.overview(self.a, usage=self.ledger.summary(self.a))
        self.assertEqual((view['status'], view['new_tasks_allowed'], view['can_subscribe']), ('active', True, False))
        self.assertEqual(view['plan']['monthly_price_usd'], '79.00'); self.assertEqual(view['usage']['period_limit_microusd'], 25_000_000)
        self.assertEqual(len(view['invoices']), 1); self.assertTrue(view['invoices'][0]['url'].startswith('https://invoice.stripe.com/'))
    def test_replaying_every_event_changes_nothing_a_second_time(self):
        sub = self.subscribe()
        before = (self.entitlements(), self.sub_row(sub['id']), self.audit_count('billing.access%'))
        for kind, obj in [('customer.subscription.updated', {'id': sub['id']}), ('invoice.paid', {'id': sub['latest_invoice'], 'subscription': sub['id']})]:
            for _ in range(3): self.deliver(kind, obj)
            self.drain()
        after = (self.entitlements(), self.sub_row(sub['id']), self.audit_count('billing.access%'))
        self.assertEqual(before[0], after[0]); self.assertEqual(before[2], after[2])
        self.assertEqual({k: v for k, v in before[1].items() if k not in ('synced_epoch', 'updated_epoch')},
                         {k: v for k, v in after[1].items() if k not in ('synced_epoch', 'updated_epoch')})
    def test_out_of_order_delivery_converges_on_the_canonical_state(self):
        out = self.svc.start_checkout(self.a); sub = self.api.complete_checkout(out['session_id'])
        # invoice and subscription events arrive before the checkout completion; a stale body is irrelevant
        self.deliver('invoice.paid', {'id': sub['latest_invoice'], 'subscription': sub['id']}, created=self.now + 5)
        self.deliver('customer.subscription.created', {'id': sub['id'], 'status': 'incomplete'}, created=self.now - 50)
        self.deliver('checkout.session.completed', {'id': out['session_id']}, created=self.now + 1)
        self.drain()
        self.assertEqual(self.sub_row(sub['id'])['access_state'], 'active'); self.assertEqual(self.entitlements()['paid'][0], 'active')
    def test_renewal_extends_and_resets_the_period_allowance(self):
        sub = self.subscribe(); start = self.sub_row(sub['id'])['current_period_start']
        self.now += MONTH - 100; self.admit('t1', amount=100_000)
        self.now += 200
        inv = self.api.renew(sub['id']); self.deliver('invoice.paid', {'id': inv, 'subscription': sub['id']}); self.drain()
        row = self.sub_row(sub['id']); self.assertGreater(row['current_period_start'], start); self.assertEqual(row['access_state'], 'active')
        with self.store.connect() as con:
            limits = json.loads(con.execute("SELECT limits_json FROM entitlements WHERE id='paid'").fetchone()[0])
        self.assertEqual(limits['period_start_epoch'], row['current_period_start'])
    def test_missed_renewal_webhook_still_ends_access_at_the_period_end(self):
        self.subscribe(); self.admit('t1')
        self.now += MONTH + 1
        with self.assertRaises(BudgetDenied): self.admit('t2')   # valid_until already passed: no webhook needed
        self.assertEqual(self.svc.sweep(), 1); self.assertEqual(self.entitlements()['paid'][0], 'expired')


class FailureAndRecoveryChecks(Kit):
    def test_payment_failure_grace_then_block_then_recovery(self):
        sub = self.subscribe(); self.now += MONTH
        inv = self.api.fail_payment(sub['id'])
        self.deliver('invoice.payment_failed', {'id': inv, 'subscription': sub['id']}); self.drain()
        self.assertEqual(self.entitlements()['paid'][0], 'grace'); self.assertTrue(self.admit('g1'))
        self.assertTrue(self.svc.overview(self.a)['new_tasks_allowed']); self.assertEqual(self.svc.overview(self.a)['grace_ends'], self.now + 72 * HOUR)
        self.now += 72 * HOUR - 1; self.assertTrue(self.admit('g2'))
        self.now += 1
        with self.assertRaises(BudgetDenied): self.admit('g3')
        self.svc.sweep(); self.assertEqual(self.entitlements()['paid'][0], 'expired')
        inv = self.api.renew(sub['id']); self.deliver('invoice.paid', {'id': inv, 'subscription': sub['id']}); self.drain()
        self.assertEqual(self.entitlements()['paid'][0], 'active'); self.assertTrue(self.admit('g4'))
    def test_running_work_drains_after_access_ends_but_nothing_new_starts(self):
        sub = self.subscribe(); running = self.admit('r1')
        self.now += MONTH + 10; self.svc.sweep()
        with self.assertRaises(BudgetDenied): self.admit('r2')
        self.ledger.receipt(account='a', task='r1', provider='p', request='q1', amount_microusd=40_000, observed_epoch=self.now,
                            price_version='v1', payload_hash='a' * 64)
        self.assertTrue(self.ledger.settle(account='a', task='r1', effects_quiesced=True, all_routes_reconciled=True))
        summary = self.ledger.summary(self.a); self.assertFalse(summary['admission_eligible']); self.assertEqual(summary['reported_microusd'], 40_000)
    def test_cancel_at_period_end_keeps_access_then_deleted_event_ends_it(self):
        sub = self.subscribe(); self.api.subs[sub['id']]['cancel_at_period_end'] = True
        self.deliver('customer.subscription.updated', {'id': sub['id']}); self.drain()
        view = self.svc.overview(self.a); self.assertTrue(view['cancel_at_period_end']); self.assertEqual(view['status'], 'active')
        self.now += MONTH - 10; self.assertTrue(self.admit('c1'))
        self.now += 20; self.api.subs[sub['id']]['status'] = 'canceled'
        self.deliver('customer.subscription.deleted', {'id': sub['id']}); self.drain()
        self.assertEqual(self.entitlements()['paid'][0], 'expired')
    def test_immediate_cancellation_ends_access_now(self):
        sub = self.subscribe(); self.api.subs[sub['id']]['status'] = 'canceled'
        self.deliver('customer.subscription.deleted', {'id': sub['id']}); self.drain()
        with self.assertRaises(BudgetDenied): self.admit()
    def test_stripe_trial_and_unknown_price_are_not_access(self):
        out = self.svc.start_checkout(self.a); sub = self.api.complete_checkout(out['session_id']); self.api.subs[sub['id']]['status'] = 'trialing'
        self.deliver('checkout.session.completed', {'id': out['session_id']}); self.drain()
        self.assertEqual(self.entitlements()['paid'][0], 'expired')
        self.api.subs[sub['id']]['status'] = 'active'; self.api.change_price(sub['id'], 'price_mystery')
        self.deliver('customer.subscription.updated', {'id': sub['id']}); self.drain()
        self.assertEqual(self.sub_row(sub['id'])['access_reason'], 'unknown_price')


class GraceFromPlanChecks(Kit):
    def test_grace_window_comes_from_the_approved_plan_file(self):
        self.assertEqual(self.svc.grace_hours, 72)
        short = BillingService(self.store, self.api, [plan_from_plan_json({**PLAN_JSON, 'billing_grace_hours': 24}, PRICE)], webhook_secrets=[SECRET], clock=self.clock)
        self.assertEqual(short.grace_hours, 24)


class PlanChangeChecks(Kit):
    def test_upgrade_and_downgrade_change_limits_without_a_new_period(self):
        sub = self.subscribe()
        self.api.change_price(sub['id'], PLUS.price_id); self.deliver('customer.subscription.updated', {'id': sub['id']}); self.drain()
        with self.store.connect() as con: limits = json.loads(con.execute("SELECT limits_json FROM entitlements WHERE id='paid'").fetchone()[0])
        self.assertEqual((limits['period_microusd'], self.entitlements()['paid'][1]), (60_000_000, 'builder-plus'))
        self.api.change_price(sub['id'], PRICE); self.deliver('customer.subscription.updated', {'id': sub['id']}); self.drain()
        with self.store.connect() as con: limits = json.loads(con.execute("SELECT limits_json FROM entitlements WHERE id='paid'").fetchone()[0])
        self.assertEqual((limits['period_microusd'], self.entitlements()['paid'][1]), (25_000_000, 'launch-v1-proposed'))
    def test_downgrade_below_current_spend_denies_new_tasks_only(self):
        sub = self.subscribe(price=PLUS.price_id)
        for day in range(3):                          # $30 spent over three days (daily cap $10, task cap $5)
            self.now += 86401
            for k in range(2):
                task = f'd{day}{k}'
                self.admit(task, amount=5_000_000)
                self.ledger.receipt(account='a', task=task, provider='p', request='r' + task, amount_microusd=5_000_000,
                                    observed_epoch=self.now, price_version='v', payload_hash='c' * 64)
                with self.store.connect() as con: con.execute("UPDATE tasks SET state='completed' WHERE id=?", (task,))
        self.now += 86401; self.admit('still-ok', amount=100_000)        # under the $60 allowance, new day
        self.api.change_price(sub['id'], PRICE); self.deliver('customer.subscription.updated', {'id': sub['id']}); self.drain()
        with self.assertRaises(BudgetDenied): self.admit('after')   # $30 already exceeds the $25 allowance
        self.assertEqual(self.ledger.summary(self.a)['reported_microusd'], 30_000_000)   # receipts untouched


class RefundDisputeChecks(Kit):
    def charge_of(self, sub): return self.api.invoices[sub['latest_invoice']]['charge']
    def test_full_refund_stops_new_tasks_partial_does_not_and_renewal_restores(self):
        sub = self.subscribe(); ch = self.charge_of(sub)
        self.api.refund(ch, 1000); self.deliver('charge.refunded', {'id': ch}); self.drain()
        self.assertEqual(self.entitlements()['paid'][0], 'active')                 # partial: unchanged
        self.api.refund(ch); self.deliver('charge.refunded', {'id': ch}); self.drain()
        self.assertEqual(self.entitlements()['paid'][0], 'expired')
        self.assertEqual(self.ledger.summary(self.a)['reported_microusd'], 0)      # receipts are never rewritten
        self.now += 5; inv = self.api.renew(sub['id']); self.deliver('invoice.paid', {'id': inv, 'subscription': sub['id']}); self.drain()
        self.assertEqual(self.entitlements()['paid'][0], 'active')
    def test_dispute_suspends_then_won_restores_and_lost_ends(self):
        sub = self.subscribe(); ch = self.charge_of(sub)
        did = self.api.dispute(ch); self.deliver('charge.dispute.created', {'id': did}); self.drain()
        self.assertEqual(self.entitlements()['paid'][0], 'suspended')
        with self.assertRaises(BudgetDenied): self.admit()
        self.api.disputes[did]['status'] = 'won'; self.deliver('charge.dispute.closed', {'id': did}); self.drain()
        self.assertEqual(self.entitlements()['paid'][0], 'active')
        did2 = self.api.dispute(ch); self.api.disputes[did2]['status'] = 'lost'
        self.deliver('charge.dispute.closed', {'id': did2}); self.drain()
        self.assertEqual(self.entitlements()['paid'][0], 'expired')
    def test_dispute_events_in_reverse_order_end_in_the_final_state(self):
        sub = self.subscribe(); ch = self.charge_of(sub); did = self.api.dispute(ch, status='won')
        self.deliver('charge.dispute.closed', {'id': did}, created=self.now + 10)
        self.deliver('charge.dispute.created', {'id': did}, created=self.now); self.drain()
        self.assertEqual(self.entitlements()['paid'][0], 'active')


class InboxAndReconcileChecks(Kit):
    def test_provider_outage_retries_with_backoff_then_succeeds(self):
        out = self.svc.start_checkout(self.a); sub = self.api.complete_checkout(out['session_id'])
        self.deliver('checkout.session.completed', {'id': out['session_id']})
        self.api.down = 1; self.assertEqual(self.drain()['retry'], 1)
        self.assertEqual(self.drain(), {'applied': 0, 'ignored': 0, 'retry': 0, 'dead': 0})   # not yet due
        self.now += 301; self.assertEqual(self.drain()['applied'], 1)
        self.assertEqual(self.entitlements()['paid'][0], 'active')
    def test_permanent_failures_are_dead_lettered_and_visible(self):
        self.deliver('customer.subscription.updated', {'id': 'sub_neverseen1'})
        self.api.subs['sub_neverseen1'] = {'id': 'sub_neverseen1', 'customer': 'cus_stranger1', 'status': 'active',
                                           'items': {'data': [{'current_period_start': 1, 'current_period_end': 2**31, 'price': {'id': PRICE}}]}}
        self.deliver('checkout.session.completed', {'id': 'cs_notmine111'})
        report = self.drain(); self.assertEqual(report['dead'], 2)
        self.assertEqual(self.svc.reconcile()['dead_letters'], 2); self.assertEqual(self.svc.overview(self.a)['dead_letters'], 2)
        self.assertNotIn('paid', self.entitlements())
    def test_endless_outage_dead_letters_after_the_attempt_limit(self):
        out = self.svc.start_checkout(self.a); self.api.complete_checkout(out['session_id'])
        self.deliver('checkout.session.completed', {'id': out['session_id']}); self.api.down = 10**6
        for _ in range(MAX_ATTEMPTS + 1):
            self.drain(); self.now += 7 * HOUR
        with self.store.connect() as con: self.assertEqual(con.execute("SELECT status FROM billing_inbox").fetchone()[0], 'dead')
    def test_reconcile_repairs_drift_when_a_webhook_was_never_delivered(self):
        sub = self.subscribe(); self.api.subs[sub['id']]['status'] = 'canceled'          # no event ever arrives
        self.assertEqual(self.entitlements()['paid'][0], 'active')
        report = self.svc.reconcile()
        self.assertEqual(report['drift'], [{'subscription': sub['id'][:12], 'was': 'active', 'now': 'expired'}])
        self.assertEqual(self.entitlements()['paid'][0], 'expired')
    def test_applied_events_drop_their_payload_but_keep_the_record(self):
        self.deliver('radar.something.new', {'id': 'x'}); self.drain()
        with self.store.connect() as con: row = con.execute('SELECT payload,status,payload_sha256 FROM billing_inbox').fetchone()
        self.assertEqual((row['payload'], row['status']), (None, 'ignored')); self.assertEqual(len(row['payload_sha256']), 64)
    def test_concurrent_processors_apply_each_event_once(self):
        sub = self.subscribe()
        for _ in range(3): self.deliver('customer.subscription.updated', {'id': sub['id']})
        self.deliver('invoice.paid', {'id': sub['latest_invoice'], 'subscription': sub['id']})
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.svc.process(100))) for _ in range(2)]
        [t.start() for t in threads]; [t.join() for t in threads]
        self.assertEqual(sum(r['applied'] for r in results), 4)   # each of the four events exactly once across both workers
        with self.store.connect() as con: self.assertEqual(con.execute("SELECT count(*) FROM billing_inbox WHERE status!='applied'").fetchone()[0], 0)


class AdmissionRaceChecks(Kit):
    def test_a_task_cannot_start_without_an_eligible_entitlement_and_reservation(self):
        self.subscribe(); self.admit('ok')
        self.assertEqual(self.ledger.summary(self.a)['held_microusd'], 100_000)
        sub = self.api.subs[next(iter(self.api.subs))]; sub['status'] = 'canceled'
        outcomes = []
        def start(n):
            try: outcomes.append(('ok', self.admit(f'race{n}')['task_id']))
            except BudgetDenied: outcomes.append(('denied', n))
        self.deliver('customer.subscription.deleted', {'id': sub['id']})
        threads = [threading.Thread(target=start, args=(n,)) for n in range(3)]
        [t.start() for t in threads]; self.drain(); [t.join() for t in threads]
        self.assertTrue(all(kind in ('ok', 'denied') for kind, _ in outcomes))
        self.drain()
        with self.assertRaises(BudgetDenied): self.admit('late')


class HttpClientChecks(unittest.TestCase):
    def client(self, key='sk_test_' + 'a' * 24, **kw):
        self.sent = []
        def opener(request, timeout):
            self.sent.append(request)
            return io.BytesIO(json.dumps({'id': 'cus_okokok', 'url': 'https://x'}).encode()).__class__(b'') if False else _Resp(json.dumps({'id': 'cus_okokok'}).encode())
        return StripeHttp(lambda: key, kw.pop('version', '2025-09-30.clover'), opener=kw.pop('opener', opener), **kw)
    def test_requests_are_pinned_authenticated_and_idempotent(self):
        c = self.client(); c.create_checkout_session({'mode': 'subscription', 'line_items': [{'price': 'price_x', 'quantity': 1}],
                                                      'metadata': {'account_id': 'a'}}, 'chk-a-1')
        r = self.sent[0]
        self.assertEqual((r.get_header('Authorization'), r.get_header('Stripe-version'), r.get_header('Idempotency-key')),
                         ('Bearer sk_test_' + 'a' * 24, '2025-09-30.clover', 'chk-a-1'))
        body = r.data.decode()
        for part in ('mode=subscription', 'line_items%5B0%5D%5Bprice%5D=price_x', 'line_items%5B0%5D%5Bquantity%5D=1', 'metadata%5Baccount_id%5D=a'):
            self.assertIn(part, body)
        c.retrieve_subscription('sub_abc123'); self.assertIsNone(self.sent[1].get_header('Idempotency-key')); self.assertEqual(self.sent[1].get_method(), 'GET')
    def test_live_keys_missing_keys_and_unpinned_versions_are_refused(self):
        with self.assertRaises(BillingNotConfigured): self.client(key='sk_live_' + 'a' * 24).retrieve_subscription('sub_abc123')
        self.assertEqual(self.sent, [])
        self.client(key='sk_live_' + 'a' * 24, allow_live=True).retrieve_subscription('sub_abc123')
        for key in ('', 'whsec_' + 'a' * 30, 'sk_test_short'):
            with self.assertRaises(BillingNotConfigured): self.client(key=key).retrieve_subscription('sub_abc123')
        with self.assertRaises(BillingNotConfigured): StripeHttp(lambda: 'sk_test_' + 'a' * 24, '')
        with self.assertRaises(BillingNotConfigured): StripeHttp(lambda: 'k', '2025-09-30.clover', base='http://api.stripe.com')
    def test_status_codes_map_to_retry_or_reject(self):
        def failing(code):
            def opener(request, timeout): raise urllib.error.HTTPError(request.full_url, code, 'x', {}, None)
            return opener
        from agentai_platform.billing import ProviderRejected
        for code in (429, 500, 503):
            with self.assertRaises(ProviderUnavailable): self.client(opener=failing(code)).retrieve_subscription('sub_abc123')
        with self.assertRaises(ProviderRejected): self.client(opener=failing(402)).retrieve_subscription('sub_abc123')
        def down(request, timeout): raise urllib.error.URLError('dns')
        with self.assertRaises(ProviderUnavailable): self.client(opener=down).retrieve_subscription('sub_abc123')
    def test_form_encoding(self):
        self.assertEqual(encode_form({'a': {'b': [1, {'c': True}]}, 'n': None}), [('a[b][0]', '1'), ('a[b][1][c]', 'true')])


class _Resp:
    def __init__(self, data): self.data = data
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self, n=-1): return self.data

if __name__ == '__main__': unittest.main()
