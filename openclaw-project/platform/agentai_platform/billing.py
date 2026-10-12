"""Hosted billing: Stripe test-mode checkout/portal, webhook inbox, access reconciliation.

Commercial access is derived only from verified provider state and written to the same
`entitlements` table the Phase 5 budget ledger already reads, so no task can start without
an eligible entitlement and a reservation. A browser redirect never grants access. Card
details stay with the hosted provider; the secret key is read from a private file at call
time and never stored, logged or returned. Live keys are refused unless the owner has
explicitly authorized live mode. Provider event ordering is not trusted: every subscription,
refund and dispute event triggers a fetch of the canonical object and a recompute.

Verified against Stripe's documentation on 2026-10-12 (see plans/product/phase-13.md):
signature scheme `t=<ts>,v1=<hmac>` over `<ts>.<raw body>`, 5 minute tolerance, events may
arrive duplicated or out of order, `Idempotency-Key` header (<=255 chars, kept >=24h),
subscription period fields live on subscription items, `invoice.paid` must be confirmed
against an `active` subscription before extending access.
"""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
import calendar
import hashlib
import hmac
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .security import NotFound, Principal

MAX_BODY = 262144
TOLERANCE = 300
GRACE_HOURS = 72
EVENT_ID = re.compile(r'evt_[A-Za-z0-9_]{6,120}')
OBJECT_ID = re.compile(r'(cus|sub|in|cs|ch|dp|pi|price)_[A-Za-z0-9_]{3,120}')
MAX_ATTEMPTS = 8
REQUIRED_EVENTS = ('checkout.session.completed', 'customer.subscription.created', 'customer.subscription.updated',
                   'customer.subscription.deleted', 'customer.subscription.paused', 'customer.subscription.resumed',
                   'invoice.paid', 'invoice.payment_failed', 'invoice.payment_action_required', 'invoice.finalized',
                   'charge.refunded', 'charge.dispute.created', 'charge.dispute.updated', 'charge.dispute.closed')
WEBHOOK_PATH = '/v1/billing/webhook'
OPEN_ID = 'open'
OPEN_TTL = 3 * 86400   # open access lapses by itself if the worker stops refreshing it


class BillingError(Exception): pass
class BillingNotConfigured(BillingError): pass
class SignatureInvalid(BillingError): pass
class PayloadTooLarge(BillingError): pass
class ProviderUnavailable(BillingError): pass     # network/5xx/429: retry later
class ProviderRejected(BillingError): pass        # 4xx: do not blindly retry
class BillingConflict(BillingError): pass
class Unmapped(BillingError): pass                # object not created by this platform


# ------------------------------------------------------------------ signatures

def verify_signature(body: bytes, header: str, secrets, *, now, tolerance=TOLERANCE):
    """Raise SignatureInvalid unless a v1 signature over `t.body` matches any active secret."""
    if not secrets: raise BillingNotConfigured('webhook secret not configured')
    if type(tolerance) is not int or tolerance <= 0: raise ValueError('tolerance must be positive')
    stamp, signatures = None, []
    for element in (header or '').split(','):
        key, _, value = element.strip().partition('=')
        if key == 't' and value.isdigit(): stamp = int(value)
        elif key == 'v1' and re.fullmatch(r'[0-9a-f]{64}', value): signatures.append(value)
        # every other scheme (v0 test signatures included) is ignored to prevent downgrade
    if stamp is None or not signatures: raise SignatureInvalid('malformed signature header')
    signed = str(stamp).encode() + b'.' + body
    ok = False
    for secret in secrets:
        expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        ok = any(hmac.compare_digest(expected, s) for s in signatures) or ok
    if not ok: raise SignatureInvalid('signature mismatch')
    if abs(int(now) - stamp) > tolerance: raise SignatureInvalid('timestamp outside tolerance')


def signature_header(body: bytes, secret: str, stamp: int):
    """Build a valid header (fixtures and tests only; the provider produces these in production)."""
    return f't={stamp},v1=' + hmac.new(secret.encode(), str(stamp).encode() + b'.' + body, hashlib.sha256).hexdigest()


# --------------------------------------------------------------- provider access

def encode_form(params, prefix=''):
    """Stripe form encoding: nested dicts as a[b], lists as a[0]."""
    pairs = []
    for key, value in params.items():
        name = f'{prefix}[{key}]' if prefix else str(key)
        if isinstance(value, dict): pairs += encode_form(value, name)
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                pairs += encode_form({str(i): item}, name)
        elif isinstance(value, bool): pairs.append((name, 'true' if value else 'false'))
        elif value is not None: pairs.append((name, str(value)))
    return pairs


