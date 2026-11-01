"""The browse loop: observe -> decide (ladder) -> policy -> fresh-target act -> record. No model can widen what is allowed."""
from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass, field
import re
import time
from urllib.parse import urlsplit

from . import candidates as cand
from . import modes
from agentai_platform import privacy
from .untrusted import neutralize
from .ladder import RUNNER_V2, Decision, Ladder, Look, Refused
from .trace import NULL

LOGIN_REASON = 'this page needs you to sign in; I never type passwords'
WALL_REASON = 'the site is asking to verify you are human, which I cannot pass for you'
# What the customer is told while the run waits for them (the run stays alive, and carries on when they are done).
WAIT_WALL = 'The site is asking you to verify you are human. Do it in the browser below, then press Continue.'
WAIT_LOGIN = 'This page needs you to sign in. Lumina never types your password. Sign in in the browser below, then press Continue.'
WAIT_PASSWORD = 'The next step is a password. Lumina never types passwords. Enter it in the browser below, then press Continue.'
MAX_HANDOFFS = 5        # times one run waits for the customer; after that the same stop ends the run as it always did
DEFAULT_DENY = re.compile(r'(^|\.)(paypal|venmo|cash\.app|chase|bankofamerica|wellsfargo|citi|capitalone|robinhood|coinbase|binance|fidelity|schwab|vanguard)\.', re.I)


CARD_NUMBER = re.compile(r'card\s*number|number on (the )?card|credit card|debit card|^card$|card no', re.I)
CARD_NAME = re.compile(r'name on (the )?card|card\s*holder', re.I)
CARD_EXPIRY = re.compile(r'expir|mm\s*/\s*yy|valid (thru|through|until)|expiry', re.I)
CARD_CODE = re.compile(r'cvv|cvc|security code|verification', re.I)


def _host(url):
    host = (urlsplit(url or '').hostname or '').lower().rstrip('.')
    return host[4:] if host.startswith('www.') else host


def _where(url):
    """Host and path only: a query string or fragment can carry tokens and personal data."""
    parts = urlsplit(url or '')
    return f'{parts.hostname or ""}{parts.path}'[:200]


