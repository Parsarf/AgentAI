#!/usr/bin/env python3
"""Per-request server-side lifecycle boundaries from the platform database. Read-only (SQLite mode=ro); selects timestamps, ids, states and counts only. It never selects
message, reply, result or payload text.

  python3 latency_report.py /var/lib/agentai-platform/platform.sqlite3 [--last 30] [--json]

What each timestamp MEANS (all UTC, one host clock; audit/events/chat_messages are millisecond text, customer_requests.created_epoch is whole seconds):
  accepted    audit 'lifecycle.chat.send' (object_id = request id): written in the same transaction as the customer's message row, BEFORE ledger.admit and before the 202.
              No such row (telegram / panel-less intake) -> falls back to created_epoch, marked 'epoch' (1 s resolution). Never to 0.
  claimed     first audit 'lifecycle.request_claim' (object_id = request id): the worker took the global slot.
  prepared    first event 'task_started': after the cell/session checks (_begin), before the first delivery row is written.
  submitted   first event 'progress' with step='working': written right after the runtime acknowledged chat.send for attempt 1. Absent for goal/steer-only or retried runs.
  first_row   earliest chat_messages row, provenance='agent': when the WORKER COPIED a finished assistant row into the database. NOT the runtime's first token, NOT a browser render.
  last_row    latest such row.   rows = how many.  last_row_to_finished = lag from the last copied reply to the committed finish (final wait + mirror + close gate + commit).
  finished    last audit 'lifecycle.request_finish': state committed, slot freed.
A missing boundary is None / '-'. A span with a missing end is None, never 0. A negative span (clock or ordering problem) is reported as-is and flagged.

Steering: a message sent while a run is open is not a request of its own. It writes audit 'lifecycle.chat.steer' (object_id = the RUNNING request) and a customer message
under that request. Its reply is an agent row of the same request, so first_row/finished of that request describe the original message; `steers` lists each steer time and
`steer_to_next_row` is the gap from the steer to the next mirrored agent row after it.

Contention evidence (only what the database can show):
  slot_overlap   ids of other requests whose [claimed, finished] interval overlaps this request's [accepted, claimed] wait (they held request_slot). A parked request releases the
                 slot while parked, so this over-reports for parked runs.
  cell_ops       lifecycle start/stop operations created for the account inside the wait window (operations.created_at; queued time, not completion).
  Everything else (worker idle sleep, the oldest request waiting for an inactive cell, handover) is not observable from this table set and is left unattributed.
"""
import argparse
import json
import sqlite3
from datetime import datetime, timezone

FMT = '%Y-%m-%dT%H:%M:%S.%fZ'


def secs(text):
    return datetime.strptime(text, FMT).replace(tzinfo=timezone.utc).timestamp() if text else None


def gap(a, b):
    return None if a is None or b is None else round(b - a, 3)


