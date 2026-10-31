import os
import time
from django.test import TestCase, override_settings
from agentai_platform import safety as sf
from .tests import AccountBoundaryTests, PASSWORD


class FakeCon:
    """Just enough of a connection for sf.is_on: rows keyed by (account, feature)."""
    def __init__(self): self.rows = {}
    def execute(self, sql, params=()):
        row = self.rows.get(tuple(params))
        class Result:
            def fetchone(self): return row
        return Result()


class SafetySwitchChecks(TestCase):
    new_client = AccountBoundaryTests.new_client
    post = AccountBoundaryTests.post
    signed = AccountBoundaryTests.signed
    setUp = AccountBoundaryTests.setUp

    def account_of(self, client):
        return client.get('/v1/me', secure=True).json().get('account_id')

    def test_nobody_sees_it_unless_named_owner(self):
        a = self.signed()
        self.assertEqual(self.new_client().get('/v1/safety', secure=True).status_code, 401)
        self.assertEqual(a.get('/v1/safety', secure=True).status_code, 404)             # no owner configured
        with override_settings(SAFETY_OWNER_ACCOUNT='someone-else'):
            self.assertEqual(a.get('/v1/safety', secure=True).status_code, 404)
            self.assertEqual(self.post(a, '/v1/safety/change', {'password': 'x', 'changes': {'budget_caps': False}}).status_code, 404)

    def test_owner_lists_everything_on_and_change_needs_password(self):
        a = self.signed()
        with override_settings(SAFETY_OWNER_ACCOUNT=self.account_of(a)):
            body = a.get('/v1/safety', secure=True).json()
            self.assertEqual(body['off_count'], 0)
            self.assertEqual({f['key'] for f in body['features']}, set(sf.FEATURES))
            r = self.post(a, '/v1/safety/change', {'password': 'wrong', 'changes': {'budget_caps': False}})
            self.assertEqual(r.status_code, 403)
            self.assertEqual(a.get('/v1/safety', secure=True).json()['off_count'], 0)

    def test_unknown_feature_and_bad_values_are_refused(self):
        a = self.signed()
        with override_settings(SAFETY_OWNER_ACCOUNT=self.account_of(a)):
            for changes in ({'nope': False}, {'budget_caps': 'off'}, {}):
                self.assertEqual(self.post(a, '/v1/safety/change', {'password': 'x', 'changes': changes}).status_code, 400)

    def test_switch_is_per_account_expires_and_fails_closed(self):
        con = FakeCon()
        self.assertTrue(sf.is_on(con, 'a', 'budget_caps'))
        con.rows[('a', 'budget_caps')] = (0, None)
        self.assertFalse(sf.is_on(con, 'a', 'budget_caps'))
        self.assertTrue(sf.is_on(con, 'b', 'budget_caps'))                                   # another account is untouched
        con.rows[('a', 'budget_caps')] = (0, int(time.time()) - 5)
        self.assertTrue(sf.is_on(con, 'a', 'budget_caps'))                                   # expired switch is back on
        self.assertTrue(sf.is_on(object(), 'a', 'budget_caps'))                              # any error means on
        self.assertTrue(sf.is_on(con, 'a', 'not_a_feature'))

    def test_owner_switches_one_off_then_on_and_others_stay_unaffected(self):
        a, b = self.signed(), self.signed('b')
        with override_settings(SAFETY_OWNER_ACCOUNT=self.account_of(a)):
            r = self.post(a, '/v1/safety/change', {'password': PASSWORD, 'changes': {'budget_caps': False, 'rate_limits': False}})
            self.assertEqual(r.status_code, 200)
            body = r.json()
            self.assertEqual(body['off_count'], 2)
            self.assertFalse(next(f for f in body['features'] if f['key'] == 'budget_caps')['on'])
            self.assertEqual(b.get('/v1/safety', secure=True).status_code, 404)
            r = self.post(a, '/v1/safety/change', {'password': PASSWORD, 'changes': {'budget_caps': True}})
            self.assertEqual(r.json()['off_count'], 1)
            r = self.post(a, '/v1/safety/change', {'password': PASSWORD, 'changes': {'rate_limits': False}, 'minutes': 5})
            off = next(f for f in r.json()['features'] if f['key'] == 'rate_limits')
            self.assertFalse(off['on'])
            self.assertTrue(off['expires_epoch'] > time.time())