@dataclass
class Policy:
    """Code-side rules. `read_only` is the first release: browse, compare and fill a cart, but stop at any payment step."""
    read_only: bool = True
    deny_domains: re.Pattern = DEFAULT_DENY
    # `switch(key) -> bool`: is this safety switch on for the account the job runs for (agentai_platform/safety.py)? Every rule below asks before it acts; the default is on.
    switch: Callable[[str], bool] = lambda key: True

    def on(self, key: str) -> bool:
        try:
            return bool(self.switch(key))
        except Exception:
            return True                                  # fails closed: a switch that cannot be read is on

    def url_ok(self, url: str) -> bool:
        try:
            if any(ord(c) < 33 for c in url or ''):
                return False
            parsed = urlsplit(url or '')
            host = (parsed.hostname or '').rstrip('.').encode('idna').decode('ascii')
            if parsed.port is not None and not 1 <= parsed.port <= 65535:
                return False
            return parsed.scheme.lower() in ('http', 'https') and bool(host) and parsed.username is None and parsed.password is None and not (self.on('denied_sites') and self.deny_domains.search(host + '.'))
        except (ValueError, UnicodeError):
            return False

    def gate(self, url, snapshot_text, page_text, chosen) -> str:
        """'ok' | 'handoff' (payment/consequential step: the user takes over) -- evaluated BEFORE any click."""
        if self.on('payment_stop') and cand.page_is_payment(url, snapshot_text, page_text):
            return 'handoff'
        if self.on('sensitive_approval') and chosen and (chosen.get('sensitive') or (chosen.get('label') and cand.SENSITIVE.search(chosen['label']))):   # `sensitive` also covers password fields
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
                 on_now=lambda by, mode, note: None, ask_gate=None, prefs=None, vault=None, hand_gate=None):
        self.s, self.ladder, self.policy, self.on_event, self.cancelled = session, ladder, policy or Policy(), on_event, cancelled
        self.max_steps, self.max_seconds, self.shots, self.clock = max_steps, max_seconds, shots, clock
        self.trace = trace
        self.wait, self.on_stat = wait, on_stat      # on_stat(name): a counter the service keeps for the run (who decided what, how often JEV missed)
        self.pause_gate = pause_gate        # blocks while the user has the wheel; returns the seconds waited so they do not count against the time limit
        self.ask_gate = ask_gate            # ask_gate(question) -> (answer | None, seconds waited): blocks while the user decides; None = no answer (cancelled or timed out)
        self.prefs = {str(k).lower(): str(v) for k, v in (prefs or {}).items() if k and v}      # what the customer told us before, by field (size -> M); never secrets
        self.vault = [i for i in (vault or []) if isinstance(i, dict) and i.get('kind') in ('login', 'card') and isinstance(i.get('id'), str)]      # what the customer keeps (label, site, hint): never the secrets
        self._filled = set()               # sites where a saved login was already used in this run: one try per site
        self.hand_gate = hand_gate          # hand_gate(reason, probe=, still_blocked=) -> (outcome, seconds waited): keeps the run alive while the customer does what only they can (None = the run ends instead)
        self._handoffs = 0
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
        token = privacy.set_scrubbing(True)
        try:
            return self._run(goal, start_url)
        finally:
            privacy.reset_scrubbing(token)

    def _neutral(self, text, limit=None):
        """Page text read by a model: sentences aimed at the AI removed, unless the account switched `untrusted_page_text` off (then only the length limit applies)."""
        if self.policy.on('untrusted_page_text'):
            return neutralize(text, limit)
        out = str(text or '')
        return out if limit is None else out[:limit]

    def _run(self, goal: str, start_url: str) -> Result:
        res = Result('error')
        if not self.policy.url_ok(start_url):
            return Result('blocked', 'that site is not allowed')
        opened = self.s.open(start_url)
        if not opened.get('ok'):
            return Result('error', f'could not open the page ({opened.get("error")})')
        self.on_event('opened', {'url': opened.get('url'), 'title': opened.get('title')})
        started, history, seen, failures, forced = self.clock(), [], {}, 0, False
        reopens = 0          # times the browser fell off the site (a `back` from the first page lands on a blank page) and the start page was opened again
        jev_misses = 0       # JEV was asked and someone else took the step, in a row; resets only when a JEV step is acted on successfully
        unchanged = 0        # acted steps in a row (a wait does not count) after which the page looked exactly the same
        hold = None          # {'reason', 'url'} while the assistant, not JEV, decides the steps on this page; it ends when a Claude step moves the page or the page changes address
        picture_only = bool(getattr(self.ladder.jev, 'picture_only', False))      # the owner's navigation test (picture_only_brain.py): JEV is shown the window only, and no one else decides a step
        for step in range(1, self.max_steps + 1):
            self.trace.step = step
            privacy.set_scrubbing(self.policy.on('personal_data_scrub'))      # read at every step: text for JEV is scrubbed unless this account switched it off
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
            if (not url or url.startswith('about:')) and reopens < 2:       # went back past the first page: that is not a site, so open the start page again instead of ending the run
                reopens += 1
                self.trace.emit('left_site', reopens=reopens)
                self.s.open(start_url)
                entry = {'step': step, 'by': 'rule', 'action': 'back', 'label': '', 'result': 'left_the_site', 'changed': None, 'note': 'went back past the start page; opened it again'}
                history.append(entry)
                self.on_event('step', {**entry, 'url': start_url})
                continue
            if not self.policy.url_ok(url):
                return self._end(res, 'blocked', 'the page moved to a site that is not allowed', history, url)
            walls = self.policy.on('denied_sites')        # the human-check and sign-in stops belong to the `denied_sites` switch
            for _ in range(3):                  # some verification pages clear by themselves within seconds
                if not walls or not cand.page_is_bot_check(snap.get('title', ''), snap.get('text', '')):
                    break
                self.wait(4)
                again = self.s.snapshot()
                if not again.get('ok'):
                    break
                snap = again
            if walls and cand.page_is_bot_check(snap.get('title', ''), snap.get('text', '')):
                self.trace.emit('floor', rule='bot check wall')
                outcome, waited = self._wait_for_user(WAIT_WALL, lambda s: cand.page_is_bot_check(s.get('title', ''), s.get('text', '')), step, history, snap.get('url', ''))
                started += waited
                if outcome != 'timeout':          # they did it (or asked to stop): read the page again
                    continue
                return self._end(res, 'handoff', WALL_REASON, history, snap.get('url', ''))
            url = snap.get('url', '')
            if not self.policy.url_ok(url):
                return self._end(res, 'blocked', 'the page moved to a site that is not allowed', history, url)
            fp_before = snap.get('page_fp')
            candidates = cand.build(snap.get('snapshot', ''), elements=snap.get('elements'))
            self.trace.emit('snapshot', where=_where(url), candidates=len(candidates), text_chars=len(snap.get('text') or ''), page_fp=fp_before, v2=snap.get('elements') is not None)
            page = {'url': url, 'title': self._neutral(snap.get('title', ''), 300), 'text': self._neutral(snap.get('text', ''))}
            if self.policy.read_only and self.policy.on('payment_stop') and cand.page_is_payment(url, snap.get('snapshot', ''), page['text']):
                self.trace.emit('floor', rule='payment page')
                outcome, waited = self._offer_fill('card', url, snap, step, history)
                started += waited
                if outcome == 'filled':        # the card is in; the security code and the order are the customer's, and no model sees this page
                    return self._end(res, 'handoff', 'I filled in your saved card. Enter the security code, check everything, and place the order yourself.', history, url)
                return self._end(res, 'handoff', 'reached a payment step; you take it from here', history, url)
            if walls and cand.page_is_login(snap.get('snapshot', '')):
                self.trace.emit('floor', rule='sign-in page')
                outcome, waited = self._offer_fill('login', url, snap, step, history) if self._handoffs == 0 else ('none', 0)       # asked once; coming back to the page means they chose to do it themselves
                started += waited
                if outcome == 'filled':        # signed in with the saved login: the next step reads the page after it, never this one
                    continue
                outcome, waited = self._wait_for_user(WAIT_LOGIN, lambda s: cand.page_is_login(s.get('snapshot', '')), step, history, url)
                started += waited
                if outcome != 'timeout':
                    continue
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
            if hold is None and not picture_only and (reason := modes.claude_reason(history)):
                hold, notice = {'reason': reason, 'url': url}, 'took'
                self.trace.emit('claude_page', outcome='taken', why=reason)
                self.on_stat('claude_page_takeovers')
            mode, mode_why = modes.choose_mode(snap, candidates, history)
            pos_words, _bottom = modes.position(snap)
            look = Look(position=pos_words, hint=modes.hint(snap, history), why=mode_why,
                        claude=hold['reason'] if hold else '')
            visible, covered = modes.covered_share(snap)
            if snap.get('window') is not None:            # the deciders see the window on every step (a runner that cannot take a picture is the only exception)
                only_picture = not candidates or picture_only         # no list to choose from: the picture is all there is, and it is kept with the run's pictures
                view = self.s.view(save=self.shots and only_picture)
                if view.get('ok'):
                    look.shot = {'data': view['data'], 'width': view['width'], 'height': view['height'], 'view': view['view']}
                    if view.get('file'):
                        self.on_event('screenshot', {'file': view['file'], 'step': step, 'seen_by': 'jev', 'why': mode_why})      # what JEV was shown, in the run's pictures
                elif only_picture and not hold:
                    look.claude = 'the picture of the window could not be taken'
            self.trace.emit('mode', mode='sight' if look.shot is not None and candidates else 'picture' if look.shot is not None else 'controls', wanted=mode, why=mode_why,
                            claude=look.claude, visible=visible, covered=covered, hinted=bool(look.hint), position=pos_words)
            now_mode = 'picture' if look.shot is not None else 'controls'            # the live label: JEV is looking at the picture (with or without the list)
            if notice or (now_mode == 'picture' and not look.claude and self._now != ('jev', 'picture')):     # a change worth a little notice, told before the step is decided
                self._publish('claude' if look.claude else 'jev', now_mode, notice or 'picture')
            try:
                d: Decision = self.ladder.decide(goal, history, page, candidates, force_escalate=forced, failures=failures, jev_misses=jev_misses,
                                                 caps=RUNNER_V2 if snap.get('elements') is not None else frozenset(), look=look)
            except Refused as exc:
                return self._end(res, 'budget', f'stopped: the spending limit was reached ({exc})', history, url)
            res.cost_microusd += d.cost_microusd
            if d.kind == 'act':                                                         # who really decided this step; a final answer or a stop is not a take-over
                by_now = 'claude' if d.by == 'agent' else 'jev'
                self._publish(by_now, now_mode, 'help' if by_now == 'claude' and d.miss and not look.claude else '')       # 'help': JEV was asked, missed, and Claude took just this step
            forced = False
            self.trace.emit('decision', by=d.by, verdict=d.kind, action=(d.action or {}).get('action'), ref=(d.action or {}).get('ref'), label=(d.action or {}).get('label'),
                            confidence=d.confidence, miss=d.miss, signal=d.signal, text_src=d.text_src, cost_microusd=d.cost_microusd, reason=d.reason if d.kind != 'act' else '')
            if d.miss:
                jev_misses += 1
                self.on_stat('jev_misses')
            if d.signal:
                self.on_stat('jev_' + d.signal)                 # jev_needs_user | jev_too_complex
            if d.agent_answer:
                self.on_stat('agent_answer')
            if d.kind == 'done':
                res.answer = d.answer
                return self._end(res, 'done', d.reason, history, url)
            if d.kind == 'handoff':
                outcome, waited = self._wait_for_user(d.reason or WAIT_LOGIN, None, step, history, url)       # JEV added a hand-off; it can never remove one. They press Continue when they are done
                started += waited
                if outcome != 'timeout':
                    continue
                return self._end(res, 'handoff', d.reason, history, url)
            if d.kind == 'stop':
                return self._end(res, 'stopped', d.reason or 'could not continue', history, url)
            if d.kind == 'ask' and d.question.get('kind') == 'fields':
                filled, waited = self._ask_fields(d.question, step, history)
                started += waited
                if filled == 'none':
                    return self._end(res, 'cancelled' if self.cancelled() else 'stopped', 'stopped by you' if self.cancelled() else 'no answer to the question', history, url)
                self.trace.emit('ask', outcome=filled, fields=len(d.question['fields']))
                self.on_stat('ask_fields_filled' if filled == 'filled' else 'ask_fields_page')
                if filled == 'page':             # they filled the form on the page themselves and pressed Continue: read the page again
                    entry = {'step': step, 'by': d.by, 'action': 'ask', 'label': 'details', 'result': 'ok', 'changed': None, 'note': 'the user filled the form on the page'}
                    history.append(entry)
                    self.on_event('step', {**entry, 'url': url})
                continue
            if d.kind == 'ask':
                option = self._remembered(d.question)
                note = 'remembered'
                if option is None:
                    option, note, waited = self._ask_user(d.question, step)
                    started += waited
                    if note == 'none':
                        return self._end(res, 'cancelled' if self.cancelled() else 'stopped', 'stopped by you' if self.cancelled() else 'no answer to the question', history, url)
                if option is None:               # the user picked on the page themselves (View full menu) and pressed Continue: read the page again
                    entry = {'step': step, 'by': d.by, 'action': 'ask', 'label': d.question.get('field', ''), 'result': 'ok', 'changed': None, 'note': 'the user chose on the page'}
                    history.append(entry)
                    self.on_event('step', {**entry, 'url': url})
                    continue
                self.on_stat('ask_remembered' if note == 'remembered' else 'ask_answered')
                self.trace.emit('ask', outcome=note, field=d.question.get('field'), options=len(d.question['options']))
                d = Decision('act', d.by, 'the user chose', action=dict(option['do']), cost_microusd=d.cost_microusd, meta={'ask': note})
            a = d.action
            chosen = next((c for c in candidates if c['ref'] == a['ref']), None) if a['ref'] is not None else None
            if a['action'] in ('clickat', 'typeat'):      # chosen from a picture: name what is really under that point, then apply the same rules as to any control
                probed = self.s.probe(a['x'], a['y'])
                hit = probed.get('hit') if probed.get('ok') else None
                a['label'] = (hit or {}).get('label', '')
                chosen = {'sensitive': bool(hit and hit.get('secret')) or bool(cand.SENSITIVE.search(a['label'])), 'label': a['label'], 'password': bool(hit and hit.get('secret'))}
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
                if chosen and (chosen.get('input_type') == 'password' or chosen.get('password')):       # a password is the customer's: they enter it, press Continue, and the run goes on
                    outcome, waited = self._wait_for_user(WAIT_PASSWORD, None, step, history, url)
                    started += waited
                    if outcome != 'timeout':
                        continue
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
            self.on_stat({'jev': 'jev_acted', 'agent': 'agent_step'}.get(d.by, 'other_step'))        # every acted step is counted exactly once
            if d.text_src:
                self.on_stat('jev_typed_from_goal' if d.text_src == 'goal' else 'helper_text' if d.text_src == 'helper' else 'agent_text')               # sub-counts of a JEV step
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
                if unchanged >= 4:                    # three steps changed nothing, and the next one (the assistant's) did not either
                    return self._end(res, 'stuck', 'the page is not changing', history, url)
                if unchanged == 3:
                    forced = True                     # a loop signal: the next step goes to the assistant
                    self.trace.emit('loop_signal', rule='three acted steps with the page unchanged')
                    self.on_stat('no_change_loops')
            if self.shots:
                shot = self.s.screenshot()
                if shot.get('ok'):
                    self.on_event('screenshot', {'file': shot['file'], 'step': step})
        return self._end(res, 'max_steps', 'step limit reached', history)

    def _offer_fill(self, kind, url, snap, step, history):
        """A sign-in or payment page, and the customer keeps a login (for this site) or a card: ask whether to use it. -> ('filled' | 'declined' | 'failed' | 'none', seconds waited).
        The secret arrives only with the customer's yes, goes straight into the page's fields, and is never given to a model, the trace, the steps or a picture."""
        host = _host(url)
        items = [i for i in self.vault if i['kind'] == kind and (kind == 'card' or i.get('site') == host)]
        if self.ask_gate is None or not items or (kind == 'login' and host in self._filled):
            return 'none', 0
        options = [{'id': f'o{n}', 'label': f'Use {i["label"]}', 'item': i['id'], 'do': {'action': 'fill'}} for n, i in enumerate(items[:5], 1)]
        options.append({'id': f'o{len(options) + 1}', 'label': 'I will do it myself', 'do': {'action': 'self'}})
        title = f'Sign in to {host} with your saved login?' if kind == 'login' else 'Fill in your saved card? You type the security code and place the order yourself.'
        self.trace.emit('ask', outcome='offered', use=kind)
        answer, waited = self.ask_gate({'title': title, 'field': '', 'options': options, 'menu': False, 'use': kind}, step)
        chosen = next((o for o in options if o['id'] == (answer or {}).get('option')), None)
        secret = (answer or {}).get('secret')
        if chosen is None or chosen['do']['action'] != 'fill' or not isinstance(secret, dict):
            return 'declined', waited
        try:
            ok = self._fill_login(secret, snap, history, host) if kind == 'login' else self._fill_card(secret, snap, history)
        finally:
            secret.clear()
        self.trace.emit('fill', use=kind, ok=ok)
        self.on_stat('fill_used' if ok else 'fill_failed')
        return ('filled' if ok else 'failed'), waited

    def _type(self, field, value, history, step_by='rule'):
        out = self.s.act('type', field['ref'], value, field['label'])
        history.append({'step': len(history) + 1, 'by': step_by, 'action': 'type', 'label': field['label'], 'result': 'ok' if out.get('ok') else out.get('error', 'failed'), 'changed': None})
        return bool(out.get('ok'))

    def _fill_login(self, secret, snap, history, host):
        fields = cand.build(snap.get('snapshot', ''), limit=200, elements=snap.get('elements'))
        password = next((c for c in fields if c['input_type'] == 'password'), None)
        user = next((c for c in reversed(fields) if password and c['action'] == 'type' and c['input_type'] != 'password' and c['ref'] < password['ref']), None)
        if not (password and user and secret.get('username') and secret.get('password')):
            return False
        self._filled.add(host)
        if not (self._type(user, secret['username'], history) and self._type(password, secret['password'], history)):
            return False
        out = self.s.act('press', None, 'Enter', '')
        history.append({'step': len(history) + 1, 'by': 'rule', 'action': 'press', 'label': 'Enter', 'result': 'ok' if out.get('ok') else out.get('error', 'failed'), 'changed': None})
        return bool(out.get('ok'))

    def _fill_card(self, secret, snap, history):
        fields = [c for c in cand.build(snap.get('snapshot', ''), limit=200, elements=snap.get('elements')) if c['action'] == 'type']
        month, year = int(secret.get('exp_month') or 0), int(secret.get('exp_year') or 0)
        wanted = []
        for c in fields:
            label = c['label'].lower()
            if CARD_NAME.search(label):
                wanted.append((c, secret.get('name') or ''))
            elif CARD_NUMBER.search(label) and not CARD_CODE.search(label):
                wanted.append((c, secret.get('number') or ''))
            elif CARD_EXPIRY.search(label):
                long_year = 'yyyy' in label or 'full year' in label
                if 'month' in label and 'year' not in label:
                    wanted.append((c, f'{month:02d}'))
                elif 'year' in label and 'month' not in label:
                    wanted.append((c, str(year) if (long_year or 'yy' not in label) else f'{year % 100:02d}'))
                else:
                    wanted.append((c, f'{month:02d}/{year if long_year else year % 100:02d}'))
        if not any(CARD_NUMBER.search(c['label'].lower()) and v == secret.get('number') for c, v in wanted):
            return False                                            # the number field was not found (often a payment frame we cannot reach): the customer does it
        done = [self._type(c, v, history) for c, v in wanted if v]
        return bool(done) and all(done)

    def _ask_fields(self, question, step, history):
        """Ask for each detail a form needs (one field at a time in the customer's box), then type the answers into the page. -> ('filled' | 'page' | 'none', seconds waited).
        What they typed goes straight into the fields: not into a trace, a step or a model prompt. A field marked sensitive is never collected here."""
        if self.ask_gate is None:
            return 'none', 0
        asked = {**question, 'fields': [{**f, 'prefill': '' if f['sensitive'] else self.prefs.get(f['key'], '')} for f in question['fields']]}
        self.trace.emit('ask', outcome='asked', fields=len(asked['fields']))
        answer, waited = self.ask_gate(asked, step)
        if not answer:
            return 'none', waited
        values = answer.get('fields')
        if not isinstance(values, dict):
            return 'page', waited
        snap = self.s.snapshot()                       # the page may have moved on while they typed: find each field again by its label
        pool = cand.build(snap.get('snapshot', ''), limit=200, elements=snap.get('elements')) if snap.get('ok') else []
        done = 0
        for f in question['fields']:
            value = values.get(f['id'])
            if f['sensitive'] or not isinstance(value, str) or not value.strip():
                continue
            target = next((c for c in pool if c['action'] == 'type' and c['label'].strip().lower() == f['label'].strip().lower()), None) or next((c for c in pool if c['ref'] == f['ref'] and c['action'] == 'type'), None)
            if target is not None and self._type(target, value.strip(), history):
                done += 1
        values.clear()
        return ('filled' if done else 'page'), waited

    def _remembered(self, question):
        """An option the customer already chose for this kind of question (size -> M), or None."""
        value = self.prefs.get((question.get('field') or '').lower())
        if not value:
            return None
        wanted = value.strip().lower()
        for option in question['options']:
            if option['label'].strip().lower() == wanted:
                return option
        for option in question['options']:
            if wanted in option['label'].lower():
                return option
        return None

    def _ask_user(self, question, step):
        """Stop and ask. -> (option | None, 'answered' | 'page' | 'none', seconds waited). `page`: they chose on the page and pressed Continue."""
        if self.ask_gate is None:
            return None, 'none', 0
        self.trace.emit('ask', outcome='asked', field=question.get('field'), options=len(question['options']))
        answer, waited = self.ask_gate({k: v for k, v in question.items()}, step)
        if not answer:
            return None, 'none', waited
        chosen = next((o for o in question['options'] if o['id'] == answer.get('option')), None)
        return (chosen, 'answered', waited) if chosen else (None, 'page', waited)

    def _wait_for_user(self, reason, still_blocked, step, history, url):
        """Something only the customer can do (a sign-in, a password, a human check). With a hand gate the run stays alive: they do it in the browser, and Lumina carries on when they
        press Continue, or by itself once `still_blocked(page)` stops being true. -> ('resumed' | 'auto' | 'cancelled' | 'timeout', seconds waited). 'timeout' also means no gate,
        or this run already waited MAX_HANDOFFS times: the caller then ends the run as before. Nothing they type is read here: only whether the page is still the same kind of page."""
        if self.hand_gate is None or self._handoffs >= MAX_HANDOFFS:
            return 'timeout', 0
        self._handoffs += 1
        self.trace.emit('handoff_wait', n=self._handoffs, auto=still_blocked is not None)
        outcome, waited = self.hand_gate(reason, probe=self.s.snapshot, still_blocked=still_blocked)
        self.trace.emit('handoff_done', n=self._handoffs, outcome=outcome, waited=int(waited))
        if outcome in ('resumed', 'auto'):
            entry = {'step': step, 'by': 'rule', 'action': 'handoff', 'label': 'the customer\'s part', 'result': 'ok', 'changed': None, 'note': 'the customer did it in the browser'}
            history.append(entry)
            self.on_event('step', {**entry, 'url': url})
        return outcome, waited

    def _end(self, res, status, reason, history, url=''):
        res.status, res.reason, res.steps, res.url = status, reason, history, url or res.url
        self.trace.emit('end', status=status, reason=reason, steps=len(history), cost_microusd=res.cost_microusd, where=_where(res.url))
        return res
