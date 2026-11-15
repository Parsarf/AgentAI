"""How long and how much a task is likely to take, from what similar tasks actually took (roadmap #9).

No model, no guessing: the median and the 90th percentile of the duration and cost of FINISHED tasks of the same kind, for this account when it has enough history, else
across all accounts (numbers only cross accounts, never content). A range is given, never a single figure, together with how many tasks it rests on; with too little
history nothing is given. An estimate informs the customer. It never refuses, delays or limits a task.
"""
from __future__ import annotations
import time

KINDS = ('chat', 'browse', 'plan', 'execute', 'phase', 'goal')
MIN_OWN, MIN_ALL = 5, 20             # fewer finished tasks than this is not a basis for a range
WINDOW_SECONDS = 60 * 86400          # older history says little about today's models and code
SAMPLE = 400


def kind_of(intent: str, goal_mode) -> str:
    if goal_mode or intent in ('goal_continue', 'goal_resume'):
        return 'goal'
    return intent if intent in KINDS else 'chat'


def _percentile(sorted_values, fraction):
    if not sorted_values:
        return None
    index = min(len(sorted_values) - 1, max(0, int(round(fraction * (len(sorted_values) - 1)))))
    return sorted_values[index]


def _history(con, kind, since, account=None):
    """(seconds, micro-dollars) of finished tasks of this kind, newest first. A task's time runs from its first hand-over to the end of its last run."""
    where = "r.goal_mode=1 OR r.intent IN ('goal_continue','goal_resume')" if kind == 'goal' else 'r.goal_mode=0 AND r.intent=?'
    args = [] if kind == 'goal' else [kind]
    sql = f"""SELECT (SELECT max(d.ended_epoch)-min(d.created_epoch) FROM chat_deliveries d WHERE d.account_id=r.account_id AND d.request_id=r.id) AS seconds,
                     (SELECT coalesce(sum(p.amount_microusd),0) FROM provider_receipts p WHERE p.account_id=r.account_id AND p.task_id=r.id) AS cost
              FROM customer_requests r WHERE r.state='completed' AND coalesce(r.outcome,'completed')='completed' AND r.created_epoch>=? AND ({where})"""
    args = [since] + args
    if account is not None:
        sql += ' AND r.account_id=?'
        args.append(account)
    rows = con.execute(sql + ' ORDER BY r.sequence DESC LIMIT ?', (*args, SAMPLE)).fetchall()
    return [(int(r['seconds']), int(r['cost'])) for r in rows if r['seconds'] is not None and r['seconds'] >= 0]


def estimate(con, account_id: str, kind: str, *, now=None) -> dict | None:
    """-> {'kind','based_on','scope','seconds':{'typical','upper'},'cost_microusd':{'typical','upper'}} or None when there is too little history to say."""
    if kind not in KINDS:
        raise ValueError('unknown task kind')
    since = int(now if now is not None else time.time()) - WINDOW_SECONDS
    history, scope = _history(con, kind, since, account_id), 'yours'
    if len(history) < MIN_OWN:
        history, scope = _history(con, kind, since), 'all'
        if len(history) < MIN_ALL:
            return None
    seconds, cost = sorted(h[0] for h in history), sorted(h[1] for h in history)
    return {'kind': kind, 'based_on': len(history), 'scope': scope,
            'seconds': {'typical': _percentile(seconds, 0.5), 'upper': _percentile(seconds, 0.9)},
            'cost_microusd': {'typical': _percentile(cost, 0.5), 'upper': _percentile(cost, 0.9)}}


def hit_rate(con, kind: str, *, now=None) -> dict | None:
    """How good the range is on recorded history: for each finished task (oldest first), was its real time within the upper bound computed from the tasks BEFORE it?"""
    since = int(now if now is not None else time.time()) - WINDOW_SECONDS
    history = list(reversed(_history(con, kind, since)))
    checked = within = 0
    for index in range(MIN_ALL, len(history)):
        upper = _percentile(sorted(h[0] for h in history[:index]), 0.9)
        checked += 1
        within += 1 if history[index][0] <= upper else 0
    return {'kind': kind, 'checked': checked, 'within_upper': within, 'rate': round(within / checked, 3)} if checked else None
