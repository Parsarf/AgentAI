"""Live check of self-service sign-up on the real stack (run on the server as the app user).

Uses the real database and middleware but captures emails in memory (nothing is sent) and opens the door only for this process
through a temporary switch file; the real owner switch stays as it is. Approval is NOT exercised here (it would create a real
assistant); the sign-up is declined and removed at the end. Prints PASS/FAIL per step."""
import io
import json
import os
import re
import sys
import tempfile
import uuid

sys.path.insert(0, '/opt/agentai-platform/current')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'accounts.settings')
import django  # noqa: E402
django.setup()
from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.core import mail  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.db import connection  # noqa: E402
from django.test import Client, override_settings  # noqa: E402
from django.test.utils import setup_test_environment  # noqa: E402
from agentai_platform.switches import SwitchStore  # noqa: E402

HOST = settings.ALLOWED_HOSTS[0]
results = []


def check(name, ok, detail=''):
    results.append(ok)
    print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else f'  -- {detail}'), flush=True)


def post(c, path, body):
    token = c.get('/v1/csrf', secure=True, HTTP_HOST=HOST).json()['csrf_token']
    return c.post(path, json.dumps(body), content_type='application/json', secure=True, HTTP_HOST=HOST, HTTP_X_CSRFTOKEN=token, HTTP_ORIGIN=settings.PUBLIC_ORIGIN)


def main():
    setup_test_environment()
    email, pw = f'p17-{uuid.uuid4().hex[:8]}@invalid.test', 'Live-check-passphrase-77'
    c = Client(enforce_csrf_checks=True, HTTP_HOST=HOST, raise_request_exception=False)
    check('door is closed by default (real owner switch)', post(c, '/auth/signup', {'email': email, 'password': pw}).status_code == 403)
    check('config says closed', c.get('/v1/signup/config', secure=True, HTTP_HOST=HOST).json() == {'open': False})
    tmp = tempfile.TemporaryDirectory()
    sw, facts = os.path.join(tmp.name, 'sw.json'), os.path.join(tmp.name, 'f.json')
    json.dump({'mail_ready': True}, open(facts, 'w'))
    store = SwitchStore(sw, facts_path=facts); store.confirm('open_signups', 'approval_only', 'live-check'); store.set('open_signups', True, 'live-check')
    account = None
    with override_settings(SWITCHES_FILE=sw, SWITCH_FACTS_FILE=facts, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
        check('config says open', c.get('/v1/signup/config', secure=True, HTTP_HOST=HOST).json() == {'open': True})
        r = post(c, '/auth/signup', {'email': email, 'password': pw})
        check('sign-up accepted', r.status_code == 202 and r.json() == {'accepted': True}, r.content[:200])
        again = post(Client(enforce_csrf_checks=True, HTTP_HOST=HOST, raise_request_exception=False), '/auth/signup', {'email': email, 'password': pw})
        check('same answer for the same address (no enumeration)', again.status_code == 202 and again.json() == {'accepted': True})
        check('confirmation email prepared with a link', bool(mail.outbox) and 'verify?code=' in mail.outbox[0].body)
        code = re.search(r'code=([A-Za-z0-9_-]+)', mail.outbox[-1].body).group(1)      # a repeat sign-up re-sends and replaces the link
        r = post(Client(enforce_csrf_checks=True, HTTP_HOST=HOST, raise_request_exception=False), '/auth/login', {'email': email, 'password': pw})
        check('cannot sign in before confirming', r.status_code == 401)
        r = post(Client(enforce_csrf_checks=True, HTTP_HOST=HOST, raise_request_exception=False), '/auth/signup/verify', {'code': code})
        check('email confirmed -> pending', r.status_code == 200 and r.json() == {'state': 'pending'}, r.content[:200])
        r = post(Client(enforce_csrf_checks=True, HTTP_HOST=HOST, raise_request_exception=False), '/auth/signup/verify', {'code': code})
        check('link is single use', r.status_code == 404)
        r = post(Client(enforce_csrf_checks=True, HTTP_HOST=HOST, raise_request_exception=False), '/auth/login', {'email': email, 'password': pw})
        check('pending account is told it is waiting', r.status_code == 403 and r.json().get('error') == 'pending_approval', r.content[:200])
        user = User.objects.get(email=email)
        account = user.identity.account_id
        out = io.StringIO(); call_command('signup_admin', 'list', stdout=out)
        mine = [x for x in json.loads(out.getvalue())['customers'] if x['account'] == account]
        check('owner list shows it as pending', len(mine) == 1 and mine[0]['signup'] == 'pending' and mine[0]['status'] == 'suspended')
        check('no assistant or data was created for it', mine[0]['assistant'] is None)
        call_command('signup_admin', 'decline', account=account, stdout=io.StringIO())
        r = post(Client(enforce_csrf_checks=True, HTTP_HOST=HOST, raise_request_exception=False), '/auth/login', {'email': email, 'password': pw})
        check('declined account is refused', r.status_code == 403 and r.json().get('error') == 'not_approved')
    # clean up everything deletable (audit rows are append-only; the account stays as a deleted tombstone)
    if account:
        from accounts.models import ActionToken, Identity
        ActionToken.objects.filter(user__email=email).delete()
        ids = list(Identity.objects.filter(account_id=account).values_list('user_id', flat=True))
        Identity.objects.filter(account_id=account).delete()
        User.objects.filter(pk__in=ids).delete()
        with connection.cursor() as cur:
            for t in ('memberships', 'signups', 'projects', 'entitlements'):
                cur.execute(f'DELETE FROM {t} WHERE account_id=%s', [account])
            cur.execute("UPDATE accounts SET status='deleted' WHERE id=%s", [account])
        check('cleaned up', not User.objects.filter(email=email).exists())
    print('ALL PASS' if all(results) else 'SOME FAILED')


main()
