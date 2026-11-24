"""One way to say why something did not finish (reliability plan, Part 1). Generalised from the connector contract (connector_kit.py), which keeps its six kinds.

A FAULT is made where a failure is caught and is never rebuilt from text later. It carries:

* `reason`  a code registered in faults_registry.py (`model.rate_limited`, `cell.stopped_under_task`). The registry gives its kind, who must act, the sentence the
            customer reads and the one the assistant reads. A reason that is not registered cannot be made.
* `kind`    one of KINDS: the six of the connector contract plus needs_owner, limit, unknown_outcome and internal. The kind alone decides whether it may be tried again.
* `effect`  what was changed: nothing_changed, partly_done or unknown.
* `detail`  FACTS ONLY, for the owner: a status number, an exception type, a state name, a count, a duration. Never page text, message text, an address, a name or the
            runtime's own wording. `facts()` enforces the shape (a short list of keys; a value is a number or one token without spaces), so a sentence cannot get in.

`record` writes one row to `faults` and never raises: recording why something failed must not be a second way for it to fail. What the customer is shown is still
decided by the code that shows it; this module is the one place those sentences come from as each feature moves onto it (Parts 2 and 3).

Stdlib only.
"""
from __future__ import annotations
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field

from .browse.job_states import RELEASED_REASON      # a job its request no longer needed: not a failure
from .faults_registry import REASONS

log = logging.getLogger(__name__)

KINDS = ('retry_later', 'needs_customer', 'needs_owner', 'refused', 'not_found', 'conflict', 'invalid', 'limit', 'unknown_outcome', 'internal')
ACTORS = ('assistant', 'customer', 'owner', 'nobody')
EFFECTS = ('nothing_changed', 'partly_done', 'unknown')
# Whether the same thing may be tried again, by kind and nothing else: `retry_later` after a pause, `unknown_outcome` only after reading back what happened, the rest never.
RETRY = {'retry_later': 'later', 'unknown_outcome': 'read_back'}

# What `detail` may hold. A value is an int, a float, a bool, or ONE token (letters, digits, . _ : -): no spaces, so no sentence; no / @ ? or %, so no address.
DETAIL_KEYS = ('status', 'code', 'route', 'exception', 'state', 'tool', 'attempt', 'seconds', 'waited_seconds', 'steps', 'kind', 'provider_error', 'runtime_reason', 'job')
TOKEN = re.compile(r'[A-Za-z0-9_.:-]{1,60}')


def facts(detail) -> dict:
    """The part of `detail` that is allowed to be kept. Anything else is dropped without a word: a key that is not listed, or a value that is not a number or one token."""
    out = {}
    for key, value in (detail or {}).items():
        if key not in DETAIL_KEYS or value is None:
            continue
        if isinstance(value, bool) or isinstance(value, int):
            out[key] = value
        elif isinstance(value, float) and value == value and abs(value) < 1e12:
            out[key] = round(value, 3)
        elif isinstance(value, str) and TOKEN.fullmatch(value):
            out[key] = value
    return out


@dataclass(frozen=True)
class Fault:
    reason: str
    detail: dict = field(default_factory=dict)
    effect: str | None = None           # None = the registry's default for this reason
    retry_at: int | None = None         # an epoch second, when whoever refused said when

    def __post_init__(self):
        if self.reason not in REASONS:
            raise ValueError('unknown fault reason: ' + str(self.reason)[:80])
        if self.effect is not None and self.effect not in EFFECTS:
            raise ValueError('unknown fault effect')
        object.__setattr__(self, 'detail', facts(self.detail))

    @property
    def spec(self):
        return REASONS[self.reason]

    @property
    def kind(self) -> str:
        return self.spec.kind

    @property
    def actor(self) -> str:
        return self.spec.actor

    @property
    def expected(self) -> bool:
        return self.spec.expected

    @property
    def alert(self) -> bool:
        return self.spec.alert

    @property
    def what_changed(self) -> str:
        return self.effect or self.spec.effect

    @property
    def retry(self) -> str:
        """never | later | read_back."""
        return RETRY.get(self.kind, 'never')

    @property
    def feature(self) -> str:
        return self.reason.split('.', 1)[0]

    @property
    def customer_words(self) -> str:
        return self.spec.customer

    @property
    def assistant_words(self) -> str:
        return self.spec.assistant or self.spec.customer


class FaultError(Exception):
    """An exception that already knows why: the base for errors that should reach a boundary as a fault instead of as text."""
    def __init__(self, fault: Fault):
        super().__init__(fault.reason)
        self.fault = fault


def insert(con, account_id, fault: Fault, *, request_id=None, now=None) -> str:
    """Inside the caller's transaction. -> the row id."""
    row = uuid.uuid4().hex
    con.execute('INSERT INTO faults(account_id,id,request_id,feature,kind,reason,actor,effect,expected,retry_after_epoch,detail_json,created_epoch) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (account_id, row, request_id, fault.feature, fault.kind, fault.reason, fault.actor, fault.what_changed, 1 if fault.expected else 0, fault.retry_at,
                 json.dumps(fault.detail, sort_keys=True), int(now if now is not None else time.time())))
    return row


def record(store, account_id, fault: Fault, *, request_id=None, now=None):
    """Write the fault in a transaction of its own. Never raises (-> the row id, or None when it could not be written): a failure to note a failure changes nothing else."""
    try:
        with store.connect() as con:
            return insert(con, account_id, fault, request_id=request_id, now=now)
    except Exception:
        log.error('fault not recorded reason=%s request=%s', fault.reason, request_id)
        return None


