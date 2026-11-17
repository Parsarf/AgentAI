#!/usr/bin/env python3
"""Roadmap prompt 3 (Phase 4 knowledge, Phase 5 mail and calendar) exit gates on the live stack. Run it ON THE SERVER after the release is deployed:

    sudo systemd-run --wait --pipe --collect --property=User=agentai-platform --property=EnvironmentFile=/etc/agentai-platform/accounts.env \\
        --property=WorkingDirectory=/opt/agentai-platform/current /opt/agentai-platform/current/.venv/bin/python deploy/phase45_live.py

It needs the knowledge services installed (deploy/knowledge/install.sh, the render service with reader image 2), NOT the owner switches: `customer_knowledge` and
`customer_uploads` count as on INSIDE THIS PROCESS ONLY, for the two disposable accounts it makes. No customer sees anything, and the switch file is not touched. It reads
pages with no text with the vision model (a few cents) and makes the search vectors with the self-hosted embedding model.

  P4-EVAL       the evaluation set (agentai_platform/knowledge_eval.py) through the sealed reader, the embedding model and PostgreSQL
  P4-SCAN       a scanned page (a picture with no text) is read by the vision model, is searchable, and its passage opens its page
  P4-ISOLATION  another account finds nothing of it, cannot open a passage by id, and an organization share is taken back at once
  P4-REMOVE     removing a source removes its passages from the index at once
  P4-SCALE      a search over 1,000 documents answers in under one second
  P5-SYNC       the mail and calendar sync on this host, read only: what is copied, its size, the service's restarts and memory
  OFFBOARD      both disposable accounts are offboarded; nothing of them is left in the index

Results are printed one line per gate; the last line is JSON (numbers only: never a document's text beyond the evaluation questions).
"""
import json
import os
import statistics
import subprocess
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'accounts.settings')
import django  # noqa: E402
django.setup()
from django.contrib.auth.models import User  # noqa: E402
from django.db import connection  # noqa: E402

from accounts import wiring  # noqa: E402
from accounts.models import Identity  # noqa: E402
from agentai_platform import knowledge_eval as E  # noqa: E402
from agentai_platform.security import NotFound, Principal  # noqa: E402

RESULTS, MINE = [], set()
_real_switch = wiring.switch_on
wiring.switch_on = lambda name: name in ('customer_knowledge', 'customer_uploads') or _real_switch(name)     # this process only


def record(case, title, ok, detail=''):
    RESULTS.append({'id': case, 'title': title, 'passed': bool(ok), 'detail': detail if isinstance(detail, (dict, list)) else str(detail)[:600]})
    print(f"{'PASS' if ok else 'FAIL':5} {case}  {title}" + (f'  -- {json.dumps(detail) if isinstance(detail, (dict, list)) else detail}' if detail else ''), flush=True)


def sql(q, args=()):
    with connection.cursor() as c:
        c.execute(q, args)
        return c.fetchall() if c.description else []


def make_account(tag):
    account = uuid.uuid4().hex
    user = User(username=f'p45-{tag}-' + account[:10], email=f'p45-live-{account[:8]}@invalid.test', is_active=True)
    user.set_unusable_password(); user.save()
    sql("INSERT INTO accounts(id,status) VALUES (%s,'active')", [account])
    Identity.objects.create(user=user, account_id=account, role='customer', verified=True)
    sql("INSERT INTO memberships VALUES (%s,%s,'customer','active')", [account, str(user.pk)])
    sql("INSERT INTO projects(account_id,id,name) VALUES (%s,%s,'Phase 4-5 proof')", [account, 'p' + account[:30]])
    MINE.add(account)
    return Principal(account, str(user.pk), 'customer')


def upload(who, name, data):
    """A file stored the way an upload is stored (the file service's own storage and row), already scanned: these are documents this script wrote."""
    import hashlib
    fid = uuid.uuid4().hex
    wiring.file_store().write_private([who.account_id, 'files', fid], data)
    sql("""INSERT INTO project_files(account_id,project_id,id,display_name,media_type,size_bytes,sha256,storage_ref,state,created_at)
        VALUES (%s,%s,%s,%s,'application/octet-stream',%s,%s,%s,'scanned',datetime('now'))""",
        [who.account_id, 'p' + who.account_id[:30], fid, name, len(data), hashlib.sha256(data).hexdigest(), f'files/{fid}'])
    return fid


def work(service, until=900):
    """Read what was added (this process's accounts only), until nothing of theirs is queued."""
    deadline = time.monotonic() + until
    while time.monotonic() < deadline:
        service.work_once(enabled=lambda account: account in MINE, limit=5)
        left = sql("SELECT count(*) FROM knowledge_sources WHERE account_id IN (%s) AND state IN ('queued','working','removing')" % ','.join('%s' for _ in MINE), list(MINE))[0][0]
        if not left:
            return True
        time.sleep(1)
    return False