class StripeHttp:
    """Minimal stdlib client (no SDK dependency); the API version is pinned by configuration."""

    def __init__(self, key_reader, api_version, *, base='https://api.stripe.com', allow_live=False,
                 opener=urllib.request.urlopen, timeout=10):
        if not api_version or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}(\.[a-z]+)?', api_version):
            raise BillingNotConfigured('a pinned Stripe API version is required')
        if not base.startswith('https://'): raise BillingNotConfigured('https required')
        self.key_reader, self.version, self.base = key_reader, api_version, base.rstrip('/')
        self.allow_live, self.opener, self.timeout = allow_live, opener, timeout

    def _key(self):
        key = (self.key_reader() or '').strip()
        if not re.fullmatch(r'(sk|rk)_(test|live)_[A-Za-z0-9]{8,}', key): raise BillingNotConfigured('no usable provider key')
        if '_live_' in key and not self.allow_live: raise BillingNotConfigured('live mode is not authorized')
        return key

    def call(self, method, path, params=None, *, idem=None):
        key = self._key()
        data = urllib.parse.urlencode(encode_form(params or {})).encode() if method == 'POST' else None
        url = self.base + path + ('?' + urllib.parse.urlencode(encode_form(params)) if method == 'GET' and params else '')
        request = urllib.request.Request(url, data=data, method=method, headers={
            'Authorization': 'Bearer ' + key, 'Stripe-Version': self.version, 'User-Agent': 'agentai-billing/1'})
        if method == 'POST':
            request.add_header('Content-Type', 'application/x-www-form-urlencoded')
            if idem: request.add_header('Idempotency-Key', idem)
        try:
            with self.opener(request, timeout=self.timeout) as response:
                return json.loads(response.read(2 * 1024 * 1024))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 or exc.code >= 500: raise ProviderUnavailable(f'provider status {exc.code}') from None
            raise ProviderRejected(f'provider status {exc.code}') from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise ProviderUnavailable('provider unreachable') from None

    # -- the narrow surface the service uses
    def create_customer(self, account_id, idem):
        return self.call('POST', '/v1/customers', {'metadata': {'account_id': account_id}}, idem=idem)

    def create_checkout_session(self, params, idem):
        return self.call('POST', '/v1/checkout/sessions', params, idem=idem)

    def create_portal_session(self, customer, return_url, idem):
        return self.call('POST', '/v1/billing_portal/sessions', {'customer': customer, 'return_url': return_url}, idem=idem)

    def retrieve_subscription(self, sub_id): return self.call('GET', f'/v1/subscriptions/{sub_id}')
    def retrieve_checkout_session(self, session_id): return self.call('GET', f'/v1/checkout/sessions/{session_id}')
    def retrieve_invoice(self, invoice_id): return self.call('GET', f'/v1/invoices/{invoice_id}')
    def retrieve_charge(self, charge_id): return self.call('GET', f'/v1/charges/{charge_id}')
    def retrieve_dispute(self, dispute_id): return self.call('GET', f'/v1/disputes/{dispute_id}')

    def subscription_for_charge(self, charge_id):
        """Documented procedure (API >= 2025-03-31.basil): charge -> payment_intent -> invoice payment -> invoice."""
        charge = self.retrieve_charge(charge_id)
        intent = charge.get('payment_intent')
        if not intent: return None
        listing = self.call('GET', '/v1/invoice_payments', {'payment': {'type': 'payment_intent', 'payment_intent': intent},
                                                            'status': 'paid', 'limit': 10})
        for item in listing.get('data', []):
            invoice = self.retrieve_invoice(item.get('invoice'))
            detail = (invoice.get('parent') or {}).get('subscription_details') or {}
            if detail.get('subscription'): return detail['subscription']
        return None


# ------------------------------------------------------------------- plans/policy

@dataclass(frozen=True)
class Plan:
    version: str
    price_id: str
    monthly_price_usd: str
    included_microusd: int
    daily_microusd: int
    task_microusd: int
    max_queued: int
    grace_hours: int = GRACE_HOURS

    def limits(self, period_start):
        return {'period_start_epoch': int(period_start), 'period_microusd': self.included_microusd,
                'daily_microusd': self.daily_microusd, 'task_microusd': self.task_microusd,
                'max_queued_tasks': self.max_queued}


def micro(value):
    return int(Decimal(str(value)) * 1_000_000)


def plan_from_plan_json(plan, price_id):
    """Limits come from the approved plan file (product/plan.json), never from a client."""
    return Plan(plan['version'], price_id, plan['monthly_price_usd'], micro(plan['included_provider_cost_usd']),
                micro(plan['daily_provider_cost_usd']), micro(plan['max_task_cost_usd']), int(plan['max_queued_tasks']),
                int(plan.get('billing_grace_hours', GRACE_HOURS)))


@dataclass(frozen=True)
class Access:
    status: str          # active | grace | expired | suspended
    valid_until: int
    reason: str


def derive_access(sub, now, *, grace_hours=GRACE_HOURS) -> Access:
    """The whole access policy as one pure function.

    New tasks require status active/grace and now < valid_until. Cancellation at period end keeps
    access through the paid period. A failed payment gets the grace window, then blocks new tasks
    (running work drains; billing pages and export stay available). Refunds and disputes never
    rewrite usage receipts; they only stop new admissions. Reactivation requires a later verified
    paid state.
    """
    now = int(now)
    status = sub['provider_status']
    if sub.get('disputed'): return Access('suspended', now, 'dispute_open')
    if sub.get('fully_refunded'): return Access('expired', now, 'refunded')
    if status == 'active':
        end = sub.get('current_period_end') or 0
        if end > now: return Access('active', end, 'cancel_at_period_end' if sub.get('cancel_at_period_end') else 'paid')
        return Access('expired', now, 'period_ended')
    if status == 'past_due':
        since = sub.get('past_due_since') or now
        end = since + grace_hours * 3600
        if now < end: return Access('grace', end, 'payment_failed_grace')
        return Access('expired', now, 'grace_ended')
    return Access('expired', now, 'provider_' + str(status))


