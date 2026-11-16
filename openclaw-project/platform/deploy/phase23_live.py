#!/usr/bin/env python3
"""The Phase 2 and Phase 3 exit gates, on the live stack (roadmap prompt 2). Run it ON THE SERVER after the release that contains Phase 2-3 is deployed.

    sudo systemd-run --wait --pipe --collect --property=User=agentai-platform --property=EnvironmentFile=/etc/agentai-platform/accounts.env \\
        --property=WorkingDirectory=/opt/agentai-platform/current /opt/agentai-platform/current/.venv/bin/python deploy/phase23_live.py [--hour]

Before running: turn the owner switches `synthetic_connector` and `connector_writes` ON (the first is test-only), and install the connector key file
(deploy/PENDING_DEPLOY.md). Turn `synthetic_connector` OFF again afterwards. The script refuses to start, and says what is missing, when they are not in place.

It makes ONE disposable account (no assistant cell: nothing here needs a model), proves each gate with the synthetic connector, and ends by offboarding that account, so
nothing of it remains but the tombstone the deletion leaves by design. It touches no other account. It costs nothing (no model call). Results are printed, one line per
gate, and the last line is JSON.

  P2-ROLES         the owner's own account is an organization of one whose owner they are; a viewer's task is refused
  P2-SWEEPER       the retention sweeper and the account-jobs timers are installed and enabled
  P3-WRITE-CYCLE   preview, approval, execute once under a forced lost answer, verify, undo
  P3-COMPENSATION  a failure after a step that cannot be undone offers (and runs) the registered follow-up
  P3-WORKFLOW      a three-step workflow that fails at step three leaves steps one and two reversed
  P3-HANDOFF       an approval answered later resumes from its checkpoint (`--hour` really waits an hour; without it the wait is a few seconds and the result says so)
  P3-PARTIAL       a partial result is stated as partial
  P2-OFFBOARD      the disposable account is offboarded and the verification scan finds nothing but what stays by design
"""
import json
import os
import subprocess
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))      # the release this script is part of: the live one, or the one about to go live
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'accounts.settings')
import django  # noqa: E402
django.setup()
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.db import connection  # noqa: E402
from django.test import Client  # noqa: E402

from accounts import wiring  # noqa: E402
from accounts.models import Identity  # noqa: E402
from agentai_platform.security import Principal  # noqa: E402
from agentai_platform.synthetic_connector import SyntheticBench  # noqa: E402

RESULTS = []
C = uuid.uuid4().hex                      # the disposable account
HOUR = '--hour' in sys.argv
# `--copy`: this is the deploy program proving a release against a COPY of the database before anything goes live (deploy/release.py). Nobody can turn a switch on for a
# copy, so the two test switches count as on inside this process only. Nothing here reaches the live database or the live switch file.
COPY = '--copy' in sys.argv
if COPY:
    _real_switch = wiring.switch_on
    wiring.switch_on = lambda name: name in ('synthetic_connector', 'connector_writes') or _real_switch(name)


def record(case, title, ok, detail=''):
    RESULTS.append({'id': case, 'title': title, 'passed': bool(ok), 'detail': str(detail)[:300]})
    print(f"{'PASS' if ok else 'FAIL':5} {case}  {title}" + (f'  -- {detail}' if detail else ''), flush=True)


def sql(q, args=()):
    with connection.cursor() as c:
        c.execute(q, args)
        return c.fetchall() if c.description else []


def client(user):
    c = Client(HTTP_HOST=settings.ALLOWED_HOSTS[0], raise_request_exception=False)
    c.force_login(user)
    session = c.session
    session['epoch'] = Identity.objects.get(user=user).epoch
    session.save()
    return c


def post(c, path, body=None):
    return c.post(path, data=json.dumps(body or {}), content_type='application/json', secure=True)


