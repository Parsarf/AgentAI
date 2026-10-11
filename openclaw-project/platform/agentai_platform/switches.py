"""Owner feature switches (stdlib only, so the dashboard can ship a copy).

One small JSON file records which optional features the owner has turned on,
plus explicit confirmations ("I read the data terms"). A switch is only the
top-level on/off: it can never bypass a gate. Turning a switch ON is refused
until every confirmation is recorded and every required fact is true; turning
OFF is always allowed. Everything fails closed: a missing, unreadable or
malformed file means "off". Facts come from a second file that deployment
tooling writes; an absent fact is false, so nothing becomes available by
accident.
"""
from __future__ import annotations
import json
import os
import tempfile
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Switch:
    key: str
    title: str
    plain: str                      # what it is, in plain words
    when_on: str                    # what actually changes
    cost_note: str
    risk: str                       # low | high
    confirmations: tuple = ()       # ((id, text), ...) the owner must tick
    needs: tuple = ()               # ((fact_id, text), ...) must be true
    locked: str = ''                # non-empty: cannot be turned on from the UI at all


CATALOG: dict[str, Switch] = {s.key: s for s in (
    Switch('research_optimization', 'Smarter page reading for research (Jev)',
           'Lets a paid TypeSafe model trim the web pages the researcher reads and rank follow-up links.',
           'Fetched public page text is sent to TypeSafe. If anything goes wrong the original page is used unchanged.',
           'Pay-as-you-go, about $0.042 per million input tokens, billed by TypeSafe and separate from your Anthropic caps.',
           'high',
           confirmations=(('data_handling', 'I have read TypeSafe\'s data terms and accept that public page text is sent to them.'),),
           needs=(('typesafe_key_present', 'A TypeSafe key is installed on the server.'),
                  ('research_provenance', 'The part that tells the plugin which pages are public (not built yet).'))),
    Switch('browser_optimization', 'Smarter browser actions (Jev)',
           'Lets a paid TypeSafe model choose the next click or field on pages the browser worker visits.',
           'Page text and element labels are sent to TypeSafe; sensitive buttons (pay, delete, passwords) always still need your normal approval.',
           'Pay-as-you-go, about $0.042 per million input tokens, billed by TypeSafe.',
           'high',
           confirmations=(('data_handling', 'I accept that page text seen by the browser worker is sent to TypeSafe.'),
                          ('transport_review', 'I reviewed how the browser worker reaches TypeSafe (plans/product/phase-12-transport-boundary.md).')),
           needs=(('typesafe_key_present', 'A TypeSafe key is installed on the server.'),
                  ('browser_route_deployed', 'The optimized browser route is deployed and connected (not yet).'))),
    Switch('connectors_linking', 'Let customers connect Gmail, Calendar, Drive and GitHub (read-only)',
           'Shows the Connect buttons to customers. Access is read-only and nothing is ever sent or changed on their accounts.',
           'Customers can start a sign-in with Google or GitHub; their tokens are kept in protected storage.',
           'No direct cost.', 'high',
           confirmations=(('privacy_notice', 'I have a customer-facing notice explaining what is read and how to disconnect.'),),
           needs=(('provider_registered', 'Google and GitHub sign-in apps are registered for this product.'),
                  ('custody_backend', 'Protected storage for sign-in tokens is set up.'))),
    Switch('credentialed_browsing', 'Let the browser worker use saved logins',
           'Lets a customer give the browser worker a website login it can reuse.',
           'Logins are kept in protected storage and used only on the sites the customer allows.',
           'No direct cost.', 'high',
           needs=(('custody_backend', 'Protected storage for logins is set up.'),
                  ('login_flow', 'The secure login screen is built (not yet).'))),
    Switch('customer_schedules', 'Let customers schedule recurring tasks',
           'Customer tasks that run on a timetable.', 'Tasks start without the customer being present.',
           'Uses the customer\'s task budget each run.', 'high',
           locked='Locked until the safety checks for unattended work have been run (Phase 15).'),
    Switch('claude_code_for_customers', 'Let customer agents use Claude Code for coding',
           'Coding and review agents powered by Claude Code (Sonnet 5.5).', 'Runs code in the customer\'s own workspace.',
           'Uses the customer\'s task budget; not yet metered.', 'high',
           locked='Locked until each customer has an isolated workspace and a metered key (Phase 4 and NATIVE-02).'),
)}


class SwitchError(Exception):
    def __init__(self, reasons):
        super().__init__('; '.join(reasons))
        self.reasons = list(reasons)


def _read_json(path, default):
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else default
    except (OSError, ValueError, TypeError):
        return default


def load_facts(path) -> dict:
    data = _read_json(path, {}) if path else {}
    return {k: v is True for k, v in data.items() if isinstance(k, str)}


