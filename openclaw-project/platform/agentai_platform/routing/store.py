"""Persistence and reporting for routing decisions (append-only per request; outcome filled in later)."""
from __future__ import annotations
import json
import time

from .classifier import estimate_cost_microusd


class RouteLog:
    def __init__(self, store, clock=time.time):
        self.store, self.clock = store, clock

    def record(self, account_id, request_id, cfg, *, status, decision=None, outcome=None, latency_ms=None,
               actual_route='claude'):
        row = (account_id, request_id, cfg['mode'], status,
               decision.route if decision else None, decision.route_confidence if decision else None,
               decision.risk if decision else None, decision.complexity if decision else None,
               outcome.route if outcome else None, outcome.action if outcome else None,
               int(outcome.requires_approval) if outcome else None, json.dumps(list(outcome.reasons)) if outcome else None,
               actual_route, latency_ms,
               decision.input_tokens if decision else None, decision.output_tokens if decision else None,
               estimate_cost_microusd(decision, cfg) if decision else None, cfg['pricing']['version'], int(self.clock()))
        with self.store.connect() as con:
            con.execute('''INSERT OR IGNORE INTO route_decisions(account_id,request_id,mode,status,jev_route,route_confidence,risk,
                complexity,policy_route,policy_action,requires_approval,reasons,actual_route,latency_ms,input_tokens,output_tokens,
                est_cost_microusd,price_version,created_epoch) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', row)

    def finish(self, account_id, request_id, *, outcome, task_cost_microusd, task_seconds):
        with self.store.connect() as con:
            con.execute('UPDATE route_decisions SET outcome=?,task_cost_microusd=?,task_seconds=? WHERE account_id=? AND request_id=?',
                        (outcome, task_cost_microusd, task_seconds, account_id, request_id))


def report(store, since_epoch=0):
    """Counts and averages only (owner view). No request text is stored, so none can be reported."""
    with store.connect() as con:
        rows = con.execute('SELECT * FROM route_decisions WHERE created_epoch>=?', (since_epoch,)).fetchall()
    total = len(rows)
    classified = [r for r in rows if r['status'] == 'classified']

    def pct(n, d):
        return round(100.0 * n / d, 1) if d else None
    by_route = {}
    for r in classified:
        by_route.setdefault(r['jev_route'], []).append(r)
    done = [r for r in rows if r['outcome']]
    cost = [r['task_cost_microusd'] for r in done if r['task_cost_microusd'] is not None]
    secs = [r['task_seconds'] for r in done if r['task_seconds'] is not None]
    buckets = {'<0.65': 0, '0.65-0.85': 0, '>=0.85': 0}
    for r in classified:
        c = r['route_confidence']
        buckets['<0.65' if c < 0.65 else '0.65-0.85' if c < 0.85 else '>=0.85'] += 1
    lightweight = sum(1 for r in classified if r['policy_route'] in ('deterministic', 'jev_executor'))
    return {
        'total_routed': total, 'classified': len(classified),
        'unavailable_or_rejected': total - len(classified),
        'jev_selected_percent': pct(lightweight, len(classified)),
        'claude_escalation_percent': pct(sum(1 for r in classified if r['policy_action'] == 'escalate'), len(classified)),
        'would_change_route_percent': pct(sum(1 for r in classified if r['policy_route'] != r['actual_route']), len(classified)),
        'by_recommended_route': {k: len(v) for k, v in sorted(by_route.items())},
        'success_percent': pct(sum(1 for r in done if r['outcome'] == 'completed'), len(done)),
        'failed_count': sum(1 for r in done if r['outcome'] == 'failed'),
        'avg_task_cost_usd': round(sum(cost) / len(cost) / 1e6, 5) if cost else None,
        'avg_task_seconds': round(sum(secs) / len(secs), 1) if secs else None,
        'avg_classifier_latency_ms': round(sum(r['latency_ms'] for r in classified) / len(classified)) if classified else None,
        'confidence_distribution': buckets,
        'classifier_cost_usd_estimated': round(sum(r['est_cost_microusd'] or 0 for r in rows) / 1e6, 6),
        'estimated_monthly_savings_usd': None,   # not computed until the benchmark measures real savings
    }