def main():
    service = wiring.knowledge_service()
    if service is None or service.reader is None:
        print('NOT RUN: the knowledge index, the embedding server or the render service is not installed on this host (deploy/PENDING_DEPLOY.md, Roadmap Phase 4).')
        print(json.dumps({'passed': False, 'not_run': True, 'cases': []}))
        return 2
    a, b = make_account('a'), make_account('b')
    try:
        # -- P4-EVAL -----------------------------------------------------------------------------------------------------------------------------------
        started = time.monotonic()
        report = E.run(service, a, lambda name, data: service.add(a, 'upload', upload(a, name, data))['id'], wait=lambda: work(service))
        report['read_seconds'] = round(time.monotonic() - started, 1)
        r = report['retrieval']
        ok = (not report['not_ready'] and r['recall_at_10'] >= TARGET['recall_at_10'] and r['recall_at_5'] >= TARGET['recall_at_5'] and r['citation_correct'] == 1.0
              and report['tables']['accuracy'] >= TARGET['table_cells'] and all(report['comparison'].values()) and report['conflicts']['reported'] == report['conflicts']['planted']
              and report['claims']['flagged'] == report['claims']['planted_unsupported'] and report['claims']['wrong'] == 0)
        record('P4-EVAL', 'The evaluation set passes with the sealed reader, the embedding model and PostgreSQL', ok, report)

        # -- P4-SCAN: a page that is only a picture ----------------------------------------------------------------------------------------------------
        page = ('<html><body style="font-family:serif;font-size:22px;margin:60px;transform:rotate(-1.5deg)"><h1>Equipment Rental Agreement (invented test document)</h1>'
                '<p>Section 7. Termination.</p><p>The renter may return the equipment and end this rental with fourteen days written notice.</p>'
                '<p>The deposit of 800 euros is refunded within ten days of the return.</p></body></html>')
        try:
            picture = wiring.renderer().convert('scan.html', 'png', {'scan.html': page.encode()}, preview=False).get('data')
        except Exception as error:
            picture = None; print('the render service could not make the test picture:', type(error).__name__)
        scanned = None
        if picture:
            scanned = service.add(a, 'upload', upload(a, 'rental-agreement-scan.png', picture))['id']
            work(service)
            hits = [h for h in service.search(a, 'how much notice to end the equipment rental', limit=5)['results'] if h['source_id'] == scanned]
            row = sql('SELECT state,model_pages,low_confidence FROM knowledge_sources WHERE account_id=%s AND id=%s', [a.account_id, scanned])[0]
            opened = service.document(a, scanned) if hits else {'passages': []}
            record('P4-SCAN', 'A scanned page is read by the vision model, is searchable, and its passage opens its page',
                   row[0] == 'ready' and row[1] >= 1 and bool(hits) and 'fourteen' in hits[0]['text'].lower() and any(p['id'] == hits[0]['passage_id'] for p in opened['passages']),
                   {'state': row[0], 'pages_read_by_model': row[1], 'flagged_unsure': bool(row[2]), 'found': bool(hits)})
        else:
            record('P4-SCAN', 'A scanned page is read by the vision model', False, 'the render service could not make the test picture')

        # -- P4-ISOLATION ------------------------------------------------------------------------------------------------------------------------------
        mine = service.search(a, 'monthly rent for the flat', limit=5)['results']
        theirs = service.search(b, 'monthly rent for the flat', limit=5)['results']
        try:
            service.passage(b, mine[0]['passage_id']); opened_by_other = True
        except NotFound:
            opened_by_other = False
        record('P4-ISOLATION', 'Another account finds nothing of it and cannot open one of its passages by id', bool(mine) and not theirs and not opened_by_other,
               {'own_results': len(mine), 'other_results': len(theirs), 'other_opened_by_id': opened_by_other})

        # -- P4-REMOVE ---------------------------------------------------------------------------------------------------------------------------------
        lease = next(s for s in service.sources(a)['sources'] if s['name'] == 'lease-agreement.pdf')
        before = service.index.count(a.account_id, lease['id'])
        service.remove(a, lease['id'])
        work(service, until=60)
        after = service.index.count(a.account_id, lease['id'])
        still = [h for h in service.search(a, 'monthly rent for the flat', limit=10)['results'] if h['source_id'] == lease['id']]
        record('P4-REMOVE', 'Removing a source removes its passages from the index at once, and search no longer returns them', before > 0 and after == 0 and not still,
               {'passages_before': before, 'after': after, 'still_found': len(still)})

        # -- P4-SCALE ----------------------------------------------------------------------------------------------------------------------------------
        record(*scale(service, b))

        # -- P5-SYNC -----------------------------------------------------------------------------------------------------------------------------------
        record(*sync_facts())
    finally:
        record(*offboard([a, b], service))
    failed = [r for r in RESULTS if not r['passed']]
    print(json.dumps({'passed': not failed, 'cases': RESULTS}), flush=True)
    return 1 if failed else 0


