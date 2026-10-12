"""Offline-safe classification benchmark over the labeled fixtures.

Measures how well JEV's route/risk recommendations agree with the fixture labels and whether deterministic policy
keeps consequential and injected requests off the lightweight routes. It does NOT measure cost per successful task
(that needs full executions on every route) and makes no savings claim.

  python3 -m agentai_platform.routing.bench --key-file KEY --out report.json     (live: ~110 calls, a few cents at most)
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import time

from . import config as rc
from .classifier import ClassifierUnavailable, classify, estimate_cost_microusd
from .decision import Rejected
from .policy import evaluate

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'tasks.json'
LIGHT = ('deterministic', 'jev_executor')


def percentile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(p / 100 * len(ordered)) - 1)]


def run(cfg, key, *, transport, tasks=None, pause=0.0):
    tasks = tasks or json.loads(FIXTURES.read_text())['tasks']
    rows, cost, lat = [], 0, []
    for task in tasks:
        row = {'id': task['id'], 'category': task['category']}
        try:
            decision, ms = classify(task['text'], cfg, key, transport=transport)
        except (ClassifierUnavailable, Rejected) as exc:
            row.update(status=type(exc).__name__)
            rows.append(row)
            continue
        outcome = evaluate(decision, task['text'], cfg)
        cost += estimate_cost_microusd(decision, cfg)
        lat.append(ms)
        row.update(status='ok', jev_route=decision.route, confidence=round(decision.route_confidence, 3), risk=decision.risk,
                   route_ok=decision.route in task['acceptable_routes'], risk_ok=(decision.risk == 'high') == (task['expected_risk'] == 'high'),
                   policy_route=outcome.route, policy_action=outcome.action, approval_flagged=outcome.requires_approval,
                   approval_expected=task['approval'], lightweight_after_policy=outcome.route in LIGHT)
        rows.append(row)
        if pause:
            time.sleep(pause)
    ok = [r for r in rows if r['status'] == 'ok']
    def rate(sel, pred):
        return round(100.0 * sum(1 for r in sel if pred(r)) / len(sel), 1) if sel else None
    by_cat = {}
    for r in ok:
        by_cat.setdefault(r['category'], []).append(r)
    needs = [r for r in ok if r['approval_expected']]
    plain = [r for r in ok if not r['approval_expected']]
    injected = by_cat.get('injection', [])
    return {
        'tasks': len(rows), 'answered': len(ok), 'failed': len(rows) - len(ok),
        'route_agreement_percent': rate(ok, lambda r: r['route_ok']),
        'route_agreement_by_category': {k: rate(v, lambda r: r['route_ok']) for k, v in sorted(by_cat.items())},
        'risk_agreement_percent': rate(ok, lambda r: r['risk_ok']),
        'approval_recall_percent': rate(needs, lambda r: r['approval_flagged']),
        'approval_false_alarm_percent': rate(plain, lambda r: r['approval_flagged']),
        'consequential_on_lightweight_route': sum(1 for r in needs if r['lightweight_after_policy']),
        'injection_on_lightweight_route': sum(1 for r in injected if r['lightweight_after_policy']),
        'would_use_lightweight_percent': rate(ok, lambda r: r['lightweight_after_policy']),
        'confidence_mean': round(sum(r['confidence'] for r in ok) / len(ok), 3) if ok else None,
        'latency_ms_p50': percentile(lat, 50), 'latency_ms_p95': percentile(lat, 95),
        'classifier_cost_usd_estimated': round(cost / 1e6, 6), 'price_version': cfg['pricing']['version'],
        'not_measured': ['cost per successful task', 'verified completion rate by route', 'savings versus Claude-first'],
        'rows': rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--key-file', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    cfg = rc.validate(rc._merge(rc.DEFAULTS, {'enabled': True, 'deadline_s': 15,
                                                'routes': {'deterministic': True, 'jev_executor': True, 'claude': True, 'specialist_worker': True, 'codex': True}}))
    from .classifier import http_post
    result = run(cfg, Path(args.key_file).read_text().strip(), transport=http_post)
    Path(args.out).write_text(json.dumps(result, indent=1))
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}, indent=1))


if __name__ == '__main__':
    main()
