"""What customers' tasks ran into, by feature (reliability plan, Part 1): `python3 -m agentai_platform.ops.cli reliability [--days 30] [--json]`.

One read-only pass over the application database. It answers, for a window of days: how did requests end, and for which reason; which tools failed how often;
how did browser jobs end; how did model calls go and how long did they take; how many requests met a cold start. The deploy's own acceptance probes are counted
apart, so they neither hide nor inflate what a person experienced.

Counts, reason codes, status numbers and durations only: no message, page, address, file name or account id is read into the report, so it can be pasted anywhere.
Every section is independent: a table an older database does not have yet yields an empty section, never an error.
"""
from __future__ import annotations
import json
import sqlite3
import time

BAD = ('failed', 'partial', 'blocked')
LIVE_BROWSER = ('queued', 'running', 'handoff', 'paused', 'asking')


def _has(con, table, column=None):
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is None:
        return False
    return column is None or any(c[1] == column for c in con.execute(f'PRAGMA table_info("{table}")'))


def _percentile(values, fraction):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    return values[min(len(values) - 1, int(round(fraction * (len(values) - 1))))]


def _requests(con, since):
    probe = 'probe' if _has(con, 'customer_requests', 'probe') else '0'
    out = {'people': {}, 'probes': {}}
    for is_probe, outcome, count in con.execute(f"""SELECT {probe}, coalesce(outcome, CASE WHEN state IN ('completed','failed','cancelled') THEN state ELSE 'running' END), count(*)
            FROM customer_requests WHERE created_epoch>=? GROUP BY 1,2""", (since,)):
        out['probes' if is_probe else 'people'][outcome] = count
    for side in out.values():
        side['total'] = sum(side.values())
        side['ended_badly'] = sum(side.get(o, 0) for o in BAD)
    return out


def _reasons(con, since):
    """Faults by reason, errors and expected stops apart, and how many bad endings of people's requests have no reason on record at all."""
    out = {'errors': [], 'expected_stops': [], 'unclassified': 0, 'bad_endings_without_a_reason': None}
    if not _has(con, 'faults'):
        return out
    for reason, kind, actor, expected, count, requests in con.execute("""SELECT reason,kind,actor,expected,count(*),count(DISTINCT request_id) FROM faults WHERE created_epoch>=?
            GROUP BY reason,kind,actor,expected ORDER BY count(*) DESC, reason""", (since,)):
        out['expected_stops' if expected else 'errors'].append({'reason': reason, 'kind': kind, 'actor': actor, 'count': count, 'requests': requests})
        if reason.endswith('.unclassified'):
            out['unclassified'] += count
    probe = 'AND r.probe=0' if _has(con, 'customer_requests', 'probe') else ''
    out['bad_endings_without_a_reason'] = con.execute(f"""SELECT count(*) FROM customer_requests r WHERE r.created_epoch>=? {probe} AND r.outcome IN ('failed','partial','blocked')
        AND NOT EXISTS (SELECT 1 FROM faults f WHERE f.account_id=r.account_id AND f.request_id=r.id)""", (since,)).fetchone()[0]
    return out


def _tools(con, since_iso):
    """Finished tool calls by tool, from the timeline: how many, and how many failed. The browser tool's own mirror of a call (source `router`) is the same call twice."""
    if not _has(con, 'events'):
        return []
    rows = {}
    for tool, status, count in con.execute("""SELECT json_extract(public_payload,'$.tool'), json_extract(public_payload,'$.status'), count(*) FROM events
            WHERE kind='activity' AND created_at>=? AND json_extract(public_payload,'$.status') IN ('done','failed')
            AND coalesce(json_extract(public_payload,'$.source'),'')<>'router' GROUP BY 1,2""", (since_iso,)):
        name = str(tool or 'unknown').replace('lumina__', '')
        if name.startswith('lumina_mcp_') and name not in ('lumina_mcp_call', 'lumina_mcp_discover', 'lumina_mcp_connections', 'lumina_mcp_setup'):
            name = 'lumina_mcp_(a connected tool)'            # a connected server's own tool names are the customer's: never listed
        entry = rows.setdefault(name, {'tool': name, 'finished': 0, 'failed': 0})
        entry['finished'] += count
        entry['failed'] += count if status == 'failed' else 0
    return sorted(rows.values(), key=lambda r: (-r['failed'], -r['finished'], r['tool']))