# The live targets, set from the first live measurement (2026-11-16, phase-04.md). The CI floors (stand-in embedder) are in tests/test_knowledge_eval.py.
TARGET = {'recall_at_10': 0.95, 'recall_at_5': 0.9, 'table_cells': 1.0}


def scale(service, who, n=1000):
    """1,000 documents of one account (each a short memo with its own facts), read through the service's own path: the reader is skipped only because each structure is
    known (it is written here), which is the path a document already read once takes. Then 30 searches, timed."""
    from agentai_platform.render.parse import Doc
    from agentai_platform.knowledge import PARSER
    import hashlib
    topics = ['budget', 'hiring', 'shipping', 'warranty', 'travel', 'security', 'pricing', 'training', 'support', 'office']
    started = time.monotonic()
    for i in range(n):
        topic = topics[i % len(topics)]
        doc = Doc('md'); doc.pages = 1; doc.title = f'Memo {i} about {topic}'
        doc.add('heading', f'Memo {i}: {topic} for team {i % 37}', page=1, level=1)
        doc.add('paragraph', f'The {topic} figure for team {i % 37} in month {i % 12 + 1} is {1000 + i * 7} euros, agreed by owner number {i}. '
                             f'Reference {hashlib.sha1(str(i).encode()).hexdigest()[:10]}.', page=1)
        structure = {**doc.out(), 'stats': {'model_pages': 0, 'cost_microusd': 0, 'unread_pages': 0}}
        data = f'scale memo {i}'.encode()
        service.index.keep_document(who.account_id, hashlib.sha256(data).hexdigest(), PARSER, structure, 1, int(time.time()))
        service.add(who, 'upload', upload(who, f'memo-{i:04d}.md', data))
    work(service, until=3600)
    indexed = sql("SELECT count(*) FROM knowledge_sources WHERE account_id=%s AND state='ready'", [who.account_id])[0][0]
    times = []
    for q in range(30):
        t = time.monotonic()
        service.search(who, f'{topics[q % len(topics)]} figure for team {q % 37}', limit=10)
        times.append((time.monotonic() - t) * 1000)
    out = {'documents': indexed, 'fill_seconds': round(time.monotonic() - started, 1), 'search_ms_median': round(statistics.median(times), 1),
           'search_ms_p90': round(sorted(times)[26], 1), 'search_ms_max': round(max(times), 1)}
    return 'P4-SCALE', f'A search over {n:,} documents answers in under one second', indexed >= n and max(times) < 1000, out


def sync_facts():
    """The mail and calendar copy on this host, read only. Sizes, counts and the service's state; nothing from a mailbox."""
    rows = sql("SELECT domain,count(*),sum(filled),sum(item_count) FROM hub_sync GROUP BY domain")
    messages = sql('SELECT count(*) FROM hub_messages')[0][0]
    events = sql('SELECT count(*) FROM hub_events')[0][0]
    bodies = sql('SELECT count(*) FROM hub_messages WHERE body_fetched_epoch IS NOT NULL')[0][0]
    size = os.path.getsize(connection.settings_dict['NAME'])
    def unit(prop):
        try:
            return subprocess.run(['systemctl', 'show', 'agentai-hub-sync.service', '-p', prop, '--value'], capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            return 'unknown'
    out = {'parts': {d: {'rows': n, 'filled': int(f or 0), 'items': int(i or 0)} for d, n, f, i in rows}, 'messages': messages, 'events': events, 'opened_bodies': bodies,
           'database_mb': round(size / 1048576, 1), 'service': unit('ActiveState'), 'restarts': unit('NRestarts'), 'memory_mb': round(int(unit('MemoryCurrent') or 0) / 1048576)
           if unit('MemoryCurrent').isdigit() else None}
    return 'P5-SYNC', 'The mail and calendar sync on this host (read only): what is copied, its size, the service', out['service'] == 'active', out


def offboard(people, service):
    jobs, done = wiring.account_jobs(), {}
    for who in people:
        jobs.start_offboarding_by_operator(who.account_id, 'phase45-live', cooling_off=0)
    for _ in range(60):
        jobs.tick()
        states = dict(sql("SELECT account_id,state FROM account_jobs WHERE kind='deletion' AND account_id IN (%s)" % ','.join('%s' for _ in people), [p.account_id for p in people]))
        if len(states) == len(people) and all(s in ('completed', 'failed') for s in states.values()):
            break
        time.sleep(2)
    left = sum(service.index.count(p.account_id) for p in people) if service is not None else 0
    return 'OFFBOARD', 'Both disposable accounts are offboarded and nothing of them is left in the index', all(s == 'completed' for s in states.values()) and left == 0, \
        {'states': list(states.values()), 'passages_left': left}


if __name__ == '__main__':
    sys.exit(main())