# -- from what Lumina already knows today -----------------------------------------------------------------------------------------------------------------------
def of_model_status(status, code='', *, own=False) -> Fault | None:
    """A model call that ended with this HTTP status, as the relay saw it (`code` is the relay's own word when the relay itself refused). None for a call that worked.
    `own` says whose key it was: a refused key is the customer's to fix when it is theirs, and the owner's when it is Lumina's."""
    status, code = int(status or 0), str(code or '')
    detail = {'status': status, 'code': code, 'route': 'own' if own else 'lumina'}
    if 200 <= status < 300:
        return None
    if code in ('budget_exhausted',) or status == 402:
        return Fault('model.allowance_exhausted' if not own else 'model.own_key_refused', detail)
    if code in ('admission_mismatch', 'not_enabled'):
        return Fault('model.selection_changed', detail)
    if code in ('rate_limited', 'too_many_at_once'):
        return Fault('model.too_many_calls', detail)
    if code in ('upstream_unreachable', 'redirect_refused', 'endpoint_not_public', 'model_settings_unavailable', 'admission_unavailable'):
        return Fault('model.unreachable', detail)
    if code in ('model_unavailable', 'no_key') or status == 404:
        return Fault('model.not_offered', detail)
    if status in (401, 403):
        return Fault('model.own_key_refused' if own else 'model.lumina_key_refused', detail)
    if status in (408, 429, 529) or status == 503:
        return Fault('model.rate_limited', detail)
    if status >= 500:
        return Fault('model.provider_error', detail)
    if status in (400, 413, 422):
        return Fault('model.bad_request', detail)
    return Fault('internal.unclassified', detail)


# The runtime's own words for a run that ended in an error, as `gateway.wait` keeps them today. This is the ONE place text is matched, and only until Part 2 replaces it with
# the status the relay recorded and the runtime's structured detail. The lists are chat_driver.failure_message's, so the reason and the sentence shown agree.
_RUNTIME_WORDS = (
    ('model.allowance_exhausted', ('budget_exhausted', 'allowance is exhausted', 'insufficient credits', 'billing error', 'credit balance')),
    ('model.rate_limited', ('rate-limit', 'rate limit', 'ratelimit', 'too many requests', 'overloaded')),
    ('run.timeout', ('timeout',)),
    ('model.not_offered', ('model is unavailable', 'model_unavailable')),
    ('model.selection_changed', ('admission_mismatch', 'does not match an admitted')),
)
_BUSY_STATUS = re.compile(r'(?<!\w)(?<!\d\.)(429|529)(?!\w)(?!\.\d)')


def of_runtime_error(error) -> Fault:
    """The fault for a run the runtime ended with this error text. The text itself is never kept: only which reason it matched."""
    text = str(error or '').lower()
    for reason, words in _RUNTIME_WORDS:
        if any(w in text for w in words) or (reason == 'model.rate_limited' and _BUSY_STATUS.search(text)):
            return Fault(reason, {'kind': 'runtime_text'})
    return Fault('run.unclassified', {'kind': 'runtime_text'})


# How a browser job ended (browse/job_states.py) -> the reason. `done` and a job the assistant simply went on without are not faults.
_BROWSER_STATES = {
    'error': 'browser.failed', 'stopped': 'browser.stopped', 'blocked': 'browser.site_not_allowed', 'stuck': 'browser.stuck', 'deadline': 'browser.deadline',
    'max_steps': 'browser.max_steps', 'interrupted': 'browser.interrupted', 'budget': 'browser.spending_limit', 'handoff': 'browser.needs_customer',
    'cancelled': 'browser.stopped_with_task',
}
_EXCEPTION = re.compile(r'\(([A-Za-z_][A-Za-z0-9_]{2,40})\)\s*$')


def of_browser_job(state, reason='') -> Fault | None:
    """The fault for a browser job that ended in `state`. From the job's own reason only the exception type in brackets is kept ("the browser run failed (TimeoutError)"),
    never the reason itself: it can quote the page."""
    state, reason = str(state or ''), str(reason or '')
    if state in ('', 'done', 'released') or reason == RELEASED_REASON:
        return None
    detail = {'state': state if TOKEN.fullmatch(state) else 'other'}
    found = _EXCEPTION.search(reason)
    if found:
        detail['exception'] = found.group(1)
    if 'verify you are human' in reason:
        return Fault('browser.human_check', detail)
    return Fault(_BROWSER_STATES.get(state, 'browser.stopped'), detail)


GOAL_HELD = ('paused', 'budget_limited', 'usage_limited')


def of_finished_run(outcome, *, jobs=(), goal=None, reply=True, continuing=False) -> Fault | None:
    """The fault behind a run that ended by itself but not cleanly (outcome partial, blocked or failed), from the same facts and in the same order as outcome.judge:
    the runtime's goal, then the last browser job, then a missing reply. None when the run simply completed, or is about to carry on with its goal."""
    if outcome not in ('partial', 'blocked', 'failed'):
        return None
    status = (goal or {}).get('status')
    if status == 'blocked':
        return Fault('task.goal_blocked')
    if status in GOAL_HELD or (status == 'active' and not continuing):
        return Fault('task.goal_held', {'state': status})
    if status == 'active':
        return None
    if jobs:
        last = jobs[-1]
        found = of_browser_job(last.get('state'), last.get('reason'))
        if found is not None:
            return found
    if not reply:
        return Fault('task.no_reply')
    return None