class ScopeRuleChecks(TestCase):
    """The rule for one account: its own setting, else the all-users setting, else on; an expired "off" says nothing."""
    def test_the_more_specific_setting_wins_and_expired_offs_fall_through(self):
        now = 1_000
        off, on, expired = (0, None), (1, None), (0, 500)
        self.assertTrue(sf.effective(None, None, now))                                    # nothing set
        self.assertFalse(sf.effective(None, off, now))                                    # off for everyone reaches an account with no setting
        self.assertTrue(sf.effective(on, off, now))                                       # its own explicit "on" exempts it
        self.assertFalse(sf.effective(off, None, now))                                    # off for this account only
        self.assertFalse(sf.effective(off, on, now))                                      # its own off beats an on-for-everyone
        self.assertTrue(sf.effective(expired, None, now))                                 # an expired off is no setting
        self.assertFalse(sf.effective(expired, off, now))                                 # ...so the all-users off applies again
        self.assertTrue(sf.effective(expired, expired, now))

    def test_is_on_reads_both_scopes_and_fails_closed(self):
        con = FakeCon()
        con.rows[(sf.ALL, 'payment_stop')] = (0, None)
        self.assertFalse(sf.is_on(con, 'a', 'payment_stop')); self.assertFalse(sf.is_on(con, 'b', 'payment_stop'))
        con.rows[('a', 'payment_stop')] = (1, None)
        self.assertTrue(sf.is_on(con, 'a', 'payment_stop')); self.assertFalse(sf.is_on(con, 'b', 'payment_stop'))
        self.assertFalse(sf.is_on(con, sf.ALL, 'payment_stop'))                           # asking about "everyone" never reads a per-account row
        self.assertTrue(sf.is_on(object(), 'a', 'payment_stop'))                          # any error means on


def real_connection():
    """A throwaway sqlite database with the two safety tables, built from the migrations' own SQL."""
    import importlib, sqlite3
    con = sqlite3.connect(':memory:')
    for name in ('0014_safety_overrides', '0015_safety_access'):
        con.executescript(importlib.import_module('accounts.migrations.' + name).SQL)
    return con