class SwitchStore:
    def __init__(self, path, *, facts_path=None, clock=time.time, catalog=None):
        self.path, self.facts_path, self.clock = path, facts_path, clock
        self.catalog = catalog or CATALOG

    # ---- reading (fail closed) ----

    def _state(self) -> dict:
        data = _read_json(self.path, {}) if self.path else {}
        return data.get('switches', {}) if isinstance(data.get('switches'), dict) else {}

    def facts(self) -> dict:
        return load_facts(self.facts_path)

    def is_on(self, key: str) -> bool:
        """The only question product code asks. True only if recorded on AND still allowed."""
        if key not in self.catalog:
            return False
        entry = self._state().get(key)
        if not isinstance(entry, dict) or entry.get('on') is not True:
            return False
        return not self.blockers(key, entry=entry)

    def blockers(self, key: str, *, entry=None, facts=None) -> list[str]:
        sw = self.catalog[key]
        if sw.locked:
            return [sw.locked]
        entry = entry if entry is not None else self._state().get(key, {})
        facts = facts if facts is not None else self.facts()
        confirmed = entry.get('confirmations', {}) if isinstance(entry, dict) else {}
        reasons = [text for fid, text in sw.needs if facts.get(fid) is not True]
        reasons += ['Confirm: ' + text for cid, text in sw.confirmations if not (isinstance(confirmed, dict) and confirmed.get(cid))]
        return reasons

    def describe(self, key: str) -> dict:
        sw = self.catalog[key]
        entry = self._state().get(key, {})
        entry = entry if isinstance(entry, dict) else {}
        blockers = self.blockers(key, entry=entry)
        recorded_on = entry.get('on') is True
        return {'key': key, 'title': sw.title, 'plain': sw.plain, 'when_on': sw.when_on, 'cost_note': sw.cost_note,
                'risk': sw.risk, 'locked': sw.locked, 'recorded_on': recorded_on,
                # "on" in effect only when recorded on and nothing blocks it
                'effective_on': recorded_on and not blockers,
                'status': 'locked' if sw.locked else ('on' if recorded_on and not blockers else
                                                      ('on_but_blocked' if recorded_on else 'off')),
                'blockers': blockers, 'changed_at': entry.get('changed_at'), 'changed_by': entry.get('changed_by'),
                'confirmations': [{'id': cid, 'text': text, 'at': (entry.get('confirmations') or {}).get(cid)}
                                  for cid, text in sw.confirmations],
                'can_turn_on': not blockers}

    # ---- writing ----

    def _write(self, switches: dict) -> None:
        if not self.path:
            raise SwitchError(['no switch file is configured'])
        directory = os.path.dirname(self.path) or '.'
        tmp = None
        try:
            os.makedirs(directory, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=directory, prefix='.switches-')
            with os.fdopen(fd, 'w') as f:
                json.dump({'version': 1, 'switches': switches}, f, indent=1, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o644)       # states only; no secrets live in this file
            os.replace(tmp, self.path)
        except OSError as exc:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            raise SwitchError([f'could not save ({type(exc).__name__})']) from None

    def confirm(self, key: str, confirmation_id: str, by: str) -> None:
        sw = self.catalog.get(key)
        if not sw or sw.locked or confirmation_id not in dict(sw.confirmations):
            raise SwitchError(['unknown confirmation'])
        state = self._state()
        entry = dict(state.get(key, {}))
        confirmations = dict(entry.get('confirmations', {}))
        confirmations[confirmation_id] = {'at': int(self.clock()), 'by': str(by)[:60]}
        entry['confirmations'] = confirmations
        state[key] = entry
        self._write(state)

    def set(self, key: str, on: bool, by: str) -> dict:
        """Turn a switch on or off. ON needs every confirmation and fact; OFF always works.
        Returns the read-back description; raises SwitchError on refusal or a readback mismatch."""
        if key not in self.catalog:
            raise SwitchError(['unknown switch'])
        if on:
            reasons = self.blockers(key)
            if reasons:
                raise SwitchError(reasons)
        state = self._state()
        entry = dict(state.get(key, {}))
        entry.update({'on': bool(on), 'changed_at': int(self.clock()), 'changed_by': str(by)[:60]})
        state[key] = entry
        self._write(state)
        after = self.describe(key)
        if after['recorded_on'] != bool(on):
            raise SwitchError(['readback mismatch — change not confirmed'])
        return after

    def all(self) -> list[dict]:
        return [self.describe(k) for k in self.catalog]


def kill_switches(store: SwitchStore):
    """Adapter for OptimizationGate: re-read on every call."""
    return lambda: {'browser': store.is_on('browser_optimization'), 'research': store.is_on('research_optimization')}
