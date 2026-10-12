"""Stripe-shaped test provider: in-memory objects, idempotency, event builders and signing.

Mirrors only the documented behaviors the service relies on (verified 2026-10-12): idempotency
keys replay the first response, period fields live on subscription items, events carry object
snapshots that may be stale, and the API can fail with 5xx. It is a test double, not Stripe.
"""
import copy
import json
import itertools
from agentai_platform.billing import ProviderUnavailable, ProviderRejected, signature_header

MONTH = 30 * 86400
PRICE = 'price_builder_test'
SECRET = 'whsec_' + 'a' * 32


class FakeStripe:
    def __init__(self, clock):
        self.clock = clock
        self.n = itertools.count(1)
        self.customers, self.subs, self.invoices, self.charges, self.disputes, self.sessions = {}, {}, {}, {}, {}, {}
        self.idem, self.calls, self.down = {}, [], 0
        self.charge_sub = {}

    def _call(self, name):
        self.calls.append(name)
        if self.down:
            self.down -= 1
            raise ProviderUnavailable('simulated outage')

    def _id(self, prefix): return f'{prefix}_{next(self.n):06d}abc'

    def _replay(self, key, make):
        if key in self.idem: return copy.deepcopy(self.idem[key])
        self.idem[key] = make()
        return copy.deepcopy(self.idem[key])

    # ---- mutations the service performs
    def create_customer(self, account_id, idem):
        self._call('create_customer')
        def make():
            cid = self._id('cus'); self.customers[cid] = {'id': cid, 'metadata': {'account_id': account_id}}
            return self.customers[cid]
        return self._replay(idem, make)

    def create_checkout_session(self, params, idem):
        self._call('create_checkout_session')
        def make():
            sid = self._id('cs')
            self.sessions[sid] = {'id': sid, 'url': f'https://checkout.stripe.com/c/pay/{sid}', 'status': 'open', 'mode': params['mode'],
                                  'customer': params['customer'], 'params': params, 'subscription': None,
                                  'expires_at': self.clock() + 1800, 'payment_status': 'unpaid'}
            return self.sessions[sid]
        return self._replay(idem, make)

    def create_portal_session(self, customer, return_url, idem):
        self._call('create_portal_session')
        return {'id': self._id('bps'), 'url': 'https://billing.stripe.com/p/session/test_' + customer, 'customer': customer}

    # ---- retrievals
    def retrieve_subscription(self, sub_id):
        self._call('retrieve_subscription'); return copy.deepcopy(self.subs[sub_id])
    def retrieve_checkout_session(self, sid):
        self._call('retrieve_checkout_session'); return copy.deepcopy(self.sessions[sid])
    def retrieve_invoice(self, iid):
        self._call('retrieve_invoice'); return copy.deepcopy(self.invoices[iid])
    def retrieve_charge(self, cid):
        self._call('retrieve_charge'); return copy.deepcopy(self.charges[cid])
    def retrieve_dispute(self, did):
        self._call('retrieve_dispute'); return copy.deepcopy(self.disputes[did])
    def subscription_for_charge(self, charge_id):
        self._call('subscription_for_charge'); return self.charge_sub.get(charge_id)

    # ---- provider-side state changes used by scenarios
    def complete_checkout(self, sid, price=PRICE):
        session = self.sessions[sid]; now = self.clock()
        sub = self.new_subscription(session['customer'], price)
        session.update(status='complete', subscription=sub['id'], payment_status='paid')
        return sub

    def new_subscription(self, customer, price=PRICE, status='active'):
        now = self.clock(); sid = self._id('sub')
        self.subs[sid] = {'id': sid, 'object': 'subscription', 'customer': customer, 'status': status, 'cancel_at_period_end': False,
                          'items': {'data': [{'id': 'si_1', 'current_period_start': now, 'current_period_end': now + MONTH,
                                              'price': {'id': price}, 'quantity': 1}]}, 'latest_invoice': None}
        self.pay_invoice(sid)
        return self.subs[sid]

    def pay_invoice(self, sub_id, paid=True):
        sub = self.subs[sub_id]; item = sub['items']['data'][0]; iid = self._id('in'); ch = self._id('ch')
        self.invoices[iid] = {'id': iid, 'customer': sub['customer'], 'subscription': sub_id, 'status': 'paid' if paid else 'open',
                              'amount_due': 7900, 'amount_paid': 7900 if paid else 0, 'currency': 'usd', 'created': self.clock(),
                              'hosted_invoice_url': f'https://invoice.stripe.com/i/test/{iid}', 'period_start': item['current_period_start'],
                              'period_end': item['current_period_end']}
        sub['latest_invoice'] = iid
        if paid:
            self.charges[ch] = {'id': ch, 'amount': 7900, 'amount_refunded': 0, 'refunded': False, 'payment_intent': 'pi_' + ch}
            self.charge_sub[ch] = sub_id
            self.invoices[iid]['charge'] = ch
        return iid

    def renew(self, sub_id):
        sub = self.subs[sub_id]; item = sub['items']['data'][0]
        item['current_period_start'], item['current_period_end'] = item['current_period_end'], item['current_period_end'] + MONTH
        sub['status'] = 'active'
        return self.pay_invoice(sub_id)

    def fail_payment(self, sub_id):
        self.subs[sub_id]['status'] = 'past_due'
        return self.pay_invoice(sub_id, paid=False)

    def change_price(self, sub_id, price):
        self.subs[sub_id]['items']['data'][0]['price'] = {'id': price}

    def refund(self, ch, amount=None):
        c = self.charges[ch]; c['amount_refunded'] = amount if amount is not None else c['amount']; c['refunded'] = c['amount_refunded'] == c['amount']

    def dispute(self, ch, status='needs_response'):
        did = self._id('dp'); self.disputes[did] = {'id': did, 'charge': ch, 'status': status}
        self.charge_sub.setdefault(ch, self.charge_sub.get(ch)); return did


class Events:
    def __init__(self, clock): self.clock, self.n = clock, itertools.count(1)

    def make(self, kind, obj, *, created=None, livemode=False, ident=None):
        return {'id': ident or f'evt_{next(self.n):08d}test', 'object': 'event', 'type': kind, 'created': created or self.clock(),
                'livemode': livemode, 'data': {'object': obj}}

    @staticmethod
    def body(event): return json.dumps(event, separators=(',', ':')).encode()

    def deliver(self, service, event, secret=SECRET, stamp=None):
        body = self.body(event)
        return service.ingest(body, signature_header(body, secret, stamp or self.clock()))
