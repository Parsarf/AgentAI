#!/usr/bin/env python3
"""Tier B, the quick live gate that runs after every deploy (roadmap #4): a few real checks against the running system, small enough to run every time.

Run as the app user with the app environment loaded (agentai-deploy does this):  python acceptance_live.py <commit sha> [--wait 600]

  LIVE-READY     the web app answers its readiness check and the migrations are all applied
  LIVE-ANSWER    the owner's own test account gets one real answer from its own assistant (its cell is woken if it sleeps), charged once and settled
  LIVE-STAMP     that request carries a version stamp whose release is the commit that was just deployed
  LIVE-ISOLATION a second account cannot read that request

Costs well under a cent. Exit 0 when every check passed, 1 when any did not, 3 when the answer could not be CHECKED for a reason that is not the release (the test account is
missing, the host had no room to wake its assistant, the model provider was busy, the test account's allowance is used up): the release is then left in place, not rolled back. Results: /var/lib/agentai-deploy/tierb-<sha>.json is written by agentai-deploy from this output.
The wider proof (two accounts at once, killing the worker or the cell, rate limits, large tasks) is deploy/phase1_live.py: run it by hand before a launch or after a big change.
"""
import json
import os
import sys
import time
import uuid

sys.path.insert(0, '/opt/agentai-platform/current')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'accounts.settings')
import django  # noqa: E402
django.setup()
from django.conf import settings  # noqa: E402
from django.db import connection  # noqa: E402
from django.test import Client  # noqa: E402

A = 'f40a5f6b9ab8437cbd0f7459f0ecaa71'          # the owner's own test account
RESULTS = []


def record(case, title, ok, detail=''):
    RESULTS.append({'id': case, 'title': title, 'passed': bool(ok), 'detail': str(detail)[:300]})
    print(f"{'PASS' if ok else 'FAIL':5} {case}  {title}" + (f'  -- {detail}' if detail and not ok else ''), flush=True)


def sql(q, args=()):
    with connection.cursor() as c:
        c.execute(q, args)
        return c.fetchall() if c.description else []


def client(user):
    from accounts.models import Identity
    c = Client(HTTP_HOST=settings.ALLOWED_HOSTS[0], raise_request_exception=False)
    c.force_login(user)
    s = c.session
    s['epoch'] = Identity.objects.get(user=user).epoch
    s.save()
    return c


def post(c, path, body):
    return c.post(path, data=json.dumps(body), content_type='application/json', secure=True)


def unchecked(why):
    """The live answer could not be checked, and the cause is the surroundings, not the release: say so and exit 3 (agentai-deploy keeps the release and reports it)."""
    print(json.dumps({'passed': False, 'inconclusive': True, 'why': why, 'cases': RESULTS}), flush=True)
    return 3


def outside_cause(request, row):
    """Why the test request did not complete, when that is known to be outside the release; else None (a failure counts against the release)."""
    if not request or not row:
        return None
    state = row[0][0]
    if state == 'waiting' and sql("""SELECT 1 FROM lifecycle_details d JOIN operations o ON o.account_id=d.account_id AND o.id=d.operation_id
            WHERE d.account_id=%s AND d.error_code='capacity_wait' AND o.state='pending'""", [A]):
        return 'the host had no room to start the test account\'s assistant (every assistant was busy)'
    if state == 'failed':
        from agentai_platform.chat_driver import ALLOWANCE_FAILURE, BUSY_FAILURE
        result = (sql('SELECT result FROM customer_requests WHERE id=%s', [request]) or [[None]])[0][0]
        if result == BUSY_FAILURE:
            return 'the model provider was too busy to answer'
        if result == ALLOWANCE_FAILURE:
            return 'the test account\'s model allowance is used up'
    return None


