"""Strict validation of the JEV routing response. Anything unexpected becomes a rejection, never a route."""
from __future__ import annotations
from dataclasses import dataclass
import math

from .config import ROUTES

RISKS = ('low', 'medium', 'high')
COMPLEXITY = ('simple', 'moderate', 'complex')
ROUTE_CRITERIA = {
    'deterministic': 'A calculation, unit or format conversion, or lookup that ordinary code can do exactly',
    'jev_executor': 'A small bounded choice or classification among predefined options',
    'specialist_worker': 'Browsing, web research or other work that needs a dedicated worker',
    'claude': 'Open-ended reasoning, planning, writing or an unclear request that needs strong reasoning',
    'codex': 'Writing, changing or debugging software',
    'abstain': 'Too unclear, unsafe or out of scope to route',
}
RISK_CRITERIA = {'low': 'Reversible; no money, no messages sent, no deletion',
                 'medium': 'Changes something, but it can be undone',
                 'high': 'Money, sending messages to others, deleting, or anything irreversible'}
COMPLEXITY_CRITERIA = {'simple': 'One step, answerable directly', 'moderate': 'A few steps',
                       'complex': 'Many steps, planning or synthesis needed'}


@dataclass(frozen=True)
class Decision:
    route: str
    route_confidence: float
    risk: str
    risk_confidence: float
    complexity: str
    input_tokens: int
    output_tokens: int


class Rejected(Exception):
    pass


def _finite01(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0.0 <= v <= 1.0


def _choice(answers, name, options):
    ans = answers.get(name)
    if not isinstance(ans, dict) or ans.get('type') != 'choice':
        raise Rejected(f'{name}: not a choice answer')
    choice, probs = ans.get('choice'), ans.get('probabilities')
    if choice not in options:
        raise Rejected(f'{name}: unknown option')
    if not isinstance(probs, dict) or set(probs) != set(options) or not all(_finite01(v) for v in probs.values()):
        raise Rejected(f'{name}: bad probabilities')
    if not math.isclose(sum(probs.values()), 1.0, rel_tol=0.0, abs_tol=0.05):
        raise Rejected(f'{name}: probabilities do not sum to 1')
    if max(probs, key=probs.get) != choice:
        raise Rejected(f'{name}: choice is not the most likely option')
    # Confidence used by policy is the probability of the chosen option: the provider's separate
    # "confidence" field was observed to differ from it (0.79 vs 0.83), so it is not trusted as the signal.
    return choice, float(probs[choice])


def parse(data, pinned_model: str) -> Decision:
    if not isinstance(data, dict):
        raise Rejected('not an object')
    if data.get('model') != pinned_model:
        raise Rejected('model pin mismatch')
    answers = data.get('answers')
    if not isinstance(answers, dict):
        raise Rejected('missing answers')
    route, route_p = _choice(answers, 'route', ROUTES)
    risk, risk_p = _choice(answers, 'risk', RISKS)
    complexity, _ = _choice(answers, 'complexity', COMPLEXITY)
    usage = data.get('usage') if isinstance(data.get('usage'), dict) else {}
    tin, tout = usage.get('input_tokens'), usage.get('output_tokens')
    tin = tin if type(tin) is int and tin >= 0 else 0
    tout = tout if type(tout) is int and tout >= 0 else 0
    return Decision(route, route_p, risk, risk_p, complexity, tin, tout)
