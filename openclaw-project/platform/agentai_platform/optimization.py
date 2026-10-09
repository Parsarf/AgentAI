"""Optional TypeSafe (Jev) optimization gates and billing (Phase 12; DISABLED).

Four independent layers must all be open before a call is even reserved:
server kill switch (read back every call, fail closed), per-account activation
state, recorded data-handling approval, and a reviewed transport with a
TypeSafe account reference. Every call is reserved against the task's Phase 5
allocation *before* it is sent and recorded as a provider receipt after;
an uncertain call keeps its hold until reconciled. TypeSafe is a separate
provider: Anthropic/ChatGPT caps do not cover it, so it is never inferred.
Pricing is pinned in ``plans/product/phase-12-typesafe-pin.json``.
"""
from __future__ import annotations
import hashlib
import time
from .budget import BudgetLedger
from .lifecycle.coordinator import Coordinator, identifier
from .lifecycle.types import Conflict
from .security import NotFound, Principal

MODEL = 'jev-1.13.0'
PRICE_VERSION = 'typesafe-jev-1-13-0-2026-10-09'
MICROUSD_PER_1000_INPUT_TOKENS = 42        # $0.042 per million input tokens; output is free
MAX_REQUEST_TOKENS = 64000                 # documented context budget for state + questions
TRACKS = {'browser', 'research'}


