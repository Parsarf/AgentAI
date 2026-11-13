"""Settings → Memory over HTTP: scoped to the signed-in account, off unless the owner's switch is on and the server is configured, deletes really delete."""
import contextlib
import io
import os
import stat
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import connection
from django.test import Client, TestCase, override_settings

from agentai_platform import longterm_memory as ltm
from tests.test_longterm_memory import FakeIndex
from . import longterm
from .store import AccountStore
from .models import Identity
from .services import consume, token_for
from .tests import PASSWORD, AccountBoundaryTests


class MemoryHTTPChecks(TestCase):
    new_client = AccountBoundaryTests.new_client
    post = AccountBoundaryTests.post

    def setUp(self):
        self.output = io.StringIO(); redirect = contextlib.redirect_stdout(self.output); redirect.__enter__(); self.addCleanup(redirect.__exit__, None, None, None)
        self.clients, self.accounts = [], []
        for email in ('mem-one@example.invalid', 'mem-two@example.invalid'):
            call_command('onboard_trial', email=email, stdout=self.output)
            user = User.objects.get(email=email); consume(token_for(user, 'onboarding'), 'onboarding', PASSWORD, uuid.uuid4())
            client = self.new_client(); self.assertEqual(self.post(client, '/auth/login', {'email': email, 'password': PASSWORD}).status_code, 200)
            self.clients.append(client); self.accounts.append(Identity.objects.get(user=user).account_id)
        self.dir = tempfile.TemporaryDirectory(); self.addCleanup(self.dir.cleanup)
        d = Path(self.dir.name)
        self.switch, self.secret = d / 'switch.json', d / 'bank-secret'
        self.secret.write_text('x' * 40); os.chmod(self.secret, 0o600)
        self.switch.write_text('{"long_term_memory": true}')
        self.index = FakeIndex()
        real = ltm.HindsightClient
        patcher = patch.object(ltm, 'HindsightClient', lambda url, key='', **kw: real(url, key, transport=self.index))
        patcher.start(); self.addCleanup(patcher.stop)
        overrides = override_settings(LTM_SWITCH_FILE=str(self.switch), HINDSIGHT_URL='http://hindsight:8888', HINDSIGHT_KEY_FILE='', HINDSIGHT_BANK_SECRET_FILE=str(self.secret))
        overrides.enable(); self.addCleanup(overrides.disable)
        self.memory = longterm.build()

    def listing(self, i):
        return self.clients[i].get('/v1/longterm-memory', secure=True)

    def test_it_is_off_unless_the_switch_the_server_and_the_secret_are_all_in_place(self):
        self.memory.remember(self.accounts[0], 'Prefers aisle seats')
        self.assertEqual(self.listing(0).json()['memories'][0]['content'], 'Prefers aisle seats')
        for content in ('{}', '{"long_term_memory": false}', '{"long_term_memory": []}', 'not json'):
            self.switch.write_text(content)
            self.assertEqual(self.listing(0).json(), {'available': False, 'memories': []}, content)
        self.switch.write_text('{"long_term_memory": true}')
        for name, value in (('HINDSIGHT_URL', ''), ('HINDSIGHT_BANK_SECRET_FILE', ''), ('HINDSIGHT_BANK_SECRET_FILE', str(Path(self.dir.name) / 'missing'))):
            with self.subTest(name=name, value=value), override_settings(**{name: value}):
                self.assertEqual(self.listing(0).json()['available'], False)
                self.assertEqual(self.post(self.clients[0], f'/v1/longterm-memory/{self.memory.entries(self.accounts[0])[0]["id"]}/forget', {}).status_code, 409)
        self.assertEqual(len(self.memory.entries(self.accounts[0])), 1)                      # off never deletes anything

    def test_a_group_readable_secret_file_is_not_used(self):
        os.chmod(self.secret, 0o640)
        self.assertIsNone(longterm.build())
        os.chmod(self.secret, 0o600); link = Path(self.dir.name) / 'link'; os.symlink(self.secret, link)
        with override_settings(HINDSIGHT_BANK_SECRET_FILE=str(link)):
            self.assertIsNone(longterm.build())

    def test_each_customer_sees_only_their_own_memory(self):
        self.memory.remember(self.accounts[0], 'Prefers aisle seats')
        self.memory.remember(self.accounts[1], 'Allergic to peanuts')
        one, two = self.listing(0).json()['memories'], self.listing(1).json()['memories']
        self.assertEqual([m['content'] for m in one], ['Prefers aisle seats'])
        self.assertEqual([m['content'] for m in two], ['Allergic to peanuts'])
        self.assertNotIn('peanuts', self.listing(0).content.decode())

    def test_a_customer_can_delete_their_own_entry_but_not_anothers(self):
        mine = self.memory.remember(self.accounts[0], 'Prefers aisle seats')
        theirs = self.memory.remember(self.accounts[1], 'Allergic to peanuts')
        self.assertEqual(self.post(self.clients[0], f'/v1/longterm-memory/{theirs}/forget', {}).status_code, 404)
        self.assertEqual(len(self.memory.entries(self.accounts[1])), 1)
        r = self.post(self.clients[0], f'/v1/longterm-memory/{mine}/forget', {})
        self.assertEqual((r.status_code, r.json()), (200, {'ok': True, 'pending': False}))
        self.assertEqual(self.listing(0).json()['memories'], [])
        self.assertEqual(self.post(self.clients[0], f'/v1/longterm-memory/{mine}/forget', {}).status_code, 404)
        self.assertEqual(self.memory.recall(self.accounts[0], 'aisle seats'), [])

    def test_delete_everything_clears_only_this_account(self):
        for text in ('Prefers aisle seats', 'Works in the Berlin office'):
            self.memory.remember(self.accounts[0], text)
        self.memory.remember(self.accounts[1], 'Allergic to peanuts')
        r = self.post(self.clients[0], '/v1/longterm-memory/forget-all', {})
        self.assertEqual((r.status_code, r.json()['pending']), (200, False))
        self.assertEqual(self.listing(0).json()['memories'], [])
        self.assertEqual(len(self.listing(1).json()['memories']), 1)
        self.assertNotIn(self.memory.bank(self.accounts[0]), self.index.banks)

    def test_a_delete_the_index_cannot_confirm_still_hides_the_entry_and_is_finished_by_the_sweep(self):
        entry = self.memory.remember(self.accounts[0], 'Prefers aisle seats')
        self.index.fail = {('DELETE', 'document')}
        r = self.post(self.clients[0], f'/v1/longterm-memory/{entry}/forget', {})
        self.assertEqual((r.status_code, r.json()), (200, {'ok': True, 'pending': True}))
        self.assertEqual(self.listing(0).json()['memories'], [])
        self.index.fail = set()
        call_command('memory_sweep', stdout=self.output)
        self.assertIn('closed 1', self.output.getvalue())
        self.assertNotIn(entry, self.index.banks[self.memory.bank(self.accounts[0])])

    def test_erase_account_command_removes_the_whole_bank(self):
        self.memory.remember(self.accounts[0], 'Prefers aisle seats')
        call_command('memory_sweep', erase_account=self.accounts[0], stdout=self.output)
        self.assertNotIn(self.memory.bank(self.accounts[0]), self.index.banks)
        self.assertEqual(self.memory.entries(self.accounts[0]), [])

    def test_signed_out_and_wrong_method_are_refused(self):
        anonymous = self.new_client()
        self.assertEqual(anonymous.get('/v1/longterm-memory', secure=True).status_code, 401)
        self.assertEqual(self.post(anonymous, '/v1/longterm-memory/forget-all', {}).status_code, 401)
        self.assertEqual(self.clients[0].get('/v1/longterm-memory/forget-all', secure=True).status_code, 405)