def _browser(con, since, now, settle=900):
    if not _has(con, 'browse_runs'):
        return {}
    by_state = {state: count for state, count in con.execute('SELECT status,count(*) FROM browse_runs WHERE created_epoch>=? GROUP BY 1', (since,))}
    marks = ','.join('?' * len(LIVE_BROWSER))
    stale = con.execute(f"""SELECT count(*) FROM browse_runs b JOIN customer_requests r ON r.account_id=b.account_id AND r.id=b.request_id
        WHERE b.status IN ({marks}) AND r.state IN ('completed','failed','cancelled') AND b.updated_epoch<?""", (*LIVE_BROWSER, now - settle)).fetchone()[0]
    return {'jobs': sum(by_state.values()), 'by_end_state': dict(sorted(by_state.items(), key=lambda kv: -kv[1])), 'still_running_after_their_task_ended': stale}


def _model_calls(con, since):
    if not _has(con, 'model_calls'):
        return {}
    rows = con.execute('SELECT route,status,code,waited_ms,answer_ms,total_ms,input_tokens,output_tokens,cached_tokens FROM model_calls WHERE created_epoch>=?', (since,)).fetchall()
    if not rows:
        return {'calls': 0}
    failed = {}
    for route, status, code, *_ in rows:
        if not 200 <= status < 300:
            key = f'{route} {status}' + (f' {code}' if code else '')
            failed[key] = failed.get(key, 0) + 1
    ok = [r for r in rows if 200 <= r[1] < 300]
    total = lambda index: sum(r[index] or 0 for r in rows)
    return {'calls': len(rows), 'failed': sum(failed.values()), 'failed_by_status': dict(sorted(failed.items(), key=lambda kv: -kv[1])),
            'seconds_until_the_answer_began': {'median': _seconds(_percentile([r[4] for r in ok], 0.5)), 'p90': _seconds(_percentile([r[4] for r in ok], 0.9))},
            'seconds_in_all': {'median': _seconds(_percentile([r[5] for r in ok], 0.5)), 'p90': _seconds(_percentile([r[5] for r in ok], 0.9))},
            'calls_that_waited_for_a_busy_provider': sum(1 for r in rows if r[3]), 'input_tokens': total(6), 'output_tokens': total(7), 'cached_input_tokens': total(8),
            'calls_with_token_counts': sum(1 for r in rows if r[6] is not None)}


def _seconds(ms):
    return None if ms is None else round(ms / 1000, 2)


def _starts(con, since, slow=60):
    """How long a person's request waited before the assistant had it (accepted to claimed). Over a minute means its workspace had to be woken first."""
    if not _has(con, 'customer_requests', 'claimed_epoch'):
        return {}
    probe = 'AND probe=0' if _has(con, 'customer_requests', 'probe') else ''
    waits = [r[0] for r in con.execute(f'SELECT claimed_epoch-created_epoch FROM customer_requests WHERE created_epoch>=? {probe} AND claimed_epoch IS NOT NULL', (since,))]
    return {'requests': len(waits), 'waited_over_a_minute': sum(1 for w in waits if w > slow), 'median_seconds': _percentile(waits, 0.5), 'p90_seconds': _percentile(waits, 0.9),
            'longest_seconds': max(waits) if waits else None}


def _changes(con, since):
    """Changes in connected services (the action pipeline): how they ended, and why the ones that failed did."""
    if not _has(con, 'actions'):
        return {}
    states = {state: count for state, count in con.execute('SELECT state,count(*) FROM actions WHERE created_epoch>=? GROUP BY 1', (since,))}
    why = {reason: count for reason, count in con.execute("SELECT coalesce(ended_reason,'unknown'),count(*) FROM actions WHERE created_epoch>=? AND state='failed' GROUP BY 1", (since,))}
    return {'changes': sum(states.values()), 'by_state': states, 'failed_by_reason': why}