def make_account():
    """A customer with no assistant cell: a project, a chat and one finished task for the changes to belong to."""
    user = User(username='p23-' + C[:12], email=f'p23-live-{C[:8]}@invalid.test', is_active=True)
    user.set_unusable_password(); user.save()
    sql("INSERT INTO accounts(id,status) VALUES (%s,'active')", [C])
    Identity.objects.create(user=user, account_id=C, role='customer', verified=True)
    sql("INSERT INTO memberships VALUES (%s,%s,'customer','active')", [C, str(user.pk)])
    sql("INSERT INTO deployments(account_id,id,generation,state) VALUES (%s,%s,1,'stopped')", [C, 'dep' + C[:20]])
    # A plan allowance, as every real customer has: without one the follow-up turn that resumes a chat is refused at admission (rightly), and the handoff gate cannot be seen.
    from datetime import timedelta
    from django.utils import timezone
    now = int(time.time())
    limits = {'period_start_epoch': now, 'period_microusd': 10 ** 12, 'daily_microusd': 10 ** 12, 'task_microusd': 10 ** 12, 'max_queued_tasks': 20}
    sql("INSERT INTO entitlements VALUES (%s,'p23-v1','p23','trial',%s,%s)", [C, json.dumps(limits), timezone.now() + timedelta(days=1)])
    sql("INSERT INTO projects(account_id,id,name) VALUES (%s,%s,'Phase 2-3 proof')", [C, 'p' + C[:30]])
    sql("INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES (%s,%s,%s,%s)", [C, 'p' + C[:30], 'c' + C[:30], 'dep' + C[:20]])
    sql('''INSERT INTO customer_requests(account_id,id,actor_id,project_id,conversation_id,idempotency_key,payload_hash,message,state,created_epoch)
        VALUES (%s,%s,%s,%s,%s,%s,'h','phase 2-3 live proof','completed',%s)''', [C, 'r' + C[:31], str(user.pk), 'p' + C[:30], 'c' + C[:30], 'k' + C[:20], int(time.time())])
    sql("INSERT INTO chat_messages(account_id,conversation_id,request_id,provenance,content) VALUES (%s,%s,%s,'customer','phase 2-3 live proof')", [C, 'c' + C[:30], 'r' + C[:31]])
    return user