class ScopeStorageChecks(TestCase):
    def setUp(self): self.con = real_connection(); self.addCleanup(self.con.close)

    def state(self, rows, key): return next(f for f in rows if f['key'] == key)

    def test_all_users_off_reaches_every_account_and_an_account_can_stay_exempt(self):
        sf.set_feature(self.con, sf.ALL, 'payment_stop', False, 'owner')
        mine = self.state(sf.listing(self.con, 'b'), 'payment_stop')
        self.assertEqual((mine['on'], mine['source']), (False, 'all'))
        sf.set_feature(self.con, 'a', 'payment_stop', True, 'a')                           # "on" while everyone is off keeps an explicit row
        self.assertEqual(self.con.execute("SELECT enabled FROM safety_overrides WHERE account_id='a'").fetchone(), (1,))
        exempt = self.state(sf.listing(self.con, 'a'), 'payment_stop')
        self.assertEqual((exempt['on'], exempt['source']), (True, 'account'))
        self.assertFalse(self.state(sf.listing(self.con, 'b'), 'payment_stop')['on'])       # others still follow the default
        sf.set_feature(self.con, sf.ALL, 'payment_stop', True, 'owner')                    # everyone back on
        self.assertTrue(self.state(sf.listing(self.con, 'b'), 'payment_stop')['on'])
        sf.set_feature(self.con, 'c', 'payment_stop', True, 'c')                           # nothing to be exempt from: no row is kept
        self.assertIsNone(self.con.execute("SELECT 1 FROM safety_overrides WHERE account_id='c'").fetchone())

    def test_the_all_users_view_counts_the_accounts_that_differ(self):
        sf.set_feature(self.con, 'a', 'web_limits', False, 'a'); sf.set_feature(self.con, 'b', 'web_limits', False, 'b', expires_epoch=1)       # b's is long expired
        row = self.state(sf.listing_all(self.con), 'web_limits')
        self.assertEqual((row['on'], row['overridden']), (True, 1))
        sf.set_feature(self.con, sf.ALL, 'web_limits', False, 'owner', expires_epoch=int(time.time()) + 60)
        row = self.state(sf.listing_all(self.con), 'web_limits')
        self.assertFalse(row['on']); self.assertTrue(row['expires_epoch'] > time.time())

    def test_shared_and_core_switches_cannot_be_changed_and_privacy_never_off_for_everyone(self):
        for key in ('csrf_protection', 'proxy_rules', 'login_limits'):
            with self.assertRaises(sf.Locked) as e: sf.set_feature(self.con, 'a', key, False, 'a')
            self.assertEqual(e.exception.reason, 'shared')
        for key in ('tenant_isolation', 'vault_encryption', 'audit_log'):
            with self.assertRaises(sf.Locked) as e: sf.set_feature(self.con, sf.ALL, key, False, 'owner')
            self.assertEqual(e.exception.reason, 'core')
        for key in ('personal_data_scrub', 'vault_notice', 'secret_redaction', 'ssrf_guard'):
            with self.assertRaises(sf.Locked) as e: sf.set_feature(self.con, sf.ALL, key, False, 'owner')
            self.assertEqual(e.exception.reason, 'privacy')
            sf.set_feature(self.con, 'a', key, False, 'a')                                  # but it may be switched off for your own account
            self.assertFalse(self.state(sf.listing(self.con, 'a'), key)['on'])
            sf.set_feature(self.con, sf.ALL, key, True, 'owner')                            # and switching it ON for everyone is always allowed
        with self.assertRaises(KeyError): sf.set_feature(self.con, 'a', 'nope', False, 'a')
        self.assertEqual({f['lock'] for f in sf.listing_all(self.con) if f['key'] in sf.PRIVACY}, {'privacy'})
        self.assertEqual({f['lock'] for f in sf.listing(self.con, 'a') if f['key'] in sf.PRIVACY}, {None})

    def test_revoking_access_drops_the_accounts_own_settings(self):
        sf.grant_access(self.con, 'b', 'owner'); sf.set_feature(self.con, 'b', 'web_limits', False, 'b'); sf.set_feature(self.con, 'a', 'web_limits', False, 'a')
        self.assertTrue(sf.has_access(self.con, 'b')); self.assertFalse(sf.has_access(self.con, 'a'))
        sf.revoke_access(self.con, 'b')
        self.assertFalse(sf.has_access(self.con, 'b'))
        self.assertTrue(self.state(sf.listing(self.con, 'b'), 'web_limits')['on'])         # protections are back
        self.assertFalse(self.state(sf.listing(self.con, 'a'), 'web_limits')['on'])        # nobody else is touched
        self.assertFalse(sf.has_access(object(), 'b'))                                     # no table, no access


