"""Phase 1 live proof (run on the server as the app user, app environment loaded). Real stack: web API, queue, workers, cells, model.

Uses the owner's own test account A and a disposable second account B WITH its own assistant cell (created here, removed at the end). Nothing here touches a real customer.
Costs real model money (a few dollars at most: `--budget` is the stop-loss, default 8 USD, checked before every paid case).

  python phase1_live.py [--budget 8] [--cases parallel,queue,kill-worker,kill-cell,rate-limit,large]

Root steps (restart a service, restart or remove a cell, change a limit in the model proxy) are asked for by creating /tmp/p1-act-<name>.request and are done by
deploy/phase1_root.sh, which must be running as root beside this script (`systemd-run --unit=p1root deploy/phase1_root.sh`).

Case status: PASS | FAIL | NOT_RUN (never averaged, never promoted). Results: /tmp/phase1-live.json
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
import uuid

sys.path.insert(0, '/opt/agentai-platform/current')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'accounts.settings')
import django  # noqa: E402
django.setup()
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.db import connection  # noqa: E402
from django.test import Client  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import p15_acceptance as p15  # noqa: E402  (its account helpers; importing it does not run its cases)

A = p15.A
B = 'p1b' + uuid.uuid4().hex[:29]
HOST = settings.ALLOWED_HOSTS[0]
RESULTS = []
SETTINGS_FILE = os.environ.get('AGENTAI_SIGNUP_SETTINGS_FILE', '/var/lib/agentai-platform/signup-settings.json')
CELLS_DOCKER = {'DOCKER_HOST': 'unix:///run/agentai-cells/docker.sock'}


def record(case, title, status, detail=''):
    RESULTS.append({'id': case, 'title': title, 'status': status, 'detail': str(detail)[:900]})
    print(f'{status:8} {case}  {title}' + (f'  -- {str(detail)[:200]}' if detail and status != 'PASS' else ''), flush=True)


def sql(q, args=()):
    with connection.cursor() as c:
        c.execute(q, args)
        return c.fetchall() if c.description else []


def scalar(q, args=()):
    rows = sql(q, args)
    return rows[0][0] if rows else None


def client(user):
    from accounts.models import Identity
    c = Client(HTTP_HOST=HOST, raise_request_exception=False)
    c.force_login(user)
    session = c.session
    session['epoch'] = Identity.objects.get(user=user).epoch
    session.save()
    return c


def call(c, method, path, body=None):
    if method == 'GET':
        return c.get(path, secure=True)
    return c.post(path, data=json.dumps(body or {}), content_type='application/json', secure=True)


def spend_since(since):
    """What the model route has billed in total since `since` (the stop-loss). Reads the receipts Lumina recorded."""
    return (scalar("SELECT coalesce(sum(amount_microusd),0) FROM provider_receipts WHERE observed_epoch>=?".replace('?', '%s'), [since]) or 0) / 1e6


# ------------------------------------------------------------------------------------------------------------- setup
def owner_user():
    from accounts.models import Identity
    return Identity.objects.get(account_id=A, role='customer').user


def make_b():
    """B: a customer with a trial allowance and its own assistant cell (the host creates it; the lifecycle worker builds it)."""
    from datetime import timedelta
    from django.utils import timezone
    from accounts.lifecycle import coordinator
    from accounts.models import Identity
    user = User(username='p1-' + uuid.uuid4().hex[:12], email='p1-live-b@invalid.test', is_active=True)
    user.set_unusable_password(); user.save()
    now = int(time.time())
    limits = {'period_start_epoch': now, 'period_microusd': 10 ** 12, 'daily_microusd': 10 ** 12, 'task_microusd': 10 ** 12, 'max_queued_tasks': 20}
    sql("INSERT INTO accounts(id,status) VALUES (%s,'active')", [B])
    Identity.objects.create(user=user, account_id=B, role='customer', verified=True)
    sql("INSERT INTO memberships VALUES (%s,%s,'customer','active')", [B, str(user.pk)])
    sql("INSERT INTO projects(account_id,id,name) VALUES (%s,%s,'B project')", [B, 'pb' + uuid.uuid4().hex[:30]])
    sql("INSERT INTO entitlements VALUES (%s,'p1-v1','p1','trial',%s,%s)", [B, json.dumps(limits), timezone.now() + timedelta(days=1)])
    coordinator().host_create(B, key='p1-live-' + B, target_profile='trial-unmeasured-v1')
    return user


def wait_for(fn, timeout, every=2.0):
    end = time.time() + timeout
    while time.time() < end:
        got = fn()
        if got:
            return got
        time.sleep(every)
    return None


def root_action(name, timeout=300):
    """Some steps need root (restart a service, restart a cell, change a limit in the model proxy). This process does not run as root: it asks and waits. The person running the proof does
    the step and creates the .done file; see the section at the top of this file."""
    open(f'/tmp/p1-act-{name}.request', 'w').write(str(int(time.time())))
    end = time.time() + timeout
    while time.time() < end:
        if os.path.exists(f'/tmp/p1-act-{name}.done'):
            return True
        time.sleep(0.5)
    return False


def cell_of(account):
    return (sql('SELECT l.observed_state,l.tenant_ref FROM lifecycle_cells l WHERE l.account_id=%s', [account]) or [[None, None]])[0]


CREATED = []      # (client, conversation id): every chat this proof makes is archived at the end, so it never fills the test account's chat limit


def new_conversation(c, user):
    project = call(c, 'GET', '/v1/projects').json()['projects'][0]['id']
    made = call(c, 'POST', '/v1/conversations', {'project_id': project})
    found = made.json().get('id') or made.json().get('conversation', {}).get('id')
    if not found:
        raise RuntimeError(f'could not make a conversation ({made.status_code}): the account is at its chat limit')
    CREATED.append((c, found))
    return found


def archive_created():
    for c, conversation in CREATED:
        try:
            call(c, 'POST', f'/v1/conversations/{conversation}/archive', {})
        except Exception:
            pass


def send(c, conversation, text, mode='text'):
    r = call(c, 'POST', f'/v1/conversations/{conversation}/send', {'message': text, 'key': uuid.uuid4().hex, 'mode': mode})
    body = r.json()
    request = body.get('request') or {}
    return request.get('id'), r.status_code


def request_row(request):
    rows = sql('SELECT state,outcome,claimed_epoch,created_epoch FROM customer_requests WHERE id=%s', [request])
    return rows[0] if rows else None


def done(request):
    row = request_row(request)
    return row and row[0] in ('completed', 'failed', 'cancelled')


class Sampler(threading.Thread):
    """Looks at the pools twice a second: how many requests and cells are running at the same moment, and for which accounts."""
    def __init__(self):
        super().__init__(daemon=True)
        self.stop, self.max_requests, self.max_cells, self.max_accounts, self.waiting_seen = False, 0, 0, 0, set()

    def run(self):
        from django.db import connection as con
        while not self.stop:
            try:
                running = sql('SELECT account_id FROM request_slots')
                cells = sql("SELECT account_id FROM cell_slots WHERE state='active'")
                self.max_requests = max(self.max_requests, len(running))
                self.max_cells = max(self.max_cells, len(cells))
                self.max_accounts = max(self.max_accounts, len({r[0] for r in running}))
                for (reason,) in sql("SELECT 1 FROM customer_requests WHERE state='waiting'"):
                    self.waiting_seen.add(reason)
            except Exception:
                pass
            time.sleep(0.5)
            con.close_if_unusable_or_obsolete()


# ------------------------------------------------------------------------------------------------------------- cases
def case_cell_b():
    ok = wait_for(lambda: cell_of(B)[0] in ('stopped', 'running'), 600, 5)
    record('P1-CELL-B', 'The disposable second account got its own assistant cell', 'PASS' if ok else 'FAIL', cell_of(B))
    return bool(ok)


def case_parallel(a_user, b_user, budget):
    set_ceiling(None)                                                                   # the host's live capacity decides, not a ceiling
    ca, cb = client(a_user), client(b_user)
    conv_a, conv_b = new_conversation(ca, a_user), new_conversation(cb, b_user)
    # B's cell is stopped (it has never been used): wake it with a first message and wait, so that the two tasks below start together on two cells that are both up.
    warm, _ = send(cb, conv_b, 'Reply with exactly the word: ready')
    wait_for(lambda: warm and done(warm), 900, 3)
    sampler = Sampler(); sampler.start()
    started = int(time.time())
    # Both customers ask at the same moment, each for something that takes a while, so that the two runs overlap for real.
    results = {}
    def go(name, c, conv):
        results[name] = send(c, conv, 'Write a 200-word story about ' + ('a lighthouse' if name == 'A' else 'a train station') + '. Do not use any tools.', 'text')
    threads = [threading.Thread(target=go, args=(n, c, v)) for n, c, v in (('A', ca, conv_a), ('B', cb, conv_b))]
    for t in threads: t.start()
    for t in threads: t.join(60)
    ids = {n: r[0] for n, r in results.items()}
    finished = wait_for(lambda: all(ids.get(n) and done(ids[n]) for n in ('A', 'B')), 900, 3)
    sampler.stop = True
    rows = {n: request_row(i) for n, i in ids.items() if i}
    states = {n: (r[0], r[1]) for n, r in rows.items()} if rows else {}
    both_ok = finished and all(s == ('completed', 'completed') for s in states.values())
    window = {n: (r[2], sql('SELECT max(updated_epoch) FROM chat_deliveries WHERE request_id=%s', [ids[n]])[0][0]) for n, r in rows.items()}
    overlap = None
    if len(window) == 2 and all(None not in w for w in window.values()):
        overlap = min(window['A'][1], window['B'][1]) - max(window['A'][0], window['B'][0])
    record('P1-PARALLEL', 'Two accounts run tasks at the same moment, each on its own cell, and both complete',
           'PASS' if both_ok and sampler.max_accounts >= 2 and sampler.max_cells >= 2 else 'FAIL',
           f'states={states} max_running_requests={sampler.max_requests} accounts={sampler.max_accounts} cells={sampler.max_cells} overlap_s={overlap}')
    receipts = {n: scalar('SELECT count(*) FROM provider_receipts WHERE task_id=%s', [i]) for n, i in ids.items() if i}
    settled = {n: scalar("SELECT state FROM task_reservations WHERE task_id=%s", [i]) for n, i in ids.items() if i}
    record('P1-PARALLEL-CHARGE', 'Each task is charged once, to its own account, and settled',
           'PASS' if all(v == 1 for v in receipts.values()) and all(v == 'settled' for v in settled.values()) else 'FAIL', f'receipts={receipts} reservations={settled}')
    cross = scalar("SELECT count(*) FROM customer_requests WHERE id=%s AND account_id=%s", [ids.get('B'), A])
    record('P1-PARALLEL-ISOLATION', 'Neither task appears under the other account', 'PASS' if not cross and call(ca, 'GET', f"/v1/requests/{ids.get('B')}").status_code == 404 else 'FAIL', '')
    return conv_a, conv_b


def set_ceiling(value):
    data = {}
    try:
        data = json.load(open(SETTINGS_FILE))
    except (OSError, ValueError):
        pass
    if value is None:
        data.pop('max_running_cells', None)
    else:
        data['max_running_cells'] = value
    tmp = SETTINGS_FILE + '.new'
    json.dump(data, open(tmp, 'w'))
    os.replace(tmp, SETTINGS_FILE)


def case_queue(a_user, b_user, conv_a, conv_b):
    """The host is made full on purpose (ceiling of one cell): the second request must WAIT, be told so, and still finish. Nothing may fail."""
    ca, cb = client(a_user), client(b_user)
    set_ceiling(1)
    try:
        # make B's cell the only one allowed: stop A's idle cell first so the ceiling is the thing being tested
        sql('SELECT 1')
        ids = {}
        ids['A'] = send(ca, conv_a, 'Reply with exactly: queue proof A')[0]
        ids['B'] = send(cb, conv_b, 'Reply with exactly: queue proof B')[0]
        seen_wait = wait_for(lambda: any((request_row(i) or [''])[0] == 'waiting' for i in ids.values()) or all(done(i) for i in ids.values()), 120, 1)
        views = {n: call({'A': ca, 'B': cb}[n], 'GET', f'/v1/requests/{i}').json() for n, i in ids.items()}
        waits = {n: v.get('wait') for n, v in views.items()}
        finished = wait_for(lambda: all(done(i) for i in ids.values()), 1500, 5)
        states = {n: (request_row(i) or [None, None])[0:2] for n, i in ids.items()}
        ok = finished and all(s[0] == 'completed' for s in states.values())
        record('P1-QUEUE', 'With the host full a second customer waits in line (and is told so) instead of failing, and finishes when room is made',
               'PASS' if ok else 'FAIL', f'states={states} wait_reasons_seen={waits}')
    finally:
        set_ceiling(None)


def case_kill_worker(b_user, conv_b):
    cb = client(b_user)
    request = send(cb, conv_b, 'Write a 400-word story about a lighthouse keeper. Take your time and do not use any tools.')[0]
    running = wait_for(lambda: (sql("SELECT 1 FROM chat_deliveries WHERE request_id=%s AND state='acknowledged'", [request]) or None), 300, 1)
    if not running:
        record('P1-KILL-WORKER', 'Killing the request worker mid-run recovers with one run and no lost work', 'FAIL', 'the run never started')
        return
    acted = root_action('kill-worker')
    finished = wait_for(lambda: done(request), 600, 3)
    runs = scalar('SELECT count(DISTINCT native_run_id) FROM chat_deliveries WHERE request_id=%s', [request])
    receipts = scalar('SELECT count(*) FROM provider_receipts WHERE task_id=%s', [request])
    replies = scalar("SELECT count(*) FROM chat_messages WHERE request_id=%s AND provenance='agent'", [request])
    state = request_row(request)
    ok = finished and state[0] == 'completed' and runs == 1 and receipts == 1 and replies >= 1
    record('P1-KILL-WORKER', 'Killing the request worker mid-run recovers with one run and no lost work', 'PASS' if ok else 'FAIL', f'state={state[:2] if state else None} runs={runs} receipts={receipts} replies={replies}')


def case_kill_cell(b_user, conv_b):
    cb = client(b_user)
    tenant = cell_of(B)[1]
    request = send(cb, conv_b, 'Write a 400-word story about a mountain village. Take your time and do not use any tools.')[0]
    running = wait_for(lambda: (sql("SELECT 1 FROM chat_deliveries WHERE request_id=%s AND state='acknowledged'", [request]) or None), 300, 1)
    if not running or not tenant:
        record('P1-KILL-CELL', 'Restarting the assistant cell mid-run recovers with one run and no lost work', 'FAIL', 'the run never started')
        return
    acted = root_action('kill-cell')
    finished = wait_for(lambda: done(request), 900, 3)
    runs = scalar('SELECT count(DISTINCT native_run_id) FROM chat_deliveries WHERE request_id=%s', [request])
    receipts = scalar('SELECT count(*) FROM provider_receipts WHERE task_id=%s', [request])
    replies = scalar("SELECT count(*) FROM chat_messages WHERE request_id=%s AND provenance='agent'", [request])
    state = request_row(request)
    ok = finished and state[0] == 'completed' and runs == 1 and receipts == 1 and replies >= 1
    record('P1-KILL-CELL', 'Restarting the assistant cell mid-run recovers with one run and no lost work', 'PASS' if ok else 'FAIL',
           f'acted={acted} state={state[:2] if state else None} runs={runs} receipts={receipts} replies={replies}')


def case_rate_limit(user, conv, account):
    """The test account's model key is limited to 2 requests a minute for the test (root step 'limit-on', restored afterwards): a task that needs several model calls must WAIT, say so, and
    finish (not fail on a 429)."""
    cb = client(user)
    open('/tmp/p1-limit-tenant', 'w').write(cell_of(account)[1] or '')
    if not root_action('limit-on'):
        record('P1-RATE-LIMIT', 'A busy provider is waited for, not turned into a failed task', 'NOT_RUN', 'the model proxy limit was not lowered')
        return
    try:
        time.sleep(75)                              # the model proxy caches a key's limits for about a minute: let the lowered limit be read before the task starts
        request = send(cb, conv, 'Use your tools: first list the files in your workspace, then create a file notes.txt with the word hello, then read it back, then tell me what it says.', 'auto')[0]
        finished = wait_for(lambda: done(request), 900, 3)
        state = request_row(request)
        said = scalar("SELECT count(*) FROM events WHERE task_id=%s AND public_payload LIKE '%%model provider%%'", [request])
        ok = finished and state[0] == 'completed' and state[1] == 'completed'
        record('P1-RATE-LIMIT', 'A busy provider is waited for, not turned into a failed task', 'PASS' if ok and said else 'FAIL', f'state={state[:2] if state else None} timeline_says_waiting={said}')
    finally:
        root_action('limit-off', 120)


def case_lanes(a_user, budget):
    """Independent phases of one plan run at the same time in lanes, under background slots, and every cent the key spent is charged to some phase once."""
    from accounts import wiring
    from agentai_platform.security import Principal
    ca = client(a_user)
    conv = new_conversation(ca, a_user)
    actor = sql("SELECT actor_id FROM memberships WHERE account_id=%s AND role='customer' AND status='active' LIMIT 1", [A])[0][0]
    principal = Principal(A, actor, 'customer')
    def phase(i, title, text, deps=()):
        return {'id': i, 'title': title, 'description': text, 'enabled': True, 'optional': False, 'requiresApproval': False, 'dependsOn': list(deps)}
    plan = {'schemaVersion': '1.0', 'type': 'task_plan', 'title': 'Two notes and a summary', 'phases': [
        phase('lighthouse', 'Lighthouse note', 'Write a 150-word note about lighthouses. Do not use any tools.'),
        phase('trains', 'Trains note', 'Write a 150-word note about trains. Do not use any tools.'),
        phase('summary', 'Summary', 'In two sentences, say what the two earlier notes have in common. Do not use any tools.', ('lighthouse', 'trains'))]}
    chat = wiring.chat_service()
    block = chat.blocks.create_plan(A, conv, plan, key='p1-lanes-' + uuid.uuid4().hex[:20])
    sampler = Sampler(); sampler.start()
    started = int(time.time())
    chat.launch_plan(principal, block['id'], block['version'])
    finished = wait_for(lambda: scalar("SELECT count(*) FROM plan_phase_runs WHERE block_id=%s AND state='completed'", [block['id']]) == 3, 900, 3)
    sampler.stop = True
    runs = {r[0]: r for r in sql("SELECT phase_id,state,started_epoch,finished_epoch,conversation_id,request_id FROM plan_phase_runs WHERE block_id=%s", [block['id']])}
    overlap = None
    if all(k in runs for k in ('lighthouse', 'trains')) and all(runs[k][2] and runs[k][3] for k in ('lighthouse', 'trains')):
        overlap = min(runs['lighthouse'][3], runs['trains'][3]) - max(runs['lighthouse'][2], runs['trains'][2])
    kinds = sorted(r[0] for r in sql('SELECT kind FROM request_slots'))
    lanes = scalar('SELECT count(*) FROM conversations WHERE account_id=%s AND parent_id IS NOT NULL', [A])
    ids = [r[5] for r in runs.values() if r[5]]
    receipts = {i: scalar('SELECT sum(amount_microusd) FROM provider_receipts WHERE task_id=%s', [i]) or 0 for i in ids}
    marks = sql("SELECT spend_microusd FROM spend_marks WHERE request_id IN (%s)" % ','.join(['%s'] * len(ids)), ids) if ids else []
    stretch = (max(m[0] for m in marks) - min(m[0] for m in marks)) if marks else None
    conserved = stretch is not None and abs(sum(receipts.values()) - stretch) <= max(3000, stretch * 0.02)
    ok = finished and sampler.max_requests >= 2 and bool(overlap and overlap > 0) and lanes >= 1 and conserved
    record('P1-LANES', 'Two independent phases of a plan run at the same moment in separate lanes and the plan completes', 'PASS' if ok else 'FAIL',
           f'states={ {k: v[1] for k, v in runs.items()} } max_running={sampler.max_requests} overlap_s={overlap} lanes={lanes} receipts={sum(receipts.values())} key_spend_stretch={stretch}')


LARGE_CASES = [
    ('report', 'Write a detailed 50-page report on the history of the bicycle as a Word document. Write it in many parts: create the file with the first section, then add the next section, part by part. Deliver it as docx when done.', 'docx'),
    ('app', 'Build a small multi-file web app: a to-do list with index.html, style.css and app.js (each at least 80 lines, with comments). Deliver the three files as a zip.', 'zip'),
    ('sheet', 'Make a spreadsheet of 2000 rows: columns id, name, city, amount. Generate it with a short script or in parts, and deliver it as xlsx.', 'xlsx'),
]


def case_large(a_user, budget, started, only=()):
    ca = client(a_user)
    for name, prompt, ext in LARGE_CASES:
        if only and name not in only:
            continue
        passes = 0
        for attempt in range(3):
            if spend_since(started) > budget:
                record('P1-LARGE-' + name.upper(), f'A large task ({name}) finishes three times in a row', 'NOT_RUN', f'budget ${budget} reached after {passes} passes')
                return
            conv = new_conversation(ca, a_user)
            request = send(ca, conv, prompt, 'auto')[0]
            CREATED.append((ca, conv)) if False else None
            finished = wait_for(lambda: done(request), 1500, 5)
            state = request_row(request)
            delivered = scalar("SELECT count(*) FROM events WHERE task_id=%s AND kind='artifact'", [request])
            cut = scalar("SELECT count(*) FROM events WHERE task_id=%s AND public_payload LIKE '%%length limit%%'", [request])
            if finished and state[0] == 'completed' and delivered:
                passes += 1
            else:
                record('P1-LARGE-' + name.upper(), f'A large task ({name}) finishes three times in a row', 'FAIL', f'attempt={attempt + 1} state={state[:2] if state else None} files={delivered} cutoff_notes={cut}')
                break
        else:
            record('P1-LARGE-' + name.upper(), f'A large task ({name}) finishes three times in a row', 'PASS', f'3 of 3, cost so far ${spend_since(started):.2f}')


def case_versions(b_user):
    row = sql("SELECT versions_json FROM customer_requests WHERE account_id=%s AND versions_json IS NOT NULL ORDER BY rowid DESC LIMIT 1", [B])
    last = json.loads(row[0][0]) if row else {}
    keys = {'release', 'rules', 'tools', 'runtime', 'model'}
    record('P1-VERSION-STAMP', 'Every request carries its version stamp (code, rules, tools, runtime, model)', 'PASS' if keys <= set(last) and all(last.get(k) for k in ('release', 'rules', 'runtime')) else 'FAIL', {k: str(v)[:12] for k, v in last.items()})
    missing = scalar("SELECT count(*) FROM customer_requests WHERE account_id IN (%s,%s) AND state IN ('completed','failed') AND versions_json IS NULL AND created_epoch>%s", [A, B, int(time.time()) - 7200])
    record('P1-VERSION-ALL', 'No request of the last two hours is without a stamp', 'PASS' if not missing else 'FAIL', f'without_stamp={missing}')


def cleanup(b_user):
    """Remove B completely. Stopping and deleting its cell, its volume, its model key and its host custody record needs root (root step 'cleanup-b', see phase1_root.sh); then B's rows
    (audit rows stay by design). A cell left behind would keep running and count against the host's running ceiling, so a failure to remove it is reported loudly."""
    tenant = cell_of(B)[1]
    if tenant:
        open('/tmp/p1-cleanup-tenant', 'w').write(tenant)
        if not root_action('cleanup-b', 120):
            print(f'WARNING: B cell {tenant} was NOT removed (the root step did not run): remove it by hand (docker rm -f, umount, rm volume, custody row, model key)', flush=True)
    sql('DELETE FROM cell_slots WHERE account_id=%s', [B])
    for table in ('lifecycle_details', 'operations', 'lifecycle_cells', 'deployments'):
        try:
            sql(f'DELETE FROM {table} WHERE account_id=%s', [B])
        except Exception:
            pass
    p15.cleanup_b(b_user, B)