class OptimizationDenied(Exception):
    """Carries a machine-readable reason; the caller falls back to the baseline route."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def cost_microusd(input_tokens: int) -> int:
    if type(input_tokens) is not int or input_tokens < 0:
        raise ValueError('invalid token count')
    return -(-input_tokens * MICROUSD_PER_1000_INPUT_TOKENS // 1000)


def upper_bound_microusd(request_json: str) -> int:
    """Conservative per-call bound: assumes one token per UTF-8 byte, capped at the documented
    context size. The one-token-per-byte assumption is NOT proven; it must be validated against
    observed usage before activation (Phase 16)."""
    return max(1, cost_microusd(min(len(request_json.encode()), MAX_REQUEST_TOKENS)))


class OptimizationGate:
    def __init__(self, store, ledger: BudgetLedger, *, kill_switches=lambda: {}, clock=time.time):
        self.store, self.ledger, self.clock = store, ledger, clock
        self.kill_switches = kill_switches
        self.coordinator = Coordinator(store, clock=clock)

    # ---------- host/operator only ----------

    def record_activation(self, account_id: str, track: str, *, enabled: bool, data_handling: bool = False,
                          transport_review: bool = False, account_ref: str | None = None) -> None:
        identifier(account_id)
        if track not in TRACKS:
            raise ValueError('unknown track')
        now = int(self.clock())
        with self.coordinator.transaction() as con:
            if not con.execute('SELECT 1 FROM accounts WHERE id=?', (account_id,)).fetchone():
                raise NotFound('unavailable')
            con.execute('''INSERT INTO optimization_activations(account_id,track,state,data_handling_approved_epoch,
                transport_reviewed_epoch,typesafe_account_ref,updated_epoch) VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(account_id,track) DO UPDATE SET state=excluded.state,
                data_handling_approved_epoch=excluded.data_handling_approved_epoch,
                transport_reviewed_epoch=excluded.transport_reviewed_epoch,
                typesafe_account_ref=excluded.typesafe_account_ref,updated_epoch=excluded.updated_epoch''',
                        (account_id, track, 'enabled' if enabled else 'disabled', now if data_handling else None,
                         now if transport_review else None, account_ref, now))
            self.coordinator._audit(con, account_id, 'operator', track, 'optimization.activation', 'completed')

    # ---------- admission ----------

    def check(self, principal: Principal, track: str) -> None:
        """Raise OptimizationDenied unless every layer is open. Fails closed on any error."""
        if track not in TRACKS:
            raise OptimizationDenied('unknown_track')
        try:
            switches = self.kill_switches()
        except Exception:
            raise OptimizationDenied('kill_switch_unreadable') from None
        if switches.get(track) is not True:
            raise OptimizationDenied('server_disabled')
        with self.store.connect() as con:
            self.store._authorize(con, principal)
            row = con.execute('SELECT * FROM optimization_activations WHERE account_id=? AND track=?',
                              (principal.account_id, track)).fetchone()
        if not row or row['state'] != 'enabled':
            raise OptimizationDenied('account_not_enabled')
        if not row['data_handling_approved_epoch']:
            raise OptimizationDenied('data_handling_not_approved')
        if not row['transport_reviewed_epoch']:
            raise OptimizationDenied('transport_not_reviewed')
        if not row['typesafe_account_ref']:
            raise OptimizationDenied('no_typesafe_account')

    def reserve_call(self, principal: Principal, task_id: str, track: str, call_id: str, request_json: str) -> int:
        identifier(call_id)
        self.check(principal, track)
        bound = upper_bound_microusd(request_json)
        with self.coordinator.transaction() as con:
            self.store._authorize(con, principal)
            existing = con.execute('SELECT bound_microusd FROM optimization_calls WHERE account_id=? AND call_id=?',
                                   (principal.account_id, call_id)).fetchone()
            if existing:
                return existing['bound_microusd']
            reservation = con.execute('''SELECT amount_microusd,state FROM task_reservations WHERE account_id=?
                AND task_id=?''', (principal.account_id, task_id)).fetchone()
            if not reservation or reservation['state'] != 'active':
                raise OptimizationDenied('task_allocation_unavailable')
            spent = con.execute('SELECT coalesce(sum(amount_microusd),0) FROM provider_receipts WHERE account_id=? '
                                'AND task_id=?', (principal.account_id, task_id)).fetchone()[0]
            held = con.execute("SELECT coalesce(sum(bound_microusd),0) FROM optimization_calls WHERE account_id=? "
                               "AND task_id=? AND state IN ('reserved','uncertain')",
                               (principal.account_id, task_id)).fetchone()[0]
            if spent + held + bound > reservation['amount_microusd']:
                raise OptimizationDenied('task_budget_exhausted')
            con.execute('INSERT INTO optimization_calls VALUES (?,?,?,?,?,?,NULL,?)',
                        (principal.account_id, task_id, call_id, track, bound, 'reserved', int(self.clock())))
            return bound

    # ---------- settlement ----------

    def record_call(self, account_id: str, task_id: str, call_id: str, input_tokens: int) -> int:
        """Host adapter path: turn a completed call into a Phase 5 provider receipt.
        The receipt is written first with a deterministic time and request id, so a crash
        between the two steps is repaired by calling this again (identical receipts are no-ops)."""
        amount = cost_microusd(input_tokens)
        with self.store.connect() as con:
            row = con.execute('SELECT * FROM optimization_calls WHERE account_id=? AND call_id=? AND task_id=?',
                              (account_id, call_id, task_id)).fetchone()
        if not row or row['state'] not in {'reserved', 'uncertain'}:
            raise Conflict('call is not open')
        self.ledger.receipt(account=account_id, task=task_id, provider='typesafe', request=call_id,
                            amount_microusd=amount, observed_epoch=row['created_epoch'], price_version=PRICE_VERSION,
                            payload_hash=hashlib.sha256(call_id.encode()).hexdigest())
        with self.coordinator.transaction() as con:
            con.execute("UPDATE optimization_calls SET state=?,input_tokens=? WHERE account_id=? AND call_id=?",
                        ('recorded' if row['state'] == 'reserved' else 'reconciled', input_tokens, account_id, call_id))
        return amount

    def mark_uncertain(self, account_id: str, call_id: str) -> None:
        """Timeout/outage after sending: keep the hold; billing is unknown until reconciled."""
        with self.coordinator.transaction() as con:
            cur = con.execute("UPDATE optimization_calls SET state='uncertain' WHERE account_id=? AND call_id=? "
                              "AND state='reserved'", (account_id, call_id))
            if cur.rowcount != 1:
                raise Conflict('call is not reserved')

    def release_unsent(self, account_id: str, call_id: str) -> None:
        """The request provably never left (e.g. rejected locally): drop the reservation."""
        with self.coordinator.transaction() as con:
            cur = con.execute("DELETE FROM optimization_calls WHERE account_id=? AND call_id=? AND state='reserved'",
                              (account_id, call_id))
            if cur.rowcount != 1:
                raise Conflict('call is not reserved')

    def unreconciled(self, account_id: str, task_id: str) -> int:
        with self.store.connect() as con:
            return con.execute("SELECT count(*) FROM optimization_calls WHERE account_id=? AND task_id=? "
                               "AND state IN ('reserved','uncertain')", (account_id, task_id)).fetchone()[0]
