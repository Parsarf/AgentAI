import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from agentai_platform import model_keys as mk, model_catalog


class SelectionChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'keys.json'
        self.store = mk.ModelKeyStore(self.path, mk.ModelKeyring.derived('x' * 60))
        self.ep = mk.parse_endpoint('https://models.example.org/v1')

    def add(self, model='first'):
        return self.store.add('a', self.ep, model, 'sk-private-customer-key-1234')

    def test_keys_and_selection_are_independent_and_secrets_stay_encrypted(self):
        first = self.add(); second = self.add('second')
        self.assertEqual(self.store.choices('a')['selected'], 'lumina-default')
        self.assertIsNone(self.store.public('a'))
        self.store.select('a', first['id']); self.assertEqual(self.store.open('a')['model'], 'first')
        self.store.select('a', second['id']); self.assertEqual(self.store.open('a')['model'], 'second')
        self.store.select('a', 'lumina-default'); self.assertEqual(len(self.store.choices('a')['keys']), 2)
        self.assertNotIn('sk-private', self.path.read_text())
        with self.assertRaises(mk.ModelKeyError): self.store.select('b', first['id'])
        self.assertEqual(self.store.choices('b')['keys'], [])

    def test_legacy_ciphertext_and_selection_survive_adding_a_key(self):
        self.store.put('a', self.ep, 'legacy-model', 'sk-legacy-secret-key-5678')
        legacy = json.loads(self.path.read_text())['accounts']['a']
        self.add(); self.assertEqual(self.store.open('a')['model'], 'legacy-model')
        self.assertEqual(json.loads(self.path.read_text())['accounts']['a']['profiles']['legacy'], legacy)
        self.store.remove_profile('a', 'key:legacy')
        self.assertEqual(self.store.choices('a')['selected'], 'lumina-default')
        self.assertEqual(len(self.store.choices('a')['keys']), 1)

    def test_selected_relay_uses_personal_route_only_when_selected(self):
        first = self.add(); self.store.select('a', first['id'])
        relay = mk.ModelRelay(self.store, lambda a: True)
        with patch.object(relay, 'chat', return_value='personal') as call:
            self.assertEqual(relay.selected_chat('a', 'cell-credential', b'{}'), 'personal'); call.assert_called_once()
        self.store.select('a', 'lumina-default')
        response = Mock(status=200); response.getheader.return_value = 'application/json'
        connection = Mock(); connection.getresponse.return_value = response
        with patch.object(mk.http.client, 'HTTPConnection', return_value=connection):
            up = relay.selected_chat('a', 'cell-credential', b'{"model":"untrusted-name","messages":[]}')
            args = connection.request.call_args.args
            self.assertEqual(json.loads(args[2])['model'], 'claude-sonnet-5-5')
            self.assertEqual(args[3]['Authorization'], 'Bearer cell-credential')
            self.assertNotIn('sk-private', str(connection.request.call_args)); up.close()

    def test_catalog_expansion_and_invalid_config(self):
        catalog = Path(self.tmp.name) / 'catalog.json'
        catalog.write_text(json.dumps({'models': [model_catalog.DEFAULT, {'id': 'lumina-next', 'name': 'Next', 'model': 'next-model'}]}))
        with patch.dict('os.environ', {'AGENTAI_MODEL_CATALOG_FILE': str(catalog)}):
            self.store.select('a', 'lumina-next'); self.assertEqual(len(model_catalog.models()), 2)
            catalog.write_text('{bad'); self.assertEqual(model_catalog.models(), [model_catalog.DEFAULT])
            with self.assertRaises(mk.ModelKeyError): self.store.select('a', 'lumina-next')

    def test_profile_limit_is_enforced(self):
        for _ in range(20): self.add()
        with self.assertRaises(mk.ModelKeyError): self.add()
        self.assertEqual(len(self.store.choices('a')['keys']), 20)

    def test_selection_fails_closed_on_billing_mismatch_and_corrupt_store(self):
        relay = mk.ModelRelay(self.store, lambda a: True, admission=lambda account, personal: False)
        with self.assertRaises(mk.RelayError) as err:
            relay.selected_chat('a', 'cell', b'{"messages":[]}')
        self.assertEqual(err.exception.code, 'admission_mismatch')
        self.path.write_text('{broken')
        with self.assertRaises(mk.RelayError) as err:
            relay.selected_chat('a', 'cell', b'{"messages":[]}')
        self.assertEqual(err.exception.status, 503)
        with self.assertRaises(mk.ModelKeyError): self.add()
        self.assertEqual(self.path.read_text(), '{broken')