class MenuAccessChecks(TestCase):
    """The menu through the real routes: the owner, an account the owner granted, and everyone else."""
    new_client = AccountBoundaryTests.new_client
    post = AccountBoundaryTests.post
    signed = AccountBoundaryTests.signed
    setUp = AccountBoundaryTests.setUp

    def account_of(self, client): return client.get('/v1/me', secure=True).json().get('account_id')

    def grant(self, owner, email='b@example.invalid'): return self.post(owner, '/v1/safety/access/change', {'password': PASSWORD, 'grant': email})

    def test_a_granted_account_sees_only_its_own_switches_and_nothing_of_the_owners_side(self):
        a, b = self.signed(), self.signed('b')
        with override_settings(SAFETY_OWNER_ACCOUNT=self.account_of(a)):
            self.assertEqual(b.get('/v1/safety', secure=True).status_code, 404)                       # not yet
            self.assertEqual(self.grant(a).status_code, 200)
            body = b.get('/v1/safety', secure=True).json()
            self.assertEqual((body['role'], body['scope'], body['scopes']), ('member', 'mine', ['mine']))
            self.assertEqual(b.get('/v1/safety?scope=all', secure=True).status_code, 404)             # the all-users view is the owner's alone
            self.assertEqual(self.post(b, '/v1/safety/change', {'password': PASSWORD, 'scope': 'all', 'changes': {'web_limits': False}}).status_code, 404)
            self.assertEqual(b.get('/v1/safety/access', secure=True).status_code, 404)                # and so is the list of who has access
            self.assertEqual(self.post(b, '/v1/safety/access/change', {'password': PASSWORD, 'grant': 'a@example.invalid'}).status_code, 404)
            r = self.post(b, '/v1/safety/change', {'password': PASSWORD, 'changes': {'web_limits': False}})
            self.assertEqual(r.status_code, 200); self.assertEqual(r.json()['off_count'], 1)
            self.assertEqual(a.get('/v1/safety', secure=True).json()['off_count'], 0)                  # the owner's own account is unaffected

    def test_the_owner_has_both_views_and_all_users_changes_reach_a_granted_account(self):
        a, b = self.signed(), self.signed('b')
        with override_settings(SAFETY_OWNER_ACCOUNT=self.account_of(a)):
            self.grant(a)
            mine = a.get('/v1/safety', secure=True).json()
            self.assertEqual((mine['role'], mine['scope'], mine['scopes']), ('owner', 'mine', ['mine', 'all']))
            r = self.post(a, '/v1/safety/change', {'password': PASSWORD, 'scope': 'all', 'changes': {'web_limits': False}})
            self.assertEqual(r.status_code, 200); body = r.json()
            self.assertEqual(body['scope'], 'all'); self.assertEqual(next(f for f in body['features'] if f['key'] == 'web_limits')['on'], False)
            seen = next(f for f in b.get('/v1/safety', secure=True).json()['features'] if f['key'] == 'web_limits')
            self.assertEqual((seen['on'], seen['source']), (False, 'all'))                            # b inherits it
            self.assertEqual(next(f for f in a.get('/v1/safety?scope=all', secure=True).json()['features'] if f['key'] == 'web_limits')['on'], False)
            self.assertEqual(self.post(b, '/v1/safety/change', {'password': PASSWORD, 'changes': {'web_limits': True}}).status_code, 200)
            self.assertTrue(next(f for f in b.get('/v1/safety', secure=True).json()['features'] if f['key'] == 'web_limits')['on'])     # b exempted itself
            self.assertEqual(a.get('/v1/safety?scope=bogus', secure=True).status_code, 400)

    def test_locked_switches_are_refused_with_the_reason_and_nothing_is_half_applied(self):
        a = self.signed()
        with override_settings(SAFETY_OWNER_ACCOUNT=self.account_of(a)):
            for key, scope, reason in (('csrf_protection', 'mine', 'shared'), ('audit_log', 'all', 'core'), ('personal_data_scrub', 'all', 'privacy')):
                r = self.post(a, '/v1/safety/change', {'password': PASSWORD, 'scope': scope, 'changes': {'web_limits': False, key: False}})
                self.assertEqual((r.status_code, r.json()['reason'], r.json()['feature']), (400, reason, key))
            self.assertEqual(a.get('/v1/safety', secure=True).json()['off_count'], 0)                  # web_limits in the same request was not applied
            self.assertEqual(self.post(a, '/v1/safety/change', {'password': PASSWORD, 'changes': {'personal_data_scrub': False}}).status_code, 200)    # fine for my own account

    def test_granting_needs_the_owner_and_the_password_and_a_real_other_account(self):
        a, b = self.signed(), self.signed('b')
        with override_settings(SAFETY_OWNER_ACCOUNT=self.account_of(a)):
            self.assertEqual(self.post(a, '/v1/safety/access/change', {'password': 'wrong', 'grant': 'b@example.invalid'}).status_code, 403)
            self.assertEqual(b.get('/v1/safety', secure=True).status_code, 404)
            for body in ({'password': PASSWORD, 'grant': 'nobody@example.invalid'}, {'password': PASSWORD, 'grant': 'a@example.invalid'}):
                self.assertEqual(self.post(a, '/v1/safety/access/change', body).status_code, 400)       # unknown account; the owner cannot grant itself
            for body in ({'password': PASSWORD}, {'password': PASSWORD, 'grant': 'b@example.invalid', 'revoke': 'b@example.invalid'}):
                self.assertEqual(self.post(a, '/v1/safety/access/change', body).status_code, 400)
            listing = self.grant(a, 'B@Example.invalid').json()['access']                              # an email matches however it is typed
            self.assertEqual([row['email'] for row in listing], ['b@example.invalid'])
            self.assertEqual(a.get('/v1/safety/access', secure=True).json()['access'][0]['email'], 'b@example.invalid')
            self.post(b, '/v1/safety/change', {'password': PASSWORD, 'changes': {'web_limits': False}})
            r = self.post(a, '/v1/safety/access/change', {'password': PASSWORD, 'revoke': 'b@example.invalid'})
            self.assertEqual(r.json()['access'], [])
            self.assertEqual(b.get('/v1/safety', secure=True).status_code, 404)                        # the menu is gone for b...

    def test_with_no_owner_configured_nobody_gets_in_whatever_was_granted(self):
        a, b = self.signed(), self.signed('b')
        with override_settings(SAFETY_OWNER_ACCOUNT=self.account_of(a)):
            self.grant(a)
        self.assertEqual(b.get('/v1/safety', secure=True).status_code, 404)
        with override_settings(SAFETY_OWNER_ACCOUNT=''):
            self.assertEqual(b.get('/v1/safety', secure=True).status_code, 404)
            self.assertEqual(a.get('/v1/safety', secure=True).status_code, 404)

    def test_off_for_everyone_never_reaches_the_sign_in_and_anonymous_limits(self):
        from django.db import connection
        from .services import ACCOUNT_RATE_SCOPES, _rate_limits_off, rate, Limited
        with connection.cursor() as c:
            c.execute("INSERT INTO safety_overrides(account_id,feature,enabled,changed_by,changed_epoch,expires_epoch) VALUES (%s,'rate_limits',0,'owner',1,NULL)", [sf.ALL])
        self.assertTrue(_rate_limits_off('a', everyone=True)); self.assertFalse(_rate_limits_off('a', everyone=False))
        for scope in ('login.ip', 'auth.pair', 'recovery.email', 'signup.ip', 'token.ip', 'mfa.user', 'ingress.anonymous', 'billing.webhook', 'safety.change', 'safety.access'):
            self.assertNotIn(scope, ACCOUNT_RATE_SCOPES, scope)
            with self.assertRaises(Limited):
                for _ in range(3): rate(scope, 'some-address', 2, 600)                              # still enforced
        for _ in range(5): rate('task.create', 'a', 2, 600)                                         # an account-keyed limit is off for everyone