def collect(con, last=30):
    con.row_factory = sqlite3.Row
    reqs = [dict(r) for r in con.execute('SELECT account_id,id,state,created_epoch FROM customer_requests ORDER BY sequence DESC LIMIT ?', (last,))]
    out = []

    def first(sql, *p):
        row = con.execute(sql, p).fetchone()
        return secs(row[0]) if row and row[0] else None

    for r in reqs:
        a, rid = r['account_id'], r['id']
        accepted = first("SELECT min(created_at) FROM audit_events WHERE account_id=? AND object_id=? AND action IN ('lifecycle.chat.send','lifecycle.chat.send.panel')", a, rid)
        src = 'audit'
        if accepted is None:
            accepted, src = float(r['created_epoch']), 'epoch'
        claimed = first("SELECT min(created_at) FROM audit_events WHERE account_id=? AND object_id=? AND action='lifecycle.request_claim'", a, rid)
        prepared = first("SELECT min(created_at) FROM events WHERE account_id=? AND task_id=? AND kind='task_started'", a, rid)
        submitted = first("SELECT min(created_at) FROM events WHERE account_id=? AND task_id=? AND kind='progress' AND json_extract(public_payload,'$.step')='working'", a, rid)
        first_row = first("SELECT min(created_at) FROM chat_messages WHERE account_id=? AND request_id=? AND provenance='agent'", a, rid)
        last_row = first("SELECT max(created_at) FROM chat_messages WHERE account_id=? AND request_id=? AND provenance='agent'", a, rid)
        rows = con.execute("SELECT count(*) FROM chat_messages WHERE account_id=? AND request_id=? AND provenance='agent'", (a, rid)).fetchone()[0]
        finished = first("SELECT max(created_at) FROM audit_events WHERE account_id=? AND object_id=? AND action='lifecycle.request_finish'", a, rid)
        steers = [x[0] for x in con.execute("SELECT created_at FROM audit_events WHERE account_id=? AND object_id=? AND action IN ('lifecycle.chat.steer','lifecycle.chat.steer.panel') ORDER BY created_at", (a, rid))]
        steer_gaps = []
        for s in steers:       # raw text compare: the stored format sorts chronologically
            nxt = first("SELECT min(created_at) FROM chat_messages WHERE account_id=? AND request_id=? AND provenance='agent' AND created_at > ?", a, rid, s)
            steer_gaps.append(gap(secs(s), nxt))
        raw = {}
        for name, sql in (('accepted', "SELECT min(created_at) FROM audit_events WHERE account_id=? AND object_id=? AND action IN ('lifecycle.chat.send','lifecycle.chat.send.panel')"),
                          ('claimed', "SELECT min(created_at) FROM audit_events WHERE account_id=? AND object_id=? AND action='lifecycle.request_claim'")):
            raw[name] = con.execute(sql, (a, rid)).fetchone()[0]
        row = {'request': rid, 'state': r['state'], 'accepted_src': src, 'rows': rows, 'steers': len(steers), 'steer_to_next_row': steer_gaps,
               'accepted_to_claimed': gap(accepted, claimed), 'claimed_to_prepared': gap(claimed, prepared), 'prepared_to_submitted': gap(prepared, submitted),
               'claimed_to_submitted': gap(claimed, submitted), 'accepted_to_submitted': gap(accepted, submitted), 'submitted_to_first_row': gap(submitted, first_row), 'claimed_to_first_row': gap(claimed, first_row),
               'first_row_to_finished': gap(first_row, finished), 'first_row_to_last_row': gap(first_row, last_row), 'last_row_to_finished': gap(last_row, finished), 'accepted_to_finished': gap(accepted, finished), 'claimed_to_finished': gap(claimed, finished),
               '_t': {'accepted': accepted, 'claimed': claimed, 'finished': finished, 'last_row': last_row}, '_raw': raw, 'account': a}
        row['flags'] = [k for k, v in row.items() if k.endswith(('claimed', 'prepared', 'submitted', 'first_row', 'finished')) and isinstance(v, float) and v < 0]
        out.append(row)
    for row in out:        # contention evidence from the other requests in this window
        t = row['_t']
        if t['accepted'] is not None and t['claimed'] is not None:
            row['slot_overlap'] = [o['request'][:8] for o in out if o is not row and o['_t']['claimed'] is not None and o['_t']['claimed'] < t['claimed']
                                   and (o['_t']['finished'] is None or o['_t']['finished'] > t['accepted'])]
            ops = None
            if row['_raw'].get('accepted') and row['_raw'].get('claimed'):
                try:
                    ops = [x[0] for x in con.execute("SELECT kind FROM operations WHERE account_id=? AND kind IN ('start','stop') AND created_at BETWEEN ? AND ?", (row['account'], row['_raw']['accepted'], row['_raw']['claimed']))]
                except sqlite3.Error:
                    ops = None
            row['cell_ops'] = ops
        else:
            row['slot_overlap'], row['cell_ops'] = None, None
    return out


def show(v):
    return '-' if v is None else f'{v:.2f}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('db')
    ap.add_argument('--last', type=int, default=30)
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()
    con = sqlite3.connect(f'file:{args.db}?mode=ro', uri=True)
    rows = collect(con, args.last)
    if args.json:
        print(json.dumps([{k: v for k, v in r.items() if k not in ('_t', '_raw', 'account')} for r in rows], indent=1))
        return
    print('seconds; "-" = boundary not recorded (never zero).  acc->clm = accepted->claimed; clm->sub = claimed->submitted(ack event); sub->row = submitted->first mirrored row')
    print('request    state      src    acc->clm clm->prep prep->sub sub->row row->fin lst->fin acc->fin rows steers overlap cell_ops flags')
    for r in rows:
        print(f"{r['request'][:10]:<10} {r['state']:<10} {r['accepted_src']:<6} {show(r['accepted_to_claimed']):>8} {show(r['claimed_to_prepared']):>8} {show(r['prepared_to_submitted']):>8} "
              f"{show(r['submitted_to_first_row']):>8} {show(r['first_row_to_finished']):>7} {show(r['last_row_to_finished']):>7} {show(r['accepted_to_finished']):>7} {r['rows']:>4} {r['steers']:>6} "
              f"{('-' if r['slot_overlap'] is None else len(r['slot_overlap'])):>7} {('-' if r['cell_ops'] is None else ','.join(r['cell_ops']) or 'none'):>8} {','.join(r['flags'])}")


if __name__ == '__main__':
    main()