def main():
    sha = sys.argv[1] if len(sys.argv) > 1 else ''
    wait = int(sys.argv[sys.argv.index('--wait') + 1]) if '--wait' in sys.argv else 600
    from accounts.models import Identity
    ready = Client(HTTP_HOST=settings.ALLOWED_HOSTS[0], raise_request_exception=False).get('/readyz', secure=True)
    import pathlib
    migrations = sorted(p.name for p in (pathlib.Path('/opt/agentai-platform/current/migrations')).glob('*.sql'))
    applied = {r[0] for r in sql('SELECT version FROM schema_migrations')}
    record('LIVE-READY', 'The app is ready and every migration is applied', ready.status_code == 200 and set(migrations) <= applied, f'ready={ready.status_code} missing={sorted(set(migrations) - applied)[:3]}')
    try:
        user = Identity.objects.get(account_id=A, role='customer').user
    except (Identity.DoesNotExist, Identity.MultipleObjectsReturned):
        if RESULTS[0]['passed']:
            return unchecked('the owner\'s test account is not on this server (or has more than one customer)')
        raise
    c = client(user)
    project = c.get('/v1/projects', secure=True).json()['projects'][0]['id']
    conversation = post(c, '/v1/conversations', {'project_id': project}).json().get('conversation', {}).get('id')
    request = None
    if conversation:
        request = (post(c, f'/v1/conversations/{conversation}/send', {'message': 'Reply with exactly the word: ok', 'key': uuid.uuid4().hex, 'mode': 'text'}).json().get('request') or {}).get('id')
    end, row = time.time() + wait, None
    while request and time.time() < end:
        row = sql('SELECT state,outcome,versions_json FROM customer_requests WHERE id=%s', [request])
        if row and row[0][0] in ('completed', 'failed', 'cancelled'):
            break
        time.sleep(3)
    done = bool(row) and row[0][0] == 'completed' and row[0][1] == 'completed'
    receipts = sql('SELECT count(*) FROM provider_receipts WHERE task_id=%s', [request])[0][0] if request else 0
    settled = (sql('SELECT state FROM task_reservations WHERE task_id=%s', [request]) or [[None]])[0][0] if request else None
    replies = sql("SELECT count(*) FROM chat_messages WHERE request_id=%s AND provenance='agent'", [request])[0][0] if request else 0
    record('LIVE-ANSWER', 'The test account gets one real answer, charged once and settled', done and receipts == 1 and settled == 'settled' and replies >= 1,
           f'state={row[0][:2] if row else None} receipts={receipts} reservation={settled} replies={replies}')
    stamp = json.loads(row[0][2]) if row and row[0][2] else {}
    record('LIVE-STAMP', 'The request carries a version stamp for the commit that was deployed', bool(stamp) and (not sha or str(stamp.get('release', '')).startswith(sha[:7]) or sha[:7] in str(stamp.get('release', ''))),
           f"release={str(stamp.get('release'))[:20]} expected={sha[:7]}")
    # A second account that can sign in: a deleted customer keeps an identity row but is refused at the door (401/403), which says nothing about this request.
    other = sql("SELECT i.user_id FROM accounts_identity i JOIN accounts a ON a.id=i.account_id JOIN auth_user u ON u.id=i.user_id "
                "WHERE i.role='customer' AND i.account_id<>%s AND a.status='active' AND u.is_active ORDER BY i.user_id LIMIT 1", [A])
    if other and request:
        from django.contrib.auth.models import User
        status = client(User.objects.get(pk=other[0][0])).get(f'/v1/requests/{request}', secure=True).status_code
        record('LIVE-ISOLATION', 'A second account cannot read that request', status == 404, f'status={status}')
    else:
        record('LIVE-ISOLATION', 'A second account cannot read that request', True, 'no second active account on this server')
    if conversation:
        post(c, f'/v1/conversations/{conversation}/archive', {})               # the test chat never stays in the account's list
    failed = [r for r in RESULTS if not r['passed']]
    why = outside_cause(request, row) if not done else None
    if why and all(r['passed'] for r in RESULTS if r['id'] in ('LIVE-READY', 'LIVE-ISOLATION')):
        return unchecked(why)
    print(json.dumps({'passed': not failed, 'cases': RESULTS}), flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