def normalize_subscription(raw):
    """Canonical subscription facts from a Stripe object; period fields live on the items."""
    if not isinstance(raw, dict) or raw.get('object') not in (None, 'subscription'): raise BillingError('not a subscription')
    sub_id, customer = raw.get('id'), raw.get('customer')
    if not (isinstance(sub_id, str) and OBJECT_ID.fullmatch(sub_id) and isinstance(customer, str) and OBJECT_ID.fullmatch(customer)):
        raise BillingError('invalid subscription identity')
    items = [i for i in ((raw.get('items') or {}).get('data') or []) if isinstance(i, dict)]
    ends = [i['current_period_end'] for i in items if isinstance(i.get('current_period_end'), int)]
    starts = [i['current_period_start'] for i in items if isinstance(i.get('current_period_start'), int)]
    end = max(ends) if ends else raw.get('current_period_end')
    start = min(starts) if starts else raw.get('current_period_start')
    price = ((items[0].get('price') or {}).get('id') if items else None)
    if len(items) > 1: price = None  # more than one line: not a plan we sold; fail closed
    return {'id': sub_id, 'customer': customer, 'provider_status': str(raw.get('status')),
            'cancel_at_period_end': bool(raw.get('cancel_at_period_end')),
            'current_period_start': start if isinstance(start, int) else None,
            'current_period_end': end if isinstance(end, int) else None, 'price_id': price,
            'latest_invoice': raw.get('latest_invoice') if isinstance(raw.get('latest_invoice'), str) else None}


def safe_invoice_url(url):
    if not isinstance(url, str): return None
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ''
    return url if parts.scheme == 'https' and (host == 'stripe.com' or host.endswith('.stripe.com')) else None


# ----------------------------------------------------------------------- service