def cleanup_leftovers():
    """Remove disposable accounts a crashed earlier run left behind (`--cleanup-only`)."""
    global B
    for (account,) in sql("SELECT id FROM accounts WHERE id LIKE 'p1b%'"):
        B = account
        users = list(User.objects.filter(email='p1-live-b@invalid.test'))
        cleanup(users[0] if users else None)
        for extra in users[1:]:
            extra.delete()
        print('cleaned', account, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cleanup-only', action='store_true')
    ap.add_argument('--large-only', default='', help='comma list of large cases to run (report, app, sheet); default all')
    ap.add_argument('--keep-on-failure', action='store_true', help='leave the disposable account in place when its cell could not be created (to diagnose)')
    ap.add_argument('--budget', type=float, default=8.0)
    ap.add_argument('--cases', default='parallel,queue,kill-worker,kill-cell,rate-limit,lanes,large')
    args = ap.parse_args()
    if args.cleanup_only:
        cleanup_leftovers()
        return
    wanted = set(args.cases.split(','))
    started = int(time.time())
    a_user = owner_user()
    if wanted <= {'large', 'lanes', 'rate-limit'}:                              # these cases use the owner's own test account only: no second account is made
        try:
            if 'rate-limit' in wanted:
                case_rate_limit(a_user, new_conversation(client(a_user), a_user), A)
            if 'lanes' in wanted:
                case_lanes(a_user, args.budget)
            if 'large' in wanted:
                case_large(a_user, args.budget, started, set(filter(None, args.large_only.split(','))))
            record('P1-COST', 'Total model spend of this run', 'PASS' if spend_since(started) <= args.budget + 1 else 'FAIL', f'${spend_since(started):.2f} (budget ${args.budget})')
        finally:
            archive_created()
            json.dump({'finished': int(time.time()), 'results': RESULTS}, open('/tmp/phase1-live-large.json', 'w'), indent=1)
            failed = [r for r in RESULTS if r['status'] != 'PASS']
            print(f'\n{len(RESULTS) - len(failed)} PASS, {len(failed)} not PASS', flush=True)
        sys.exit(1 if failed else 0)
    b_user = make_b()
    keep = False
    try:
        if not case_cell_b():
            keep = args.keep_on_failure
            return
        conv_a = conv_b = None
        if 'parallel' in wanted:
            conv_a, conv_b = case_parallel(a_user, b_user, args.budget)
        cb = client(b_user)
        conv_a = conv_a or new_conversation(client(a_user), a_user)
        conv_b = conv_b or new_conversation(cb, b_user)
        if 'queue' in wanted:
            case_queue(a_user, b_user, conv_a, conv_b)
        if 'kill-worker' in wanted:
            case_kill_worker(b_user, conv_b)
        if 'kill-cell' in wanted:
            case_kill_cell(b_user, conv_b)
        if 'rate-limit' in wanted:
            case_rate_limit(b_user, conv_b, B)
        case_versions(b_user)
        if 'large' in wanted:
            case_large(a_user, args.budget, started, set(filter(None, args.large_only.split(','))))
        record('P1-COST', 'Total model spend of this run', 'PASS' if spend_since(started) <= args.budget + 1 else 'FAIL', f'${spend_since(started):.2f} (budget ${args.budget})')
    finally:
        set_ceiling(None)
        archive_created()
        if not keep:
            cleanup(b_user)
        json.dump({'finished': int(time.time()), 'results': RESULTS}, open('/tmp/phase1-live.json', 'w'), indent=1)
        failed = [r for r in RESULTS if r['status'] != 'PASS']
        print(f'\n{len(RESULTS) - len(failed)} PASS, {len(failed)} not PASS', flush=True)
        sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
