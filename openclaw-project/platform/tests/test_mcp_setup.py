"""Real SDK interoperability and account-scoped setup; no external provider accounts."""
import asyncio
import base64
import json
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs
from tests import test_mcp_connections as existing
from tests.mcp_fixture import URL, ISSUER
from agentai_platform.mcp_connections.client import RemoteClient
from agentai_platform.mcp_connections.network import ConnectionError
from agentai_platform.mcp_connections.relay import RemoteTools, SETUP, CONNECTIONS, SEARCH
from agentai_platform.mcp_connections.service import namespaced, redact
from agentai_platform.mcp_connections.credentials import credentials


class SetupChecks(unittest.TestCase):
    setUp = existing.ConnectionChecks.setUp
    connect = existing.ConnectionChecks.connect
    approve = existing.ConnectionChecks.approve

    def test_auto_public_server_and_manual_agent_duplicate_share_one_entry(self):
        cid = self.service.create(self.a, url=URL)
        self.assertTrue(self.service.test(self.a, cid)['connected'])
        remote = RemoteTools(self.service)
        reply = remote.call('a', {'url': URL, 'name': 'Duplicate'}, lambda: False, name=SETUP['name'], request_id='r1')
        self.assertFalse(reply['isError'])
        self.assertEqual(json.loads(reply['content'][0]['text'])['id'], cid)
        self.assertEqual(len(self.service.listing(self.a)['connections']), 1)
        self.assertEqual(self.service.listing(self.b)['connections'], [])

    def test_unknown_agent_endpoint_is_listed_but_never_contacted_before_confirmation(self):
        remote = RemoteTools(self.service)
        reply = remote.call('a', {'url': URL, 'source_url': 'https://docs.example.com/mcp'}, lambda: False, name=SETUP['name'])
        item = json.loads(reply['content'][0]['text'])
        self.assertFalse(item['setup_confirmed']); self.assertEqual(item['added_by'], 'lumina')
        self.assertEqual(self.fixture.initialized, 0)
        with self.assertRaises(ConnectionError) as e: self.service.test(self.a, item['id'])
        self.assertEqual(e.exception.code, 'confirmation_required')
        listing = remote.call('a', {}, lambda: False, name=CONNECTIONS['name'])
        self.assertNotIn('secret_json', listing['content'][0]['text'])
        denied = remote.call('a', {'url': URL, 'token': 'secret'}, lambda: False, name=SETUP['name'])
        self.assertTrue(denied['isError'])

    def test_cimd_only_registration_uses_global_identity_without_registering(self):
        self.fixture.oauth = True; self.fixture.cimd = True
        identity = 'https://lumina.mcp-demo.net/oauth/client-metadata.json'
        self.service.metadata_url = identity
        cid = self.service.create(self.a, url=URL)
        pending = self.service.test(self.a, cid, session='browser', browser='cookie')
        params = parse_qs(urlsplit(pending['authorize_url']).query)
        self.assertEqual(params['client_id'], [identity]); self.assertEqual(self.fixture.registrations, 0)
        self.assertEqual(params['resource'], [URL]); self.assertEqual(params['code_challenge_method'], ['S256'])
        self.assertTrue(self.service.callback(self.a, params['state'][0], 'code', 'browser')['connected'])
        self.assertFalse(any(t['enabled'] for t in self.service.listing(self.a)['connections'][0]['tools']))

    def test_header_and_basic_credentials_use_same_encrypted_connection_service(self):
        for method, options, token, headers in [
            ('header', {'header_name': 'X-API-Key'}, 'private-api-key', {'X-API-Key': 'private-api-key'}),
            ('basic', {'username': 'private-user', 'password': 'private-pass'}, '', {'Authorization': 'Basic ' + base64.b64encode(b'private-user:private-pass').decode()})]:
            with self.subTest(method=method):
                self.fixture.required_headers = headers
                cid = self.service.create(self.a, url=URL + '/' + method, auth_method=method, options=options, token=token)
                self.assertTrue(self.service.test(self.a, cid)['connected'])
                public = json.dumps(self.service.listing(self.a))
                for value in ('private-api-key', 'private-user', 'private-pass'): self.assertNotIn(value, public)
                with self.store.connect() as con:
                    raw = con.execute('SELECT secret_json FROM mcp_connections WHERE id=?', (cid,)).fetchone()[0]
                for value in ('private-api-key', 'private-pass'): self.assertNotIn(value, raw)

    def test_customer_can_supply_registered_client_and_reconfigure_resets_tool_choices(self):
        self.fixture.oauth = True
        cid = self.service.create(self.a, url=URL, auth_method='oauth', options={'issuer': ISSUER, 'client_id': 'my-app', 'client_secret': 'app-secret', 'token_endpoint_auth_method': 'client_secret_post'})
        pending = self.service.test(self.a, cid, session='browser')
        params = parse_qs(urlsplit(pending['authorize_url']).query)
        self.assertEqual(params['client_id'], ['my-app']); self.assertEqual(self.fixture.registrations, 0)
        self.service.registrations={URL:{'issuer':ISSUER,'client_id':'operator-other'}}
        self.service.reconnect(self.a, cid)
        pending=self.service.test(self.a,cid,session='browser')
        params=parse_qs(urlsplit(pending['authorize_url']).query)
        self.assertEqual(params['client_id'],['my-app'])
        self.service.callback(self.a, params['state'][0], 'code', 'browser')
        self.service.update(self.a, cid, tools={'echo': True})
        self.service.configure(self.a, cid, auth_method='bearer', token='fixture-access-secret')
        self.assertTrue(self.service.test(self.a, cid)['connected'])
        self.assertEqual(self.service.enabled_tools('a'), [])
        self.assertFalse(self.service.listing(self.a)['connections'][0]['tools'][0]['enabled'])

    def test_legacy_sse_fallback_is_only_during_initialization(self):
        self.fixture.legacy = True
        cid = self.service.create(self.a, url=URL, auth_method='none')
        self.assertTrue(self.service.test(self.a, cid)['connected'])
        self.assertEqual(self.service.listing(self.a)['connections'][0]['transport'], 'sse')
        self.service.update(self.a, cid, tools={'echo': True})
        self.service.call('a', 'echo', {'text': 'sse'}, 'r1'); self.approve()
        self.assertFalse(self.service.call('a', 'echo', {'text': 'sse'}, 'r1')['isError'])
        self.assertEqual(len(self.fixture.calls), 1)

    def test_scope_upgrade_is_saved_without_replaying_a_dispatched_action(self):
        self.fixture.oauth = True
        cid = self.service.create(self.a, url=URL, auth_method='oauth')
        pending = self.service.test(self.a, cid, session='browser')
        state = parse_qs(urlsplit(pending['authorize_url']).query)['state'][0]
        self.service.callback(self.a, state, 'code', 'browser')
        self.service.update(self.a, cid, tools={'write': True})
        self.service.call('a', 'write', {'text': 'one'}, 'r1'); self.approve()
        self.fixture.reject_call = True; self.fixture.required_scope = 'tasks:write'
        with self.assertRaises(ConnectionError): self.service.call('a', 'write', {'text': 'one'}, 'r1')
        self.assertEqual(len(self.fixture.calls), 1)
        self.assertEqual(self.service.listing(self.a)['connections'][0]['error_code'], 'additional_permission_required')
        self.service.reconnect(self.a, cid)
        pending = self.service.test(self.a, cid, session='browser')
        params = parse_qs(urlsplit(pending['authorize_url']).query)
        self.assertIn('tasks:write', params['scope'][0].split())
        with self.assertRaises(ConnectionError): self.service.call('a', 'write', {'text': 'one'}, 'r1')
        self.assertEqual(len(self.fixture.calls), 1)

    def test_reserved_headers_credentials_and_cross_account_configuration_are_refused(self):
        for name in ['Authorization', 'Host', 'Cookie', 'Proxy-Foo', 'Sec-Token', 'Mcp-Session-Id', 'X-Key\r\nHost']:
            with self.assertRaises(ConnectionError): credentials('header', 'secret', {'header_name': name})
        cid = self.service.create(self.a, url=URL)
        from agentai_platform.security import NotFound
        with self.assertRaises(NotFound): self.service.configure(self.b, cid, auth_method='none')
