"""Deterministic policy applied after the model, outside it. Confidence can never override these rules."""
from __future__ import annotations
from dataclasses import dataclass, field
import re

from .decision import Decision

# Consequential requests need an authorized worker plus explicit approval, whatever the model says.
SENSITIVE = re.compile(
    r"\b(pay|payment|wire|transfer|purchase|buy|order|refund|invoice|charge|delete|remove|erase|cancel|unsubscribe|"
    r"send (an? )?(email|message|text)|email (them|him|her|everyone)|post|publish|tweet|password|credential|api key|"
    r"sign\s*out|log\s*out|submit)\b", re.I)
MIN_LEGAL_ROUTE = 'claude'   # the only route currently wired end to end; others fall back here


@dataclass(frozen=True)
class Outcome:
    recommended: str            # what the model preferred
    route: str                  # what policy allows (always an enabled route)
    action: str                 # auto | checks | escalate | abstain
    requires_approval: bool
    reasons: tuple = field(default_factory=tuple)


def evaluate(decision: Decision, request_text: str, cfg: dict, *, budget_remaining_usd: float | None = None) -> Outcome:
    reasons = []
    enabled = {r for r, on in cfg['routes'].items() if on}
    approval = decision.risk == 'high' or bool(SENSITIVE.search(request_text or ''))
    if approval:
        reasons.append('consequential request: approval required')
    if budget_remaining_usd is not None and budget_remaining_usd < 0.01:
        return Outcome(decision.route, 'abstain', 'abstain', approval, tuple(reasons + ['budget exhausted']))
    if decision.route == 'abstain':
        return Outcome('abstain', MIN_LEGAL_ROUTE if MIN_LEGAL_ROUTE in enabled else 'abstain', 'escalate', approval,
                       tuple(reasons + ['router abstained']))
    route, action = decision.route, 'auto'
    confidence = decision.route_confidence
    if confidence < cfg['confidence']['review']:
        route, action = (MIN_LEGAL_ROUTE, 'escalate')
        reasons.append('confidence below review threshold')
    elif confidence < cfg['confidence']['automatic']:
        action = 'checks'
        reasons.append('confidence needs deterministic checks')
    if decision.risk == 'high' and route in ('deterministic', 'jev_executor'):
        route, action = (MIN_LEGAL_ROUTE, 'escalate')
        reasons.append('high risk is never handled by the lightweight routes')
    if decision.complexity == 'complex' and route in ('deterministic', 'jev_executor'):
        route, action = (MIN_LEGAL_ROUTE, 'escalate')
        reasons.append('complex request needs stronger reasoning')
    if route not in enabled:
        if route != MIN_LEGAL_ROUTE:
            reasons.append(f'route {route} is not enabled: using {MIN_LEGAL_ROUTE}')
        route = MIN_LEGAL_ROUTE if MIN_LEGAL_ROUTE in enabled else 'abstain'
        action = 'escalate' if route != 'abstain' else 'abstain'
    return Outcome(decision.route, route, action, approval, tuple(reasons))