class BillingService:
    def __init__(self, store, api, plans, *, webhook_secrets=(), clock=time.time, public_origin='https://getlumina.pro',
                 allow_live=False, grace_hours=None):
        self.store, self.api, self.clock = store, api, clock
        self.plans = {p.price_id: p for p in plans}
        self.default_plan = list(plans)[0] if plans else None
        self.secrets = tuple(webhook_secrets)
        self.origin = public_origin.rstrip('/')
        self.allow_live = allow_live
        # The approved plan file owns the grace window (billing_grace_hours); an override is for tests only.
        self.grace_hours = grace_hours or (self.default_plan.grace_hours if self.default_plan else GRACE_HOURS)

    @contextmanager
    def tx(self):
        if hasattr(self.store, 'transaction'):
            with self.store.transaction() as con: yield con
            return
        with self.store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            try:
                yield con
                con.execute('COMMIT')
            except Exception:
                con.execute('ROLLBACK')
                raise

    def _now(self): return int(self.clock())

    def _audit(self, con, account, actor, obj, action, outcome):
        con.execute('''INSERT INTO audit_events(account_id,id,actor_id,object_id,action,outcome,request_id)
            VALUES (?,?,?,?,?,?,?)''', (account, uuid.uuid4().hex, str(actor), str(obj)[:120], 'billing.' + action, outcome, uuid.uuid4().hex))

    # ------------------------------------------------------------ customer actions

    def _account(self, con, principal):
        if principal.role != 'customer': raise NotFound()
        row = con.execute('SELECT status FROM accounts WHERE id=?', (principal.account_id,)).fetchone()
        if not row or row['status'] != 'active': raise NotFound()

    def _customer(self, principal):
        account = principal.account_id
        with self.store.connect() as con:
            row = con.execute('SELECT provider_customer_id FROM billing_customers WHERE account_id=?', (account,)).fetchone()
        if row: return row['provider_customer_id']
        key = 'cust-' + account
        with self.tx() as con:
            con.execute('INSERT OR IGNORE INTO billing_operations VALUES (?,?,?,?,?,NULL,?,?)',
                        (uuid.uuid4().hex, account, 'create_customer', key, 'pending', self._now(), self._now()))
        try:
            created = self.api.create_customer(account, key)
        except ProviderUnavailable:
            with self.tx() as con:
                con.execute("UPDATE billing_operations SET state='uncertain',updated_epoch=? WHERE idempotency_key=?", (self._now(), key))
            raise
        customer = created.get('id') if isinstance(created, dict) else None
        if not (isinstance(customer, str) and OBJECT_ID.fullmatch(customer) and customer.startswith('cus_')):
            raise ProviderRejected('unexpected customer response')
        with self.tx() as con:
            con.execute('INSERT OR IGNORE INTO billing_customers VALUES (?,?,?)', (account, customer, self._now()))
            con.execute("UPDATE billing_operations SET state='applied',provider_ref=?,updated_epoch=? WHERE idempotency_key=?",
                        (customer, self._now(), key))
            stored = con.execute('SELECT provider_customer_id FROM billing_customers WHERE account_id=?', (account,)).fetchone()
        return stored['provider_customer_id']

    def start_checkout(self, principal: Principal):
        """Hosted checkout for the one configured plan. Account, price and quantity are server-derived."""
        if self.default_plan is None or self.api is None: raise BillingNotConfigured('billing is not configured')
        plan, account, now = self.default_plan, principal.account_id, self._now()
        with self.store.connect() as con:
            self._account(con, principal)
            live = con.execute("SELECT 1 FROM billing_subscriptions WHERE account_id=? AND access_state IN ('active','grace','suspended')",
                               (account,)).fetchone()
            if live: raise BillingConflict('already_subscribed')
            open_session = con.execute("SELECT provider_session_id,url FROM billing_checkout_sessions WHERE account_id=? AND state='open' "
                                       "AND expires_epoch>? ORDER BY created_epoch DESC LIMIT 1", (account, now)).fetchone()
            attempts = con.execute('SELECT count(*) FROM billing_checkout_sessions WHERE account_id=? AND plan_version=?',
                                   (account, plan.version)).fetchone()[0]
        if open_session:  # duplicate click: the same hosted session, no second provider call
            return {'url': open_session['url'], 'session_id': open_session['provider_session_id'], 'reused': True}
        customer = self._customer(principal)
        key = f'chk-{account}-{plan.version}-{attempts + 1}'
        params = {'mode': 'subscription', 'customer': customer, 'client_reference_id': account,
                  'line_items': [{'price': plan.price_id, 'quantity': 1}],
                  'success_url': self.origin + '/account/billing/?checkout=return',
                  'cancel_url': self.origin + '/account/billing/?checkout=cancelled',
                  'metadata': {'account_id': account}, 'subscription_data': {'metadata': {'account_id': account}}}
        with self.tx() as con:
            con.execute('INSERT OR IGNORE INTO billing_operations VALUES (?,?,?,?,?,NULL,?,?)',
                        (uuid.uuid4().hex, account, 'create_checkout', key, 'pending', now, now))
        try:
            session = self.api.create_checkout_session(params, key)
        except ProviderUnavailable:
            with self.tx() as con:
                con.execute("UPDATE billing_operations SET state='uncertain',updated_epoch=? WHERE idempotency_key=?", (self._now(), key))
            raise  # a retry reuses this exact key, so the provider returns the original session
        sid, url = session.get('id'), session.get('url')
        if not (isinstance(sid, str) and sid.startswith('cs_') and OBJECT_ID.fullmatch(sid) and isinstance(url, str)
                and urllib.parse.urlsplit(url).scheme == 'https'):
            raise ProviderRejected('unexpected checkout response')
        with self.tx() as con:
            con.execute('INSERT OR IGNORE INTO billing_checkout_sessions VALUES (?,?,?,?,?,?,?,?,?)',
                        (sid, account, plan.version, plan.price_id, key, url, 'open', now, int(session.get('expires_at') or now + 1800)))
            con.execute("UPDATE billing_operations SET state='applied',provider_ref=?,updated_epoch=? WHERE idempotency_key=?", (sid, now, key))
            self._audit(con, account, principal.actor_id, sid, 'checkout', 'pending')
        return {'url': url, 'session_id': sid, 'reused': False}

    def portal_url(self, principal: Principal):
        if self.api is None: raise BillingNotConfigured('billing is not configured')
        with self.store.connect() as con:
            self._account(con, principal)
            row = con.execute('SELECT provider_customer_id FROM billing_customers WHERE account_id=?', (principal.account_id,)).fetchone()
        if not row: raise NotFound()   # nothing to manage before a first checkout
        key = f'portal-{principal.account_id}-{self._now() // 300}'
        session = self.api.create_portal_session(row['provider_customer_id'], self.origin + '/account/billing/', key)
        url = session.get('url')
        if not (isinstance(url, str) and urllib.parse.urlsplit(url).scheme == 'https'): raise ProviderRejected('unexpected portal response')
        return {'url': url}

    # --------------------------------------------------------------- webhook inbox

    def ingest(self, body: bytes, header: str):
        """Verify over the raw body, persist, then acknowledge. Returns 'stored' or 'duplicate'."""
        if len(body) > MAX_BODY: raise PayloadTooLarge('body too large')
        verify_signature(body, header, self.secrets, now=self._now())
        try:
            event = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            raise BillingError('payload is not JSON') from None
        ident, kind, created = (event.get('id'), event.get('type'), event.get('created')) if isinstance(event, dict) else (None, None, None)
        if not (isinstance(ident, str) and EVENT_ID.fullmatch(ident) and isinstance(kind, str) and 1 <= len(kind) <= 100
                and type(created) is int):
            raise BillingError('invalid event envelope')
        if event.get('livemode') is True and not self.allow_live: raise BillingError('live events are not authorized')
        digest = hashlib.sha256(body).hexdigest()
        with self.tx() as con:
            existing = con.execute('SELECT 1 FROM billing_inbox WHERE event_id=?', (ident,)).fetchone()
            if existing: return 'duplicate'
            con.execute('''INSERT INTO billing_inbox(event_id,event_type,provider_created,payload_sha256,payload,status,received_epoch)
                VALUES (?,?,?,?,?,'received',?)''', (ident, kind, created, digest, body.decode(), self._now()))
        return 'stored'

    def process(self, limit=25):
        """Apply stored events: lease, handle, retry with backoff, dead-letter. One account's failure never blocks others."""
        report = {'applied': 0, 'ignored': 0, 'retry': 0, 'dead': 0}
        now = self._now()
        with self.tx() as con:
            rows = con.execute('''SELECT event_id FROM billing_inbox WHERE (status='received' AND next_attempt_epoch<=?)
                OR (status='processing' AND lease_until<=?) ORDER BY provider_created,event_id LIMIT ?''', (now, now, limit)).fetchall()
            ids = [r['event_id'] for r in rows]
            for ident in ids:
                con.execute("UPDATE billing_inbox SET status='processing',lease_until=?,attempts=attempts+1 WHERE event_id=?", (now + 120, ident))
        for ident in ids:
            with self.store.connect() as con:
                row = con.execute('SELECT event_type,provider_created,payload,attempts FROM billing_inbox WHERE event_id=?', (ident,)).fetchone()
            outcome, code = self._handle(row)
            now = self._now()
            if outcome == 'retry' and row['attempts'] >= MAX_ATTEMPTS: outcome, code = 'dead', code or 'attempts_exhausted'
            with self.tx() as con:
                if outcome in ('applied', 'ignored'):
                    con.execute("UPDATE billing_inbox SET status=?,payload=NULL,lease_until=NULL,error_code=NULL,processed_epoch=? WHERE event_id=?", (outcome, now, ident))
                elif outcome == 'dead':
                    con.execute("UPDATE billing_inbox SET status='dead',lease_until=NULL,error_code=?,processed_epoch=? WHERE event_id=?", (code, now, ident))
                else:
                    backoff = min(300 * 2 ** (row['attempts'] - 1), 6 * 3600)
                    con.execute("UPDATE billing_inbox SET status='received',lease_until=NULL,error_code=?,next_attempt_epoch=? WHERE event_id=?", (code, now + backoff, ident))
            report[outcome] += 1
        return report

    def _handle(self, row):
        try:
            event = json.loads(row['payload'])
            kind, obj = row['event_type'], (event.get('data') or {}).get('object') or {}
            stamp = row['provider_created']
            if kind == 'checkout.session.completed': return self._checkout_completed(obj, stamp)
            if kind in ('customer.subscription.created', 'customer.subscription.updated', 'customer.subscription.deleted',
                        'customer.subscription.paused', 'customer.subscription.resumed'):
                return self._sync(obj.get('id'), stamp)
            if kind in ('invoice.paid', 'invoice.payment_failed', 'invoice.payment_action_required', 'invoice.finalized'):
                detail = (obj.get('parent') or {}).get('subscription_details') or {}
                sub = obj.get('subscription') or detail.get('subscription')
                return self._sync(sub, stamp, invoice_id=obj.get('id'))
            if kind == 'charge.refunded': return self._refund(obj.get('id'), stamp)
            if kind in ('charge.dispute.created', 'charge.dispute.updated', 'charge.dispute.closed'):
                return self._dispute(obj.get('id'), stamp)
            return 'ignored', None
        except ProviderUnavailable: return 'retry', 'provider_unavailable'
        except Unmapped as exc: return 'dead', str(exc)[:60] or 'unmapped'
        except (ProviderRejected, BillingError, KeyError, TypeError, ValueError) as exc:
            return 'dead', ('invalid_' + type(exc).__name__.lower())[:60]

    # ------------------------------------------------------------- state machine

    def _account_for_customer(self, con, customer):
        row = con.execute('SELECT account_id FROM billing_customers WHERE provider_customer_id=?', (customer,)).fetchone()
        if not row: raise Unmapped('unknown_customer')   # never trust metadata in a payload
        return row['account_id']

    def _checkout_completed(self, obj, stamp):
        sid = obj.get('id')
        if not (isinstance(sid, str) and sid.startswith('cs_')): raise BillingError('invalid session')
        with self.store.connect() as con:
            mine = con.execute('SELECT account_id FROM billing_checkout_sessions WHERE provider_session_id=?', (sid,)).fetchone()
            if not mine: raise Unmapped('unknown_checkout_session')
            owner = con.execute('SELECT provider_customer_id FROM billing_customers WHERE account_id=?', (mine['account_id'],)).fetchone()
        session = self.api.retrieve_checkout_session(sid)
        if not owner or session.get('customer') != owner['provider_customer_id']: raise Unmapped('customer_mismatch')
        if session.get('status') != 'complete': return 'ignored', None
        with self.tx() as con:
            con.execute("UPDATE billing_checkout_sessions SET state='completed' WHERE provider_session_id=?", (sid,))
        return self._sync(session.get('subscription'), stamp)

    def _sync(self, sub_id, stamp, invoice_id=None):
        if not (isinstance(sub_id, str) and sub_id.startswith('sub_') and OBJECT_ID.fullmatch(sub_id)): return 'ignored', None
        snap = normalize_subscription(self.api.retrieve_subscription(sub_id))
        invoice_id = invoice_id or snap['latest_invoice']   # checkout and renewals list their latest invoice too
        invoice = self.api.retrieve_invoice(invoice_id) if isinstance(invoice_id, str) and invoice_id.startswith('in_') else None
        self.apply_snapshot(snap, stamp, invoice)
        return 'applied', None

    def _flags(self, con, sub_id):
        rows = con.execute('SELECT kind,count(*) AS n FROM billing_flags WHERE provider_subscription_id=? AND active=1 GROUP BY kind', (sub_id,)).fetchall()
        found = {r['kind']: r['n'] for r in rows}
        return int(found.get('refund', 0) > 0), int(found.get('dispute', 0) > 0)

    def apply_snapshot(self, snap, stamp, invoice=None):
        """Idempotent: recompute access from canonical facts; write the entitlement only if it changed."""
        now = self._now()
        with self.tx() as con:
            account = self._account_for_customer(con, snap['customer'])
            old = con.execute('SELECT * FROM billing_subscriptions WHERE provider_subscription_id=?', (snap['id'],)).fetchone()
            plan = self.plans.get(snap['price_id'])
            since = old['past_due_since'] if old else None
            if snap['provider_status'] == 'past_due': since = since or int(stamp or now)
            else: since = None
            refunded, disputed = self._flags(con, snap['id'])
            if old and snap['provider_status'] == 'active' and snap['current_period_end'] and old['current_period_end'] \
                    and snap['current_period_end'] > old['current_period_end']:
                refunded = 0   # a later paid period supersedes a refund of the earlier one
                con.execute("UPDATE billing_flags SET active=0,updated_epoch=? WHERE kind='refund' AND provider_subscription_id=?", (now, snap['id']))
            row = {'provider_status': snap['provider_status'], 'current_period_end': snap['current_period_end'],
                   'cancel_at_period_end': snap['cancel_at_period_end'], 'past_due_since': since,
                   'fully_refunded': refunded, 'disputed': disputed}
            access = derive_access(row, now, grace_hours=self.grace_hours)
            if plan is None: access = Access('expired', now, 'unknown_price')   # fail closed
            con.execute('''INSERT INTO billing_subscriptions(provider_subscription_id,account_id,provider_customer_id,plan_version,price_id,
                provider_status,current_period_start,current_period_end,cancel_at_period_end,past_due_since,fully_refunded,disputed,
                access_state,access_reason,synced_epoch,updated_epoch) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(provider_subscription_id) DO UPDATE SET plan_version=excluded.plan_version,price_id=excluded.price_id,
                provider_status=excluded.provider_status,current_period_start=excluded.current_period_start,
                current_period_end=excluded.current_period_end,cancel_at_period_end=excluded.cancel_at_period_end,
                past_due_since=excluded.past_due_since,fully_refunded=excluded.fully_refunded,disputed=excluded.disputed,
                access_state=excluded.access_state,access_reason=excluded.access_reason,synced_epoch=excluded.synced_epoch,
                updated_epoch=excluded.updated_epoch''',
                (snap['id'], account, snap['customer'], plan.version if plan else None, snap['price_id'], snap['provider_status'],
                 snap['current_period_start'], snap['current_period_end'], int(snap['cancel_at_period_end']), since, refunded, disputed,
                 access.status, access.reason, now, now))
            if invoice: self._store_invoice(con, account, snap['id'], invoice, now)
            changed = self._write_entitlement(con, account, plan or self.default_plan, access, snap['current_period_start'] or now, now)
            if changed or not old or old['access_state'] != access.status:
                self._audit(con, account, 'billing-worker', snap['id'], 'access.' + access.status, 'completed')
        return access

    def _write_entitlement(self, con, account, plan, access, period_start, now):
        valid = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(access.valid_until))
        limits = json.dumps(plan.limits(min(period_start, now)), sort_keys=True)
        current = con.execute("SELECT status,valid_until,limits_json,plan_version FROM entitlements WHERE account_id=? AND id='paid'", (account,)).fetchone()
        same = current and (current['status'], current['valid_until'], current['limits_json'], current['plan_version']) == (access.status, valid, limits, plan.version)
        if not same:
            con.execute('''INSERT INTO entitlements(account_id,id,plan_version,status,limits_json,valid_until) VALUES (?,'paid',?,?,?,?)
                ON CONFLICT(account_id,id) DO UPDATE SET plan_version=excluded.plan_version,status=excluded.status,
                limits_json=excluded.limits_json,valid_until=excluded.valid_until''', (account, plan.version, access.status, limits, valid))
        if access.status in ('active', 'grace'):
            # Exactly one eligible entitlement may exist; the trial allowance ends when paid access begins.
            con.execute("UPDATE entitlements SET status='expired',valid_until=? WHERE account_id=? AND id!='paid' AND status IN ('trial','active','grace')",
                        (time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now)), account))
        return not same

    def _store_invoice(self, con, account, sub_id, invoice, now):
        ident = invoice.get('id')
        if not (isinstance(ident, str) and ident.startswith('in_')): return
        if self._account_for_customer(con, invoice.get('customer')) != account: raise Unmapped('invoice_customer_mismatch')
        periods = invoice.get('period_start'), invoice.get('period_end')
        con.execute('''INSERT INTO billing_invoices VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(provider_invoice_id) DO UPDATE SET status=excluded.status,amount_due=excluded.amount_due,
            amount_paid=excluded.amount_paid,hosted_invoice_url=excluded.hosted_invoice_url,updated_epoch=excluded.updated_epoch''',
            (ident, account, sub_id, str(invoice.get('status')), int(invoice.get('amount_due') or 0), int(invoice.get('amount_paid') or 0),
             str(invoice.get('currency') or 'usd'), safe_invoice_url(invoice.get('hosted_invoice_url')),
             periods[0] if isinstance(periods[0], int) else None, periods[1] if isinstance(periods[1], int) else None,
             int(invoice.get('created') or now), now))

    def _refund(self, charge_id, stamp):
        if not (isinstance(charge_id, str) and charge_id.startswith('ch_')): raise BillingError('invalid charge')
        sub = self.api.subscription_for_charge(charge_id)
        if not sub: return 'ignored', None   # not a subscription charge
        charge = self.api.retrieve_charge(charge_id)
        full = bool(charge.get('refunded')) or (isinstance(charge.get('amount'), int) and charge.get('amount_refunded') == charge.get('amount') > 0)
        return self._flag('refund', charge_id, sub, full, stamp)

    def _dispute(self, dispute_id, stamp):
        if not (isinstance(dispute_id, str) and dispute_id.startswith('dp_')): raise BillingError('invalid dispute')
        dispute = self.api.retrieve_dispute(dispute_id)
        sub = self.api.subscription_for_charge(dispute.get('charge'))
        if not sub: return 'ignored', None
        open_states = {'warning_needs_response', 'warning_under_review', 'needs_response', 'under_review'}
        active = dispute.get('status') in open_states
        lost = dispute.get('status') == 'lost'
        outcome = self._flag('dispute', dispute_id, sub, active, stamp)
        if lost: self._flag('refund', dispute_id, sub, True, stamp)   # a lost dispute removes the payment like a refund
        return outcome

    def _flag(self, kind, object_id, sub_id, active, stamp):
        with self.tx() as con:
            owner = con.execute('SELECT account_id FROM billing_subscriptions WHERE provider_subscription_id=?', (sub_id,)).fetchone()
            if not owner: raise Unmapped('unknown_subscription')
            con.execute('''INSERT INTO billing_flags VALUES (?,?,?,?,?,?) ON CONFLICT(kind,object_id) DO UPDATE SET active=excluded.active,
                updated_epoch=excluded.updated_epoch''', (kind, object_id, owner['account_id'], sub_id, int(bool(active)), self._now()))
        return self._sync(sub_id, stamp)

    # ------------------------------------------------------------- open access

    def sync_open_access(self, open_on: bool):
        """Grant or end the free-access entitlement for every active account (needs no Stripe configuration).

        Free access is one rolling `open` entitlement carrying the plan's limits with the allowance resetting
        each calendar month. It never overrides paid access, never overrides a dispute hold, supersedes an
        invitation-trial row while it lasts, expires the moment it is switched off, and lapses on its own
        after three days if nothing refreshes it (fail closed).
        """
        report = {'granted': 0, 'refreshed': 0, 'ended': 0}
        if open_on and self.default_plan is None: raise BillingNotConfigured('no plan configured')
        now = self._now()
        t = time.gmtime(now)
        month_start = calendar.timegm((t.tm_year, t.tm_mon, 1, 0, 0, 0))
        stamp = lambda e: time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(e))
        with self.tx() as con:
            accounts = [r['id'] for r in con.execute("SELECT id FROM accounts WHERE status='active'").fetchall()]
            for account in accounts:
                paid = con.execute("SELECT status,valid_until FROM entitlements WHERE account_id=? AND id='paid'", (account,)).fetchone()
                held = paid is not None and paid['status'] == 'suspended'
                paid_ok = paid is not None and paid['status'] in ('active', 'grace') and con.execute(
                    'SELECT julianday(?)>julianday(?,?)', (paid['valid_until'], now, 'unixepoch')).fetchone()[0]
                row = con.execute("SELECT status,valid_until,limits_json FROM entitlements WHERE account_id=? AND id=?", (account, OPEN_ID)).fetchone()
                if open_on and not paid_ok and not held:
                    limits = json.dumps(self.default_plan.limits(month_start), sort_keys=True)
                    if row is None:
                        con.execute("INSERT INTO entitlements(account_id,id,plan_version,status,limits_json,valid_until) VALUES (?,?,?,'active',?,?)",
                                    (account, OPEN_ID, self.default_plan.version, limits, stamp(now + OPEN_TTL)))
                        con.execute("UPDATE entitlements SET status='expired',valid_until=? WHERE account_id=? AND id NOT IN (?, 'paid') AND status IN ('trial','active','grace')",
                                    (stamp(now), account, OPEN_ID))
                        self._audit(con, account, 'billing-worker', OPEN_ID, 'open_access.granted', 'completed')
                        report['granted'] += 1
                    else:
                        remaining = con.execute('SELECT (julianday(?)-julianday(?,?))*86400', (row['valid_until'], now, 'unixepoch')).fetchone()[0]
                        if row['status'] != 'active' or row['limits_json'] != limits or remaining < OPEN_TTL / 2:
                            was_active = row['status'] == 'active'
                            con.execute("UPDATE entitlements SET status='active',limits_json=?,valid_until=?,plan_version=? WHERE account_id=? AND id=?",
                                        (limits, stamp(now + OPEN_TTL), self.default_plan.version, account, OPEN_ID))
                            con.execute("UPDATE entitlements SET status='expired' WHERE account_id=? AND id NOT IN (?, 'paid') AND status IN ('trial','active','grace')",
                                        (account, OPEN_ID))
                            if not was_active: self._audit(con, account, 'billing-worker', OPEN_ID, 'open_access.granted', 'completed')
                            report['refreshed'] += 1
                elif row is not None and row['status'] in ('active', 'grace'):
                    con.execute("UPDATE entitlements SET status='expired',valid_until=? WHERE account_id=? AND id=?", (stamp(now), account, OPEN_ID))
                    self._audit(con, account, 'billing-worker', OPEN_ID, 'open_access.ended', 'completed')
                    report['ended'] += 1
        return report

    # --------------------------------------------------- reconcile / sweep / views

    def sweep(self):
        """Clock-driven pass using stored facts only: grace and period ends need no webhook to take effect."""
        now, changed = self._now(), 0
        with self.tx() as con:
            for sub in con.execute("SELECT * FROM billing_subscriptions WHERE access_state IN ('active','grace')").fetchall():
                access = derive_access(dict(sub), now, grace_hours=self.grace_hours)
                if access.status != sub['access_state']:
                    con.execute('UPDATE billing_subscriptions SET access_state=?,access_reason=?,updated_epoch=? WHERE provider_subscription_id=?',
                                (access.status, access.reason, now, sub['provider_subscription_id']))
                    plan = self.plans.get(sub['price_id']) or self.default_plan
                    self._write_entitlement(con, sub['account_id'], plan, access, sub['current_period_start'] or now, now)
                    self._audit(con, sub['account_id'], 'billing-worker', sub['provider_subscription_id'], 'access.' + access.status, 'completed')
                    changed += 1
        return changed

    def reconcile(self):
        """Compare stored access with the provider's canonical state; correct drift and report it."""
        drift, errors = [], 0
        with self.store.connect() as con:
            subs = [(r['provider_subscription_id'], r['access_state']) for r in con.execute('SELECT provider_subscription_id,access_state FROM billing_subscriptions').fetchall()]
        for sub_id, before in subs:
            try:
                snap = normalize_subscription(self.api.retrieve_subscription(sub_id))
                access = self.apply_snapshot(snap, self._now())
                if access.status != before: drift.append({'subscription': sub_id[:12], 'was': before, 'now': access.status})
            except (ProviderUnavailable, ProviderRejected, BillingError):
                errors += 1
        with self.store.connect() as con:
            inbox = dict(con.execute('SELECT status,count(*) FROM billing_inbox GROUP BY status').fetchall())
        return {'checked': len(subs), 'drift': drift, 'provider_errors': errors, 'inbox': inbox,
                'dead_letters': inbox.get('dead', 0)}

    def overview(self, principal: Principal, usage=None, mode='invite_only'):
        account = principal.account_id
        with self.store.connect() as con:
            self._account(con, principal)
            sub = con.execute('SELECT * FROM billing_subscriptions WHERE account_id=? ORDER BY updated_epoch DESC LIMIT 1', (account,)).fetchone()
            invoices = con.execute('SELECT * FROM billing_invoices WHERE account_id=? ORDER BY created_epoch DESC LIMIT 12', (account,)).fetchall()
            has_customer = con.execute('SELECT 1 FROM billing_customers WHERE account_id=?', (account,)).fetchone() is not None
            dead = con.execute("SELECT count(*) FROM billing_inbox WHERE status='dead'").fetchone()[0]
        plan = self.default_plan
        state = dict(sub) if sub else None
        status = state['access_state'] if state else 'none'
        view = {'plan': {'name': 'Builder', 'monthly_price_usd': plan.monthly_price_usd if plan else None,
                         'included_usd': f'{plan.included_microusd / 1_000_000:.2f}' if plan else None},
                'status': status, 'reason': state['access_reason'] if state else None,
                'period_end': state['current_period_end'] if state else None,
                'cancel_at_period_end': bool(state and state['cancel_at_period_end']),
                'grace_ends': (state['past_due_since'] + self.grace_hours * 3600) if state and state['access_state'] == 'grace' and state['past_due_since'] else None,
                'new_tasks_allowed': bool(usage['admission_eligible']) if usage else status in ('active', 'grace'),
                'access_mode': mode,
                'can_subscribe': status in ('none', 'expired') and plan is not None,
                'can_manage': has_customer, 'usage': usage,
                'invoices': [{'id': i['provider_invoice_id'], 'status': i['status'], 'amount_paid': i['amount_paid'], 'currency': i['currency'],
                              'url': i['hosted_invoice_url'], 'created': i['created_epoch']} for i in invoices],
                'dead_letters': dead}
        return view