class SnapshotAndRouteGates(TestCase):
    """What the app writes for the other processes, and the gates that live in the routes."""
    new_client = AccountBoundaryTests.new_client
    post = AccountBoundaryTests.post
    signed = AccountBoundaryTests.signed
    setUp = AccountBoundaryTests.setUp

    def account_of(self, client): return client.get('/v1/me', secure=True).json().get('account_id')

    def owner_setup(self):
        import tempfile
        self.dir = tempfile.mkdtemp(prefix='agentai-safety-test-'); self.addCleanup(lambda: __import__('shutil').rmtree(self.dir, ignore_errors=True))
        self.snapshot = os.path.join(self.dir, 'safety-switches.json')
        a = self.signed(); override = override_settings(SAFETY_OWNER_ACCOUNT=self.account_of(a), SAFETY_SNAPSHOT_FILE=self.snapshot)
        override.enable(); self.addCleanup(override.disable)
        return a

    def test_every_change_is_written_for_the_other_processes_and_revoking_clears_the_accounts_own_settings(self):
        a, b = self.owner_setup(), self.signed('b')
        self.assertEqual(self.post(a, '/v1/safety/access/change', {'password': PASSWORD, 'grant': 'b@example.invalid'}).status_code, 200)
        self.post(a, '/v1/safety/change', {'password': PASSWORD, 'changes': {'payment_stop': False}})
        self.post(b, '/v1/safety/change', {'password': PASSWORD, 'changes': {'denied_sites': False}})
        reader = sf.Reader(self.snapshot)
        acct_a, acct_b = self.account_of(a), self.account_of(b)
        self.assertEqual((reader.on(acct_a, 'payment_stop'), reader.on(acct_b, 'payment_stop')), (False, True))
        self.assertEqual((reader.on(acct_a, 'denied_sites'), reader.on(acct_b, 'denied_sites')), (True, False))
        self.post(a, '/v1/safety/change', {'password': PASSWORD, 'scope': 'all', 'changes': {'untrusted_page_text': False}})
        self.assertEqual((reader.on(acct_a, 'untrusted_page_text'), reader.on(acct_b, 'untrusted_page_text'), reader.on('anyone-else', 'untrusted_page_text')), (False, False, False))
        self.assertEqual(self.post(a, '/v1/safety/access/change', {'password': PASSWORD, 'revoke': 'b@example.invalid'}).status_code, 200)
        self.assertTrue(reader.on(acct_b, 'denied_sites'))                                                   # b's own setting went with its access

    def test_the_snapshot_is_made_on_first_use_and_a_failed_write_is_reported_not_hidden(self):
        a = self.owner_setup()
        self.assertFalse(os.path.exists(self.snapshot))
        a.get('/v1/safety', secure=True)
        self.assertTrue(os.path.exists(self.snapshot))                                                       # the database's settings reach the other processes
        override = override_settings(SAFETY_SNAPSHOT_FILE=os.path.join(self.dir, 'missing-folder', 'x.json')); override.enable(); self.addCleanup(override.disable)
        r = self.post(a, '/v1/safety/change', {'password': PASSWORD, 'changes': {'payment_stop': False}})
        self.assertEqual((r.status_code, r.json()['error']), (503, 'temporarily_unavailable'))             # saved, but the others have not heard: the owner is told
        self.assertFalse(next(f for f in a.get('/v1/safety', secure=True).json()['features'] if f['key'] == 'payment_stop')['on'])

    def test_the_vault_notice_is_required_until_that_switch_is_off_and_a_card_code_is_never_stored(self):
        import tempfile
        from agentai_platform import vault
        a = self.owner_setup(); card = {'number': '4242424242424242', 'exp_month': 12, 'exp_year': 2030, 'name': 'A'}
        with tempfile.TemporaryDirectory() as d:
            key = os.path.join(d, 'vault.key'); open(key, 'w').write(vault.Keyring.generate() + '\n'); os.chmod(key, 0o600)
            with override_settings(VAULT_KEY_FILE=key):
                self.assertEqual(self.post(a, '/v1/vault/add', {'kind': 'card', 'secret': card}).status_code, 400)                  # on: the tick is required
                self.post(a, '/v1/safety/change', {'password': PASSWORD, 'changes': {'vault_notice': False}})
                self.assertEqual(self.post(a, '/v1/vault/add', {'kind': 'card', 'secret': card}).status_code, 200)                  # off: saved without the tick
                self.assertEqual(self.post(a, '/v1/vault/add', {'kind': 'card', 'secret': {**card, 'cvv': '123'}}).status_code, 400)   # but a security code is never stored
                self.assertEqual(self.post(a, '/v1/vault/add', {'kind': 'card', 'secret': card, 'accepted': 'yes'}).status_code, 200)    # off means the tick is not looked at

    def test_the_upload_size_limit_in_the_view_follows_the_account(self):
        import tempfile, shutil
        from .test_files import multipart_body, BOUNDARY
        import re
        root = tempfile.mkdtemp(prefix='agentai-files-test-'); os.chmod(root, 0o700); self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        storage = override_settings(STORAGE_DIR=root, ARTIFACT_SIGNING_KEY=b'k' * 32, STORAGE_READY=True, UPLOADS_ENABLED=True); storage.enable(); self.addCleanup(storage.disable)
        a = self.owner_setup()
        def upload(client, size):
            page = client.get('/account/login/', secure=True)
            token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode()).group(1)
            return client.post('/v1/projects/project-a/files', multipart_body(token, [('big.txt', b'x' * size)]), content_type=f'multipart/form-data; boundary={BOUNDARY}',
                               secure=True, HTTP_REFERER='https://localhost/account/')
        big = 10 * 1024 * 1024 + 1
        self.assertEqual(upload(a, big).status_code, 422)                                                    # on: over 10 MiB is refused in the view
        self.post(a, '/v1/safety/change', {'password': PASSWORD, 'changes': {'upload_limits': False}})
        self.assertEqual(upload(a, big).status_code, 201)                                                    # off: accepted, and the service's own limits are off too
