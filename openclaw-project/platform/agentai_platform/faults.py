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
import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field

from .browse.job_states import END_CODES, RELEASED_REASON      # a job its request no longer needed is not a failure
from .faults_registry import REASONS

log = logging.getLogger(__name__)

KINDS = ('retry_later', 'needs_customer', 'needs_owner', 'refused', 'not_found', 'conflict', 'invalid', 'limit', 'unknown_outcome', 'internal')
ACTORS = ('assistant', 'customer', 'owner', 'nobody')
EFFECTS = ('nothing_changed', 'partly_done', 'unknown')
# Whether the same thing may be tried again, by kind and nothing else: `retry_later` after a pause, `unknown_outcome` only after reading back what happened, the rest never.
RETRY = {'retry_later': 'later', 'unknown_outcome': 'read_back'}

# What `detail` may hold. A value is an int, a float, a bool, or ONE token (letters, digits, . _ : -): no spaces, so no sentence; no / @ ? or %, so no address.
DETAIL_KEYS = ('status', 'code', 'route', 'exception', 'where', 'state', 'tool', 'call', 'attempt', 'seconds', 'waited_seconds', 'steps', 'kind', 'provider_error', 'runtime_reason', 'job')
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
_EXCEPTION = re.compile(r'\(([A-Za-z_][A-Za-z0-9_]{2,40})\)\s*$')


def of_browser_job(state, reason='', code='', *, exception=None, where=None) -> Fault | None:
    """The fault for a browser job that ended in `state`. `code` is the reason the browser gave where the ending was decided (browse/loop.py, browse/service.py): a
    registered code is used as it is, with the exception's type and place as facts when it was a crash. The job's own sentence is never kept: it can quote the page.

    A job recorded before the browser gave codes has none. For those, and only those, the state decides, and two things are still read from the old sentence: the
    exception type it carried in brackets and the human-check wording."""
    state, reason, code = str(state or ''), str(reason or ''), str(code or '')
    if state in ('', 'done', 'released') or reason == RELEASED_REASON:
        return None
    detail = {'state': state if TOKEN.fullmatch(state) else 'other', 'exception': exception, 'where': where}
    if code in REASONS and code.startswith('browser.'):
        return Fault(code, detail)
    found = _EXCEPTION.search(reason)
    if found:
        detail['exception'] = found.group(1)
    if 'verify you are human' in reason:
        return Fault('browser.human_check', detail)
    return Fault(END_CODES.get(state, 'browser.stopped'), detail)


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
        found = of_browser_job(last.get('state'), last.get('reason'), last.get('code'), exception=last.get('exception'), where=last.get('where'))
        if found is not None:
            return found
    if not reply:
        return Fault('task.no_reply')
    return None


# -- one tool call (Part 3) -------------------------------------------------------------------------------------------------------------------------------------
# A tool answers `(text, problem[, picture])`. `problem` is False for a call that did what was asked, and a Fault for one that did not: the tool that refused or failed says
# why, there, with a registered reason. The tool relay records it with the call. A bare True (a tool that has not said why) is kept working and counted as `tool.failed`,
# which reaches the owner: the count of those is the list of tools still to be moved.
#
# The assistant is told `isError` only for a fault that is an error. An expected stop (approval needed, stopped with the task, a limit, a switch that is off) is a normal
# reply that says what happens next: the runtime and the model treat an error as something to retry, and 26 approval requests were retried that way in 30 days.
STEP = "json_extract(detail_json,'$.tool') IS NOT NULL"       # SQL: this fault row is about ONE tool call (a step), not about how a request ended


def tool_name(name) -> str:
    """The tool's name as a fact that may be kept. A connected service's own tool names are the customer's: every one of them is recorded as the same word."""
    name = str(name or '').removeprefix('lumina__')
    if re.match(r'lumina_mcp_[a-f0-9]{8}', name):                 # also when the name was cut short for display
        return 'lumina_mcp_connected'
    return name if TOKEN.fullmatch(name) else 'other'


# A tool reached through the runtime's `tool_call` wrapper is given an id of its own by the runtime, built around the id of the wrapper call the model made:
# "tool_search_code:<the model's call id>:<tool name>:<n>". The session history, and so the timeline, knows only the model's call id. Seen on the installed runtime
# (2026.9.6) and held there by tests/e2e (test_a_tool_call_lumina_refuses_shows_its_reason_on_the_step_whichever_way_it_was_called).
_WRAPPED_CALL = re.compile(r'tool_search_code:(.+):[A-Za-z0-9_.-]+:\d+')


