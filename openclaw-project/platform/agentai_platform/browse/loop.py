"""The browse loop: observe -> decide (ladder) -> policy -> fresh-target act -> record. No model can widen what is allowed."""
from __future__ import annotations
from dataclasses import dataclass, field
import re
import time

from . import candidates as cand
from .untrusted import neutralize
from .ladder import Decision, Ladder, Refused

DEFAULT_DENY = re.compile(r'(^|\.)(paypal|venmo|cash\.app|chase|bankofamerica|wellsfargo|citi|capitalone|robinhood|coinbase|binance|fidelity|schwab|vanguard)\.', re.I)


@dataclass
class Policy:
    """Code-side rules. `read_only` is the first release: browse, compare and fill a cart, but stop at any payment step."""
    read_only: bool = True
    deny_domains: re.Pattern = DEFAULT_DENY

    def url_ok(self, url: str) -> bool:
        m = re.match(r'^https?://([^/:]+)', url or '', re.I)
        return bool(m) and not self.deny_domains.search(m.group(1) + '.')

    def gate(self, url, snapshot_text, page_text, chosen) -> str:
        """'ok' | 'handoff' (payment/consequential step: the user takes over) -- evaluated BEFORE any click."""
        if cand.page_is_payment(url, snapshot_text, page_text):
            return 'handoff'
        if chosen and chosen.get('label') and cand.SENSITIVE.search(chosen['label']):
            return 'handoff'
        return 'ok'


@dataclass
class Result:
    status: str                    # done | handoff | stopped | blocked | max_steps | deadline | cancelled | stuck | budget | error
    reason: str = ''
    answer: str | None = None
    url: str = ''
    steps: list = field(default_factory=list)
    cost_microusd: int = 0
    pending_action: dict | None = None    # what the user would be approving, for a handoff on a sensitive control


class BrowseRunner:
    def __init__(self, session, ladder: Ladder, *, policy: Policy | None = None, on_event=lambda kind, data: None, cancelled=lambda: False,
                 max_steps=25, max_seconds=600, shots=True, clock=time.monotonic, pause_gate=lambda: 0):
        self.s, self.ladder, self.policy, self.on_event, self.cancelled = session, ladder, policy or Policy(), on_event, cancelled
        self.max_steps, self.max_seconds, self.shots, self.clock = max_steps, max_seconds, shots, clock
        self.pause_gate = pause_gate        # blocks while the user has the wheel; returns the seconds waited so they do not count against the time limit

    def run(self, goal: str, start_url: str) -> Result:
        res = Result('error')
        if not self.policy.url_ok(start_url):
            return Result('blocked', 'that site is not allowed')
        opened = self.s.open(start_url)
        if not opened.get('ok'):
            return Result('error', f'could not open the page ({opened.get("error")})')
        self.on_event('opened', {'url': opened.get('url'), 'title': opened.get('title')})
        started, history, seen, failures, forced = self.clock(), [], {}, 0, False
        for step in range(1, self.max_steps + 1):
            if self.cancelled():
                return self._end(res, 'cancelled', 'stopped by you', history)
            started += self.pause_gate()
            if self.cancelled():
                return self._end(res, 'cancelled', 'stopped by you', history)
            if self.clock() - started > self.max_seconds:
                return self._end(res, 'deadline', 'time limit reached', history)
            snap = self.s.snapshot()
            if not snap.get('ok'):
                return self._end(res, 'error', 'could not read the page', history)
            url = snap.get('url', '')
            if not self.policy.url_ok(url):
                return self._end(res, 'blocked', 'the page moved to a site that is not allowed', history, url)
            candidates = cand.build(snap.get('snapshot', ''))
            page = {'url': url, 'title': neutralize(snap.get('title', ''), 300), 'text': neutralize(snap.get('text', ''))}
            if self.policy.read_only and cand.page_is_payment(url, snap.get('snapshot', ''), page['text']):
                return self._end(res, 'handoff', 'reached a payment step; you take it from here', history, url)
            try:
                d: Decision = self.ladder.decide(goal, history, page, candidates, force_escalate=forced, failures=failures)
            except Refused as exc:
                return self._end(res, 'budget', f'stopped: the spending limit was reached ({exc})', history, url)
            res.cost_microusd += d.cost_microusd
            forced = False
            if d.kind == 'done':
                res.answer = d.answer
                return self._end(res, 'done', d.reason, history, url)
            if d.kind == 'stop':
                return self._end(res, 'stopped', d.reason or 'could not continue', history, url)
            a = d.action
            chosen = next((c for c in candidates if c['ref'] == a['ref']), None) if a['ref'] is not None else None
            if self.policy.gate(url, snap.get('snapshot', ''), page['text'], chosen) == 'handoff':
                res.pending_action = {'action': a['action'], 'label': a['label'], 'url': url}
                return self._end(res, 'handoff', f'next step is "{a["label"]}", which needs you', history, url)
            key = (url, a['action'], a['ref'], a.get('label'))
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 2:
                if seen[key] > 3:
                    return self._end(res, 'stuck', 'repeating the same step', history, url)
                forced = True
            out = self.s.act(a['action'], a['ref'], a.get('value'), a.get('label'))
            entry = {'step': step, 'by': d.by, 'action': a['action'], 'label': a['label'], 'result': 'ok' if out.get('ok') else out.get('error', 'failed')}
            history.append(entry)
            self.on_event('step', {**entry, 'url': out.get('url', url), 'confidence': d.confidence, **d.meta})
            if not out.get('ok'):
                failures += 1
                if failures >= 4:
                    return self._end(res, 'stuck', 'too many failed steps', history, url)
                continue
            failures = 0
            if self.shots:
                shot = self.s.screenshot()
                if shot.get('ok'):
                    self.on_event('screenshot', {'file': shot['file'], 'step': step})
        return self._end(res, 'max_steps', 'step limit reached', history)

    @staticmethod
    def _end(res, status, reason, history, url=''):
        res.status, res.reason, res.steps, res.url = status, reason, history, url or res.url
        return res
