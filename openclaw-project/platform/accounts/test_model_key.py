import json
import tempfile
from pathlib import Path
from unittest import mock
from django.test import TestCase, override_settings
from agentai_platform import model_keys as mk
from .models import Audit
from .tests import AccountBoundaryTests

KEY = 'sk-live-customer-key-0123456789'


class ModelKeyEndpointChecks(TestCase):
    new_client = AccountBoundaryTests.new_client
    post = AccountBoundaryTests.post
    signed = AccountBoundaryTests.signed
    setUp = AccountBoundaryTests.setUp

    def configure(self, engine):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.store_path, engine_path = Path(tmp.name) / 'model-keys.json', Path(tmp.name) / 'engine.json'
        engine_path.write_text(json.dumps(engine))
        overrides = override_settings(MODEL_KEY_STORE=str(self.store_path), ENGINE_FILE=str(engine_path), MODEL_KEY_FILE=''); overrides.enable(); self.addCleanup(overrides.disable)

    BODY = {'base_url': 'https://models.example.org/v1', 'api_key': KEY, 'model': 'gpt-4o-mini'}

    def saved(self, client, body=None, probe=None):
        with mock.patch.object(mk, 'probe', probe or mock.Mock(return_value=None)) as p:
            r = self.post(client, '/v1/model-key/save', body or self.BODY)
        return r, p

    def test_every_route_needs_a_signed_in_customer(self):
        self.configure({'own_model_keys': True}); c = self.new_client()
        self.assertEqual(c.get('/v1/model-key', secure=True).status_code, 401)
        self.assertEqual(self.post(c, '/v1/model-key/save', self.BODY).status_code, 401); self.assertEqual(self.post(c, '/v1/model-key/remove').status_code, 401)

    def test_it_is_off_until_it_is_turned_on_for_the_account(self):
        self.configure({}); a = self.signed()
        self.assertEqual(a.get('/v1/model-key', secure=True).json(), {'available': False, 'configured': False})
        r, probe = self.saved(a); self.assertEqual((r.status_code, r.json()['error']), (409, 'not_available')); probe.assert_not_called(); self.assertFalse(self.store_path.exists())
        self.configure({'own_model_keys': ['a']}); a, b = self.signed('a'), self.signed('b')
        self.assertTrue(a.get('/v1/model-key', secure=True).json()['available']); self.assertFalse(b.get('/v1/model-key', secure=True).json()['available'])
        self.assertEqual(self.saved(b)[0].status_code, 409)

    def test_saving_tests_the_key_stores_it_encrypted_and_never_returns_it(self):
        self.configure({'own_model_keys': True}); a = self.signed()
        r, probe = self.saved(a)
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json(); self.assertEqual((body['configured'], body['host'], body['model'], body['hint']), (True, 'models.example.org', 'gpt-4o-mini', KEY[-4:]))
        args = probe.call_args.args; self.assertEqual((args[0].base_url, args[1], args[2]), ('https://models.example.org/v1', 'gpt-4o-mini', KEY))     # the endpoint was tested with exactly what was typed
        self.assertNotIn(KEY, r.content.decode()); self.assertNotIn(KEY, json.dumps(dict(r.headers)))
        self.assertNotIn(KEY, self.store_path.read_text()); self.assertNotIn('0123456789', self.store_path.read_text())
        shown = a.get('/v1/model-key', secure=True).json(); self.assertEqual(shown, {'available': True, 'configured': True, 'host': 'models.example.org', 'model': 'gpt-4o-mini', 'hint': KEY[-4:]}); self.assertNotIn(KEY, json.dumps(shown))
        audits = list(Audit.objects.filter(action='model_key.save')); self.assertEqual(len(audits), 1)
        self.assertNotIn(KEY, ' '.join(str(vars(row)) for row in Audit.objects.all()))                                                                      # the audit trail records that it happened, never what
        from .model_key import active
        self.assertTrue(active('a')); self.assertFalse(active('b'))

    def test_a_key_that_fails_the_test_or_a_bad_entry_stores_nothing(self):
        self.configure({'own_model_keys': True}); a = self.signed()
        for body, words in [({**self.BODY, 'base_url': 'http://models.example.org/v1'}, 'https'), ({**self.BODY, 'base_url': 'https://10.0.0.5/v1'}, 'hostname'), ({**self.BODY, 'base_url': 'https://localhost/v1'}, 'hostname'),
                            ({**self.BODY, 'model': 'bad model name'}, 'model name'), ({**self.BODY, 'api_key': 'short'}, 'API key'), ({**self.BODY, 'api_key': 'has a space in it 1234'}, 'API key')]:
            r, probe = self.saved(a, body); self.assertEqual(r.status_code, 422, body); self.assertEqual(r.json()['error'], 'model_key_invalid'); self.assertIn(words, r.json()['message']); probe.assert_not_called()
        self.assertFalse(self.store_path.exists()); self.assertFalse(Audit.objects.filter(action='model_key.save').exists())

    def test_a_key_the_endpoint_refuses_is_not_saved_and_the_reason_is_shown(self):
        self.configure({'own_model_keys': True}); a = self.signed()
        r, _ = self.saved(a, probe=mock.Mock(side_effect=mk.ModelKeyError('Your endpoint refused the API key: Incorrect API key provided.')))
        self.assertEqual((r.status_code, r.json()['message']), (422, 'Your endpoint refused the API key: Incorrect API key provided.'))
        self.assertFalse(self.store_path.exists()); self.assertFalse(Audit.objects.filter(action='model_key.save').exists())
        self.assertEqual(self.post(a, '/v1/model-key/save', {**self.BODY, 'extra': 'x'}).status_code, 400)                                                  # unknown fields are refused
        self.assertEqual(self.post(a, '/v1/model-key/save', {'base_url': 'x'}).status_code, 422)

    def test_saving_again_replaces_and_removing_deletes_for_good(self):
        self.configure({'own_model_keys': True}); a = self.signed(); self.saved(a)
        self.saved(a, {**self.BODY, 'model': 'other-model', 'api_key': 'sk-second-key-9999999999'})
        self.assertEqual(a.get('/v1/model-key', secure=True).json()['model'], 'other-model'); self.assertNotIn(KEY, self.store_path.read_text())
        r = self.post(a, '/v1/model-key/remove'); self.assertEqual((r.status_code, r.json()['removed'], r.json()['configured']), (200, True, False))
        self.assertFalse(a.get('/v1/model-key', secure=True).json()['configured']); self.assertNotIn('other-model', self.store_path.read_text())
        self.assertEqual(Audit.objects.filter(action='model_key.remove').count(), 1)
        self.assertEqual(self.post(a, '/v1/model-key/remove').json()['removed'], False); self.assertEqual(Audit.objects.filter(action='model_key.remove').count(), 1)
        from .model_key import active
        self.assertFalse(active('a'))                                                                                                                       # back under Lumina's limits at once

    def test_one_account_never_sees_or_removes_anothers(self):
        self.configure({'own_model_keys': True}); a, b = self.signed('a'), self.signed('b'); self.saved(a)
        self.assertFalse(b.get('/v1/model-key', secure=True).json()['configured']); self.assertFalse(self.post(b, '/v1/model-key/remove').json()['removed'])
        self.assertTrue(a.get('/v1/model-key', secure=True).json()['configured'])

    def test_saving_is_rate_limited_so_a_wrong_key_cannot_be_hammered(self):
        self.configure({'own_model_keys': True}); a = self.signed()
        codes = [self.saved(a, probe=mock.Mock(side_effect=mk.ModelKeyError('no')))[0].status_code for _ in range(8)]
        self.assertEqual(codes[:6], [422] * 6); self.assertEqual(codes[6:], [429, 429])

    def test_anything_unreadable_means_lumina_limits_apply(self):
        self.configure({'own_model_keys': True}); self.saved(self.signed())
        from .model_key import active
        self.assertTrue(active('a')); self.store_path.write_text('{broken'); self.assertFalse(active('a'))
        with override_settings(ENGINE_FILE='/nonexistent/engine.json'): self.assertFalse(active('a'))
