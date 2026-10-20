"""The browse loop: observe -> decide (ladder) -> policy -> fresh-target act -> record. No model can widen what is allowed."""
from __future__ import annotations
from dataclasses import dataclass, field
import re
import time
from urllib.parse import urlsplit

from . import candidates as cand
from . import modes
from .untrusted import neutralize
from .ladder import RUNNER_V2, Decision, Ladder, Look, Refused
from .trace import NULL

LOGIN_REASON = 'this page needs you to sign in; I never type passwords'
WALL_REASON = 'the site is asking to verify you are human, which I cannot pass for you'
DEFAULT_DENY = re.compile(r'(^|\.)(paypal|venmo|cash\.app|chase|bankofamerica|wellsfargo|citi|capitalone|robinhood|coinbase|binance|fidelity|schwab|vanguard)\.', re.I)


def _where(url):
    """Host and path only: a query string or fragment can carry tokens and personal data."""
    parts = urlsplit(url or '')
    return f'{parts.hostname or ""}{parts.path}'[:200]


@dataclass
class Policy:
    """Code-side rules. `read_only` is the first release: browse, compare and fill a cart, but stop at any payment step."""
    read_only: bool = True
    deny_domains: re.Pattern = DEFAULT_DENY

    def url_ok(self, url: str) -> bool:
        try:
            if any(ord(c) < 33 for c in url or ''):
                return False
            parsed = urlsplit(url or '')
            host = (parsed.hostname or '').rstrip('.').encode('idna').decode('ascii')
            if parsed.port is not None and not 1 <= parsed.port <= 65535:
                return False
            return parsed.scheme.lower() in ('http', 'https') and bool(host) and parsed.username is None and parsed.password is None and not self.deny_domains.search(host + '.')
        except (ValueError, UnicodeError):
            return False

    def gate(self, url, snapshot_text, page_text, chosen) -> str:
        """'ok' | 'handoff' (payment/consequential step: the user takes over) -- evaluated BEFORE any click."""
        if cand.page_is_payment(url, snapshot_text, page_text):
            return 'handoff'
        if chosen and (chosen.get('sensitive') or (chosen.get('label') and cand.SENSITIVE.search(chosen['label']))):   # `sensitive` also covers password fields
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
                 max_steps=25, max_seconds=600, shots=True, clock=time.monotonic, pause_gate=lambda: 0, wait=time.sleep, on_stat=lambda name, n=1: None, trace=NULL,
                 on_now=lambda by, mode, note: None):
        self.s, self.ladder, self.policy, self.on_event, self.cancelled = session, ladder, policy or Policy(), on_event, cancelled
        self.max_steps, self.max_seconds, self.shots, self.clock = max_steps, max_seconds, shots, clock
        self.trace = trace
        self.wait, self.on_stat = wait, on_stat      # on_stat(name): a counter the service keeps for the run (who decided what, how often JEV missed)
        self.pause_gate = pause_gate        # blocks while the user has the wheel; returns the seconds waited so they do not count against the time limit
        self.on_now, self._now = on_now, None   # on_now(by, mode, note): who is deciding right now ('jev' | 'claude'), from what ('controls' | 'picture'), and a one-word code for a change worth a little notice

    def _publish(self, by, mode, note=''):
        """Tell the live view who is deciding, only when something changed (or there is a notice): the live view shows it next to the frames, so it costs nothing extra."""
        state = (by, mode)
        if state == self._now and not note:
            return
        self._now = state
        try:
            self.on_now(by, mode, note)
        except Exception:                      # a status light must never stop a task
            pass

    def run(self, goal: str, start_url: str) -> Result:
        res = Result('error')
        if not self.policy.url_ok(start_url):
            return Result('blocked', 'that site is not allowed')
        opened = self.s.open(start_url)
        if not opened.get('ok'):
            return Result('error', f'could not open the page ({opened.get("error")})')
        self.on_event('opened', {'url': opened.get('url'), 'title': opened.get('title')})
        started, history, seen, failures, forced = self.clock(), [], {}, 0, False
        jev_misses = 0       # JEV was asked and someone else took the step, in a row; resets only when a JEV step is acted on successfully
        unchanged = 0        # acted steps in a row (a wait does not count) after which the page looked exactly the same
        hold = None          # {'reason', 'url'} while Claude, not JEV, decides the steps on this page; it ends when a Claude step moves the page or the page changes address
        for step in range(1, self.max_steps + 1):
            self.trace.step = step
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
            for _ in range(3):                  # some verification pages clear by themselves within seconds
                if not cand.page_is_bot_check(snap.get('title', ''), snap.get('text', '')):
                    break
                self.wait(4)
                again = self.s.snapshot()
                if not again.get('ok'):
                    break
                snap = again
            if cand.page_is_bot_check(snap.get('title', ''), snap.get('text', '')):
                self.trace.emit('floor', rule='bot check wall')
                return self._end(res, 'handoff', WALL_REASON, history, snap.get('url', ''))
            url = snap.get('url', '')
            if not self.policy.url_ok(url):
                return self._end(res, 'blocked', 'the page moved to a site that is not allowed', history, url)
            fp_before = snap.get('page_fp')
            candidates = cand.build(snap.get('snapshot', ''), elements=snap.get('elements'))
            self.trace.emit('snapshot', where=_where(url), candidates=len(candidates), text_chars=len(snap.get('text') or ''), page_fp=fp_before, v2=snap.get('elements') is not None)
            page = {'url': url, 'title': neutralize(snap.get('title', ''), 300), 'text': neutralize(snap.get('text', ''))}
            if self.policy.read_only and cand.page_is_payment(url, snap.get('snapshot', ''), page['text']):
                self.trace.emit('floor', rule='payment page')
                return self._end(res, 'handoff', 'reached a payment step; you take it from here', history, url)
            if cand.page_is_login(snap.get('snapshot', '')):
                self.trace.emit('floor', rule='sign-in page')
                return self._end(res, 'handoff', LOGIN_REASON, history, url)       # before any model, so a sign-in page is never sent to a third party
            # Say what the last scroll did, now that the page has been read again: where it is, or that it was already at the bottom.
            if history and history[-1]['action'] == 'scroll' and not history[-1].get('note') and history[-1]['result'] == 'ok':
                words, bottom = modes.position(snap)
                history[-1]['note'] = ('already at the bottom of the page, nothing more to see below' if history[-1]['changed'] is False and bottom else f'now {words}') if words else ''
            # Who decides this step, and from what: the page's controls, or a picture of the window; JEV, or Claude for the rest of this page.
            notice = ''
            if hold and (url != hold['url'] or (history and history[-1]['by'] != 'jev' and history[-1]['result'] == 'ok' and history[-1]['changed'] is True)):
                self.trace.emit('claude_page', outcome='released', why='the page changed' if url != hold['url'] else 'a Claude step moved the page')
                hold, notice = None, 'back'
            if hold is None and (reason := modes.claude_reason(history)):
                hold, notice = {'reason': reason, 'url': url}, 'took'
                self.trace.emit('claude_page', outcome='taken', why=reason)
                self.on_stat('claude_page_takeovers')
            mode, mode_why = modes.choose_mode(snap, candidates, history)
            pos_words, _bottom = modes.position(snap)
            look = Look(position=pos_words, hint=modes.hint(snap, history), why=mode_why, claude=hold['reason'] if hold else '')
            visible, covered = modes.covered_share(snap)
            if mode == 'picture' and not hold:
                view = self.s.view(save=self.shots)
                if view.get('ok'):
                    look.shot = {'data': view['data'], 'width': view['width'], 'height': view['height'], 'view': view['view']}
                    if view.get('file'):
                        self.on_event('screenshot', {'file': view['file'], 'step': step, 'seen_by': 'jev', 'why': mode_why})      # what JEV was shown, in the run's pictures
                else:
                    look.claude = 'the picture of the window could not be taken'
            self.trace.emit('mode', mode='picture' if look.shot is not None else 'controls', wanted=mode, why=mode_why, claude=look.claude, visible=visible, covered=covered,
                            hinted=bool(look.hint), position=pos_words)
            now_mode = 'picture' if look.shot is not None else 'controls'
            if notice or (now_mode == 'picture' and not look.claude and self._now != ('jev', 'picture')):     # a change worth a little notice, told before the step is decided
                self._publish('claude' if look.claude else 'jev', now_mode, notice or 'picture')
            try:
                d: Decision = self.ladder.decide(goal, history, page, candidates, force_escalate=forced, failures=failures, jev_misses=jev_misses,
                                                 caps=RUNNER_V2 if snap.get('elements') is not None else frozenset(), look=look)
            except Refused as exc:
                return self._end(res, 'budget', f'stopped: the spending limit was reached ({exc})', history, url)
            res.cost_microusd += d.cost_microusd
            if d.kind == 'act':                                                         # who really decided this step; a final answer or a stop is not a take-over
                by_now = 'claude' if d.by in ('haiku', 'sonnet') else 'jev'
                self._publish(by_now, now_mode, 'help' if by_now == 'claude' and d.miss and not look.claude else '')       # 'help': JEV was asked, missed, and Claude took just this step
            forced = False
            self.trace.emit('decision', by=d.by, verdict=d.kind, action=(d.action or {}).get('action'), ref=(d.action or {}).get('ref'), label=(d.action or {}).get('label'),
                            confidence=d.confidence, miss=d.miss, signal=d.signal, text_src=d.text_src, cost_microusd=d.cost_microusd, reason=d.reason if d.kind != 'act' else '')
            if d.miss:
                jev_misses += 1
                self.on_stat('jev_misses')
            if d.signal:
                self.on_stat('jev_' + d.signal)                 # jev_needs_user | jev_too_complex
            if d.haiku_answer:
                self.on_stat('haiku_answer')
            if d.kind == 'done':
                res.answer = d.answer
                return self._end(res, 'done', d.reason, history, url)
            if d.kind == 'handoff':
                return self._end(res, 'handoff', d.reason, history, url)         # JEV added a hand-off; it can never remove one
            if d.kind == 'stop':
                return self._end(res, 'stopped', d.reason or 'could not continue', history, url)
            a = d.action
            chosen = next((c for c in candidates if c['ref'] == a['ref']), None) if a['ref'] is not None else None
            if a['action'] in ('clickat', 'typeat'):      # chosen from a picture: name what is really under that point, then apply the same rules as to any control
                probed = self.s.probe(a['x'], a['y'])
                hit = probed.get('hit') if probed.get('ok') else None
                a['label'] = (hit or {}).get('label', '')
                chosen = {'sensitive': bool(hit and hit.get('secret')) or bool(cand.SENSITIVE.search(a['label'])), 'label': a['label']}
                self.trace.emit('probe', found=hit is not None, tag=(hit or {}).get('tag'), editable=(hit or {}).get('editable'), secret=(hit or {}).get('secret'))
                if a['action'] == 'typeat' and hit is not None and not hit.get('editable'):
                    entry = {'step': step, 'by': d.by, 'action': 'type', 'label': a['label'], 'result': 'not_a_field', 'changed': None}      # nothing was typed: what JEV pointed at takes no text
                    history.append(entry)
                    self.trace.emit('act_failed', error='not_a_field', failures=failures + 1)
                    self.on_event('step', {**entry, 'url': url, 'confidence': d.confidence, **d.meta})
                    failures += 1
                    if failures >= 4:
                        return self._end(res, 'stuck', 'too many failed steps', history, url)
                    continue
            if self.policy.gate(url, snap.get('snapshot', ''), page['text'], chosen) == 'handoff':
                self.trace.emit('floor', rule='sensitive control', label=a['label'])
                res.pending_action = {'action': a['action'], 'label': a['label'], 'url': url}
                return self._end(res, 'handoff', f'next step is "{a["label"]}", which needs you', history, url)
            # A scroll or key press is the same step only if it is the same move from the same place on the page (the fingerprint includes the scroll position).
            spot = (round(a['x'] / 40), round(a['y'] / 40)) if a['action'] in ('clickat', 'typeat') else None          # the same place, give or take a few pixels
            key = (url, a['action'], a['ref'], a.get('label'), a.get('value') if a['action'] in ('scroll', 'press') else None, fp_before if a['action'] == 'scroll' else None, spot)
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 2:
                if seen[key] > 3:
                    return self._end(res, 'stuck', 'repeating the same step', history, url)
                forced = True
                self.trace.emit('loop_signal', rule='same step a third time', action=a['action'], label=a.get('label'))
            out = self.s.act(a['action'], a['ref'], a.get('value'), a.get('label'), **({'x': a['x'], 'y': a['y']} if a['action'] in ('clickat', 'typeat') else {}))
            after = out.get('page_fp')
            changed = None if not (fp_before and after) else after != fp_before         # None = unknown (an older runner, or the page was mid-change)
            shown = {'clickat': 'click', 'typeat': 'type'}.get(a['action'], a['action'])      # the history and the customer's step list say what was done, not how
            entry = {'step': step, 'by': d.by, 'action': shown, 'label': a['label'], 'result': 'ok' if out.get('ok') else out.get('error', 'failed'), 'changed': changed,
                     **({'move': a.get('value')} if a['action'] == 'scroll' else {})}
            history.append(entry)
            self.on_stat({'jev': 'jev_acted', 'haiku': 'haiku_step', 'sonnet': 'sonnet_step'}.get(d.by, 'other_step'))        # every acted step is counted exactly once
            if d.text_src:
                self.on_stat('jev_typed_from_goal' if d.text_src == 'goal' else 'haiku_text')               # sub-counts of a JEV step
            why = {k: v for k, v in (('miss', d.miss), ('signal', d.signal), ('src', d.text_src)) if v}      # short facts for the run's record; never page text or typed values
            self.trace.emit('act', **{k: entry[k] for k in ('action', 'label', 'result', 'changed', 'by')}, page_fp_before=fp_before, page_fp_after=after)
            self.on_event('step', {**entry, 'url': out.get('url', url), 'confidence': d.confidence, **d.meta, **why})
            if not out.get('ok'):
                failures += 1
                self.trace.emit('act_failed', error=entry['result'], failures=failures)
                if failures >= 4:
                    return self._end(res, 'stuck', 'too many failed steps', history, url)
                continue
            failures = 0
            if d.by == 'jev':
                jev_misses = 0
            if a['action'] != 'wait':
                unchanged = unchanged + 1 if changed is False else 0
                if unchanged >= 4:                    # three steps changed nothing, the next one (Sonnet's, or Haiku's when Sonnet is used up) did not either
                    return self._end(res, 'stuck', 'the page is not changing', history, url)
                if unchanged == 3:
                    forced = True                     # a loop signal: the next step goes to Sonnet
                    self.trace.emit('loop_signal', rule='three acted steps with the page unchanged')
                    self.on_stat('no_change_loops')
            if self.shots:
                shot = self.s.screenshot()
                if shot.get('ok'):
                    self.on_event('screenshot', {'file': shot['file'], 'step': step})
        return self._end(res, 'max_steps', 'step limit reached', history)

    def _end(self, res, status, reason, history, url=''):
        res.status, res.reason, res.steps, res.url = status, reason, history, url or res.url
        self.trace.emit('end', status=status, reason=reason, steps=len(history), cost_microusd=res.cost_microusd, where=_where(res.url))
        return res