def main():
    missing = [name for name in ('synthetic_connector', 'connector_writes') if not wiring.switch_on(name)]
    if missing or type(wiring.connector_custody()).__name__ == 'DisabledCustody':
        print('NOT RUN: ' + ('turn on the owner switch(es) ' + ', '.join(missing) + '. ' if missing else '') +
              ('Install the connector key file (AGENTAI_CONNECTOR_KEY_FILE, see deploy/PENDING_DEPLOY.md).' if type(wiring.connector_custody()).__name__ == 'DisabledCustody' else ''))
        print(json.dumps({'passed': False, 'not_run': True, 'cases': []}))
        return 2
    user = make_account()
    web = client(user)
    who = Principal(C, str(user.pk), 'customer')
    request_id = 'r' + C[:31]
    connectors, cl, actions, workflows = wiring.action_services()
    runner = wiring.action_runner()
    bench = SyntheticBench(wiring.store())
    try:
        # -- P2-ROLES ----------------------------------------------------------------------------------------------------------------------
        view = web.get('/v1/organization', secure=True).json().get('organization', {})
        sql("UPDATE organization_members SET role='viewer' WHERE account_id=%s", [C])
        refused = post(web, f'/v1/conversations/c{C[:30]}/send', {'message': 'should be refused', 'key': 'p23-viewer'})
        sql("UPDATE organization_members SET role='owner' WHERE account_id=%s", [C])
        record('P2-ROLES', 'An account is an organization of one whose owner they are; a viewer cannot run a task',
               view.get('your_role') == 'owner' and refused.status_code == 403 and refused.json().get('needs') == 'task.run', f"role={view.get('your_role')} viewer_send={refused.status_code}")

        # -- P2-SWEEPER --------------------------------------------------------------------------------------------------------------------
        timers = {}
        for name in ('agentai-retention.timer', 'agentai-account-jobs.timer', 'agentai-connector-refresh.timer'):
            try:
                timers[name] = subprocess.run(['systemctl', 'is-enabled', name], capture_output=True, text=True, timeout=10).stdout.strip()
            except Exception:
                timers[name] = 'unknown'
        record('P2-SWEEPER', 'The retention sweeper, the account-jobs timer and the connector refresh are installed and enabled', all(v == 'enabled' for v in timers.values()), json.dumps(timers))

        # -- connect the synthetic service: one folder for writing, one for reading ------------------------------------------------------------------------------
        made = post(web, '/v1/integrations/synthetic/connect')
        connection_id = made.json()['connection']['id']
        post(web, f'/v1/integrations/{connection_id}/grants', {'grants': [{'kind': 'folder', 'id': 'inbox', 'access': 'write'}, {'kind': 'folder', 'id': 'projects', 'access': 'read'}]})

        # -- P3-WRITE-CYCLE ----------------------------------------------------------------------------------------------------------------
        action = actions.propose(who, connection_id, 'note.create', {'folder': 'inbox', 'title': 'Live proof', 'body': 'One'}, request_id=request_id)
        nothing_yet = not bench.rows(C)
        post(web, f'/v1/actions/{action["id"]}/approve', {'payload_hash': action['payload_hash']})
        bench.fault(C, 'write', 'silent')                                     # the write happens and its answer is lost: a forced retry situation
        for _ in range(4):
            runner.tick()
        done = actions.get(who, action['id'])
        notes = [r for r in bench.rows(C) if r['kind'] == 'note']
        undo = post(web, f'/v1/actions/{action["id"]}/undo').json().get('action', {})
        post(web, f'/v1/actions/{undo.get("id")}/approve', {'payload_hash': undo.get('payload_hash')})
        runner.tick()
        record('P3-WRITE-CYCLE', 'Preview, approval, execute once under a forced lost answer, verify, undo',
               nothing_yet and done['state'] == 'done' and done['verified'] is True and len(notes) == 1 and actions.get(who, action['id'])['state'] == 'undone' and bench.rows(C)[0]['deleted'] == 1,
               f"state={done['state']} verified={done['verified']} records={len(notes)} after_undo={actions.get(who, action['id'])['state']}")

        # -- P3-COMPENSATION and P3-WORKFLOW -------------------------------------------------------------------------------------------------
        bench.seed(C, 'inbox', 1, prefix='Existing')
        send = {'connection_id': connection_id, 'kind': 'message.send', 'payload': {'folder': 'inbox', 'to': 'proof@invalid.test', 'text': 'It is done'}}
        wrong = {'connection_id': connection_id, 'kind': 'message.correction', 'payload': {'folder': 'inbox', 'to': 'proof@invalid.test', 'text': 'Second'}}
        flow = workflows.propose(who, 'Proof: fails after a step that cannot be undone', [{'connection_id': connection_id, 'kind': 'note.create', 'payload': {'folder': 'inbox', 'title': 'W1', 'body': ''}}, send, wrong], request_id=request_id)
        post(web, f'/v1/workflows/{flow["id"]}/approve', {'steps_hash': flow['steps_hash']})
        for step in flow['steps'][:2]:                                        # run the first two, then make the third fail at the provider
            actions.approve_internal(C, step['id']); actions.execute(C, step['id'])
        bench.fault(C, 'write', 'forbidden')
        sql("UPDATE workflows SET state='running' WHERE id=%s", [flow['id']])
        runner.tick()
        report = workflows.get(who, flow['id'])
        sent = [r['body'] for r in bench.rows(C) if r['kind'] == 'message']
        record('P3-COMPENSATION', 'A failure after a step that cannot be undone runs its registered follow-up',
               [(r['step'], r['how']) for r in (report['report'] or {}).get('reversed', [])] == [(2, 'compensated'), (1, 'undone')] and 'Please disregard my previous message. It was sent in error.' in sent,
               json.dumps((report['report'] or {}).get('reversed')))
        three = [{'connection_id': connection_id, 'kind': 'note.create', 'payload': {'folder': 'inbox', 'title': t, 'body': ''}} for t in ('S1', 'S2')]
        three.append({'connection_id': connection_id, 'kind': 'note.update', 'payload': {'id': 'inbox-0000', 'body': 'changed by the workflow'}})
        flow = workflows.propose(who, 'Proof: three steps, the third fails', three, request_id=request_id)
        post(web, f'/v1/workflows/{flow["id"]}/approve', {'steps_hash': flow['steps_hash']})
        bench.edit_elsewhere(C, 'inbox-0000', body='changed by someone else')  # the third step will meet a conflict
        runner.tick()
        after = workflows.get(who, flow['id'])
        live = [r['title'] for r in bench.rows(C) if r['title'] in ('S1', 'S2') and not r['deleted']]
        record('P3-WORKFLOW', 'A three-step workflow that fails at step three leaves steps one and two reversed',
               after['state'] == 'reversed' and [r['step'] for r in after['report']['reversed']] == [2, 1] and not live, f"state={after['state']} still_live={live}")

        # -- P3-HANDOFF --------------------------------------------------------------------------------------------------------------------
        # This account has no assistant cell, so the follow-up turns the gates above queued can never run. They are cancelled here so the account's waiting-task limit
        # does not stand in the way of the one this gate looks for. (For a real customer they simply run.)
        sql("UPDATE customer_requests SET state='cancelled',cancel_requested=1 WHERE account_id=%s AND state='waiting'", [C])
        sql("UPDATE tasks SET state='cancelled' WHERE account_id=%s AND state='queued'", [C])
        waiting = actions.propose(who, connection_id, 'note.create', {'folder': 'inbox', 'title': 'After the wait', 'body': ''}, request_id=request_id)
        held = sql('SELECT count(*) FROM request_slots WHERE account_id=%s', [C])[0][0]
        time.sleep(3600 if HOUR else 5)
        runner.tick()
        untouched = actions.get(who, waiting['id'])['state'] == 'proposed'
        post(web, f'/v1/actions/{waiting["id"]}/approve', {'payload_hash': waiting['payload_hash']})
        runner.tick(); runner.tick()
        resumed = sql("SELECT r.id FROM handoffs h JOIN customer_requests r ON r.account_id=h.account_id AND r.id=h.resumed_request_id WHERE h.account_id=%s AND h.action_id=%s", [C, waiting['id']])
        record('P3-HANDOFF', 'An approval answered ' + ('an hour' if HOUR else 'a few seconds (run with --hour for the full hour)') + ' later resumes from its checkpoint',
               held == 0 and untouched and actions.get(who, waiting['id'])['state'] == 'done' and len(resumed) == 1, f"slots_held={held} resumed_turns={len(resumed)}")

        # -- P3-PARTIAL --------------------------------------------------------------------------------------------------------------------
        bench.seed(C, 'projects', 70, prefix='Many')
        text, error = wiring.connector_tools().call(C, {'connection': connection_id, 'resource_kind': 'folder', 'resource_id': 'projects'}, name='lumina_connector_list', request_id=request_id)
        first = json.loads(text) if not error else {}
        record('P3-PARTIAL', 'A partial result is always stated as partial', first.get('complete') is False and 'PARTIAL RESULT' in first.get('result', ''), f"complete={first.get('complete')} count={first.get('count')}")
    finally:
        # -- P2-OFFBOARD: the disposable account leaves completely, whatever happened above ---------------------------------------------------------------
        jobs = wiring.account_jobs()
        jobs.start_offboarding_by_operator(C, 'phase23-live', cooling_off=0)
        for _ in range(30):
            jobs.tick()
            state = sql("SELECT state,report_json FROM account_jobs WHERE account_id=%s AND kind='deletion'", [C])
            if state and state[0][0] in ('completed', 'failed'):
                break
            time.sleep(2)
        report = json.loads(state[0][1]) if state and state[0][1] else {}
        scan = report.get('verification') or {}
        record('P2-OFFBOARD', 'The disposable account is offboarded and the verification scan finds nothing but what stays by design',
               bool(state) and state[0][0] == 'completed' and scan.get('clean') is True and not scan.get('found'), json.dumps({'found': scan.get('found'), 'kept': scan.get('kept_by_design')}))
    failed = [r for r in RESULTS if not r['passed']]
    print(json.dumps({'passed': not failed, 'account': C, 'cases': RESULTS}), flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