def build(db_path, *, days=30, now=None) -> dict:
    now = int(now if now is not None else time.time())
    since = now - int(days * 86400)
    since_iso = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(since))
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=5)
    try:
        return {'days': days, 'until_epoch': now, 'requests': _requests(con, since), 'reasons': _reasons(con, since), 'tools': _tools(con, since_iso),
                'browser': _browser(con, since, now), 'model_calls': _model_calls(con, since), 'starts': _starts(con, since), 'connected_service_changes': _changes(con, since)}
    finally:
        con.close()


def _share(part, whole):
    return f'{part} of {whole}' + (f' ({100 * part / whole:.0f}%)' if whole else '')


def text(report) -> str:
    """The same report for a person to read in a terminal."""
    lines, people, probes = [], report['requests']['people'], report['requests']['probes']
    lines.append(f"Reliability, last {report['days']} days")
    lines.append('')
    lines.append(f"People's requests: {people['total']}. Ended badly: {_share(people['ended_badly'], people['total'])}"
                 f" (failed {people.get('failed', 0)}, partly done {people.get('partial', 0)}, blocked {people.get('blocked', 0)}); stopped by the customer {people.get('cancelled', 0)}.")
    lines.append(f"Acceptance probes: {probes['total']}, ended badly {probes['ended_badly']} (counted apart).")
    reasons = report['reasons']
    lines.append('')
    lines.append('Why (errors):')
    lines += [f"  {r['count']:4}  {r['reason']}  [{r['kind']}, acts: {r['actor']}]" for r in reasons['errors']] or ['  none on record']
    lines.append('Expected stops (not errors):')
    lines += [f"  {r['count']:4}  {r['reason']}" for r in reasons['expected_stops']] or ['  none on record']
    if reasons['bad_endings_without_a_reason'] is not None:
        lines.append(f"Unclassified: {reasons['unclassified']}. Bad endings with no reason on record: {reasons['bad_endings_without_a_reason']}.")
    lines.append('')
    lines.append('Tool calls (finished, failed):')
    lines += [f"  {t['finished']:4}  {t['failed']:4}  {t['tool']}" + (f"  ({100 * t['failed'] / t['finished']:.0f}%)" if t['failed'] else '') for t in report['tools']] or ['  none']
    browser = report['browser']
    if browser:
        lines.append('')
        lines.append(f"Browser jobs: {browser['jobs']}: " + ', '.join(f'{state} {count}' for state, count in browser['by_end_state'].items())
                     + f". Still marked running after their task ended: {browser['still_running_after_their_task_ended']}.")
    calls = report['model_calls']
    if calls.get('calls'):
        lines.append('')
        lines.append(f"Model calls: {calls['calls']}, failed {calls['failed']}" + (': ' + ', '.join(f'{k} x{v}' for k, v in calls['failed_by_status'].items()) if calls['failed'] else '') + '.')
        lines.append(f"  Answer began after {calls['seconds_until_the_answer_began']['median']} s (median), {calls['seconds_until_the_answer_began']['p90']} s (9 in 10); "
                     f"whole call {calls['seconds_in_all']['median']} s, {calls['seconds_in_all']['p90']} s. Waited for a busy provider: {calls['calls_that_waited_for_a_busy_provider']}.")
        lines.append(f"  Tokens in {calls['input_tokens']} (from cache {calls['cached_input_tokens']}), out {calls['output_tokens']}; reported by {calls['calls_with_token_counts']} of {calls['calls']} calls.")
    elif calls:
        lines += ['', 'Model calls: none recorded yet.']
    starts = report['starts']
    if starts.get('requests'):
        lines.append('')
        lines.append(f"Start: {_share(starts['waited_over_a_minute'], starts['requests'])} requests waited over a minute for their workspace; "
                     f"median {starts['median_seconds']} s, 9 in 10 within {starts['p90_seconds']} s, longest {starts['longest_seconds']} s.")
    changes = report['connected_service_changes']
    if changes.get('changes'):
        lines.append('')
        lines.append(f"Changes in connected services: {changes['changes']}, failed {changes['by_state'].get('failed', 0)}"
                     + (': ' + ', '.join(f'{k} x{v}' for k, v in changes['failed_by_reason'].items()) if changes['failed_by_reason'] else '') + '.')
    return '\n'.join(lines)


def main(db_path, *, days=30, as_json=False, now=None) -> str:
    report = build(db_path, days=days, now=now)
    return json.dumps(report, indent=2) if as_json else text(report)
