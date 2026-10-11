import json
from django.db import connection
from django.test import TestCase
from .tests import AccountBoundaryTests


class ConnectionHTTPChecks(TestCase):
    new_client = AccountBoundaryTests.new_client
    post = AccountBoundaryTests.post
    signed = AccountBoundaryTests.signed
    setUp = AccountBoundaryTests.setUp

    def seed(self, account_id, service='gmail', state='connected'):
        with connection.cursor() as c:
            c.execute("""INSERT INTO connector_connections(account_id,id,service,state,identity_label,granted_scopes,
                selected_resources,secret_ref,created_epoch,updated_epoch) VALUES (%s,%s,%s,%s,'me@example.com','[]','[]','ref-x',1,1)""",
                      [account_id, 'conn-' + account_id, service, state])
        return 'conn-' + account_id

    def account_of(self, client):
        return client.get('/v1/me', secure=True).json().get('account_id')

    def test_routes_require_a_signed_in_customer(self):
        anon = self.new_client()
        self.assertEqual(anon.get('/v1/account/connections', secure=True).status_code, 401)
        self.assertEqual(anon.get('/v1/account/drafts', secure=True).status_code, 401)
        self.assertEqual(self.post(anon, '/v1/account/connections/link', {'service': 'gmail'}).status_code, 401)
        self.assertEqual(self.post(anon, '/v1/account/connections/disconnect', {'connection_id': 'x'}).status_code, 401)

    def test_listing_is_read_only_and_link_fails_closed(self):
        a = self.signed()
        body = a.get('/v1/account/connections', secure=True).json()
        self.assertFalse(body['provider_writes_enabled'])
        self.assertEqual({c['service'] for c in body['connections']}, {'gmail', 'calendar', 'drive', 'github'})
        self.assertTrue(all(c['state'] == 'not_connected' and c['writes'] is False and c['configured'] is False
                            for c in body['connections']))
        self.assertEqual(self.post(a, '/v1/account/connections/link', {'service': 'gmail'}).status_code, 503)
        self.assertEqual(self.post(a, '/v1/account/connections/link', {'service': 'nonsense'}).status_code, 503)
        self.assertEqual(self.post(a, '/v1/account/connections/link', {'bogus': 'x'}).status_code, 400)
        self.assertEqual(a.get('/v1/account/connections/callback?code=x&state=y', secure=True).status_code, 503)
        self.assertEqual(a.get('/v1/account/drafts', secure=True).json(), {'drafts': [], 'sent': False})

    def test_link_requires_the_owner_switch_and_reports_it(self):
        import json as _json, os, tempfile
        from django.test import override_settings
        a = self.signed()
        self.assertFalse(a.get('/v1/account/connections', secure=True).json()['linking_available'])
        self.assertEqual(self.post(a, '/v1/account/connections/link', {'service': 'gmail'}).json()['error'], 'feature_off')
        with tempfile.TemporaryDirectory() as d:
            switches, facts = os.path.join(d, 's.json'), os.path.join(d, 'f.json')
            _json.dump({'a': True}, open(facts, 'w'))
            with override_settings(SWITCHES_FILE=switches, SWITCH_FACTS_FILE=facts):
                from agentai_platform.switches import SwitchStore
                store = SwitchStore(switches, facts_path=facts)
                store.confirm('connectors_linking', 'privacy_notice', 'owner')
                with self.assertRaises(Exception):                 # facts missing: the owner cannot turn it on
                    store.set('connectors_linking', True, 'owner')
                self.assertFalse(a.get('/v1/account/connections', secure=True).json()['linking_available'])
                _json.dump({'provider_registered': True, 'custody_backend': True}, open(facts, 'w'))
                store.set('connectors_linking', True, 'owner')
                self.assertTrue(a.get('/v1/account/connections', secure=True).json()['linking_available'])
                # switched on, but nothing is registered in the app yet: still fails closed
                self.assertEqual(self.post(a, '/v1/account/connections/link', {'service': 'gmail'}).json()['error'],
                                 'connector_not_configured')
                store.set('connectors_linking', False, 'owner')
                self.assertEqual(self.post(a, '/v1/account/connections/link', {'service': 'gmail'}).json()['error'], 'feature_off')

    def test_page_renders_honestly(self):
        a = self.signed()
        page = a.get('/account/connections/', secure=True)
        self.assertEqual(page.status_code, 200)
        text = page.content.decode()
        self.assertIn('Linking is not available yet', text)
        self.assertIn('Read-only', text)
        self.assertNotIn('Disconnect', text)

    def test_disconnect_is_scoped_to_own_account(self):
        a, b = self.signed('a'), self.signed('b')
        with connection.cursor() as c:
            c.execute("SELECT DISTINCT account_id FROM memberships")
            accounts = [r[0] for r in c.fetchall()]
        self.assertEqual(len(accounts), 2)
        ids = [self.seed(x) for x in accounts]
        mine = {a: ids[0], b: ids[1]}
        # whichever account owns ids[0]: the other client must get the same 404 as a missing id
        for client, other in ((a, b), (b, a)):
            overview = client.get('/v1/account/connections', secure=True).json()['connections']
            owned = [c for c in overview if c['state'] == 'connected']
            self.assertEqual(len(owned), 1)
            foreign = ids[0] if owned[0]['connection_id'] == ids[1] else ids[1]
            self.assertEqual(self.post(client, '/v1/account/connections/disconnect', {'connection_id': foreign}).status_code, 404)
            self.assertNotIn('ref-x', json.dumps(overview))
        own = [c for c in a.get('/v1/account/connections', secure=True).json()['connections'] if c['connection_id']][0]['connection_id']
        page = a.get('/account/connections/', secure=True).content.decode()
        self.assertIn('Disconnect', page)
        self.assertEqual(self.post(a, '/v1/account/connections/disconnect', {'connection_id': own}).status_code, 200)
        self.assertEqual({c['state'] for c in a.get('/v1/account/connections', secure=True).json()['connections']}, {'not_connected'})