def call_mark(call_id) -> str:
    """A short mark for one tool call, from the runtime's own id for it. The relay records it with the fault and the driver finds the fault by it when it shows the step;
    the id itself is not kept (it is the model provider's). Both ways a tool is reached give the same mark: its plain name, and the runtime's wrapper."""
    call_id = str(call_id or '')
    wrapped = _WRAPPED_CALL.fullmatch(call_id)
    if wrapped:
        call_id = wrapped.group(1)
    return hashlib.sha256(call_id.encode()).hexdigest()[:20] if call_id else ''


def of_tool_reply(problem, tool, call_id=None) -> Fault | None:
    """What a tool put in the second place of its answer -> the fault to record for the call (with the tool and the call's mark), or None for a call that worked."""
    if not problem:
        return None
    fault = problem if isinstance(problem, Fault) else Fault('tool.failed')
    return Fault(fault.reason, {**fault.detail, 'tool': tool_name(tool), 'call': call_mark(call_id) or None}, fault.effect, fault.retry_at)


def is_error(problem) -> bool:
    """Is the assistant told this call failed? Only for a fault that is an error; an expected stop is a normal reply."""
    if isinstance(problem, Fault):
        return not problem.expected
    return bool(problem)


def of_connector(error) -> Fault:
    """A ConnectorFault (connector_kit) as a fault: its six kinds are registered one to one."""
    return Fault('connector.' + str(getattr(error, 'kind', 'invalid')), retry_at=int(error.retry_at) if getattr(error, 'retry_at', None) else None)


def for_call(con, account_id, request_id, call_id) -> str | None:
    """The reason the relay recorded for this call of this request, or None. Read by the driver when it shows the step."""
    mark = call_mark(call_id)
    if not mark:
        return None
    row = con.execute(f"SELECT reason FROM faults WHERE account_id=? AND request_id=? AND {STEP} AND json_extract(detail_json,'$.call')=? ORDER BY created_epoch DESC LIMIT 1",
                      (account_id, request_id, mark)).fetchone()
    return row[0] if row else None


# The runtime's own tools (web_fetch, web_search, exec and the rest) answer in the runtime's words, and those words are all Lumina gets: the call never passes the relay. This
# is the second and last table that matches text (rule 1), pinned to the installed runtime by tests/test_tool_faults.py. A status number in the message is a fact and is read
# first. Whatever matches nothing is `runtime.tool_failed`: a command that exited with an error is the assistant's ordinary work, not something to alert on.
_FETCH_STATUS = re.compile(r'\b(?:web )?fetch failed \((\d{3})\)', re.I)
RUNTIME_TOOL_WORDS = (
    ('runtime.tool_not_offered', re.compile(r'^tool [\w.:-]+ not found\b|^unknown tool id\b', re.I)),
    ('runtime.skipped_for_message', re.compile(r'^skipped to process an incoming message', re.I)),
    ('site.unreadable', re.compile(r'^web fetch extraction failed', re.I)),
    ('runtime.unreachable', re.compile(r'^fetch failed\b|\bUND_ERR_\w+|\bECONN\w+|\bETIMEDOUT\b|\bENOTFOUND\b')),
)


def of_site_status(status) -> str:
    status = int(status or 0)
    if status in (401, 402, 403, 407, 451):
        return 'site.refused'
    if status in (404, 410):
        return 'site.not_found'
    if status in (408, 425, 429):
        return 'site.busy'
    return 'site.error' if status >= 500 else 'site.refused'


def of_runtime_tool(tool, text) -> Fault:
    """The fault for a failed call of one of the runtime's own tools, from what the runtime said. Only the reason, the tool's name and a status number are kept."""
    text = str(text or '').strip()[:600]
    detail = {'tool': tool_name(tool), 'kind': 'runtime_text'}
    found = _FETCH_STATUS.search(text)
    if found:
        return Fault(of_site_status(found.group(1)), {**detail, 'status': int(found.group(1))})
    for reason, pattern in RUNTIME_TOOL_WORDS:
        if pattern.search(text):
            return Fault(reason, detail)
    return Fault('runtime.tool_failed', detail)
