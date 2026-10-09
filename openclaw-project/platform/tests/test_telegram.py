import json
import threading
from pathlib import Path
import tempfile
import unittest
from agentai_platform.budget import BudgetLedger
from agentai_platform.chat import ChatService, FixedRoute
from agentai_platform.request_queue import RequestQueue
from agentai_platform.security import Principal
from agentai_platform.telegram import TelegramService, TelegramBotApi, NullTransport
from agentai_platform.store import Store

LIMITS = {'period_start_epoch': 2000000000 - 100000, 'period_microusd': 100000,
          'daily_microusd': 100000, 'task_microusd': 100000, 'max_queued_tasks': 3}


class FakeTransport:
    def __init__(self, mode='ok'):
        self.mode = mode
        self.sent = []
        self.counter = 100

    def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))
        if self.mode == 'network':
            raise ConnectionError('cable cut')
        if self.mode == 'reject':
            raise LookupError('telegram rejected message')
        self.counter += 1
        return self.counter


class TelegramChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'state' / 'db.sqlite3');self.store.initialize()
        self.now = 2000000000
        self.transport = FakeTransport()
        self.build_service()

    def build_service(self):
        ledger = BudgetLedger(self.store, service_limit_microusd=10 ** 9, clock=lambda:self.now)
        chat = ChatService(self.store, queue=RequestQueue(self.store, clock=lambda:self.now),
                           ledger=ledger, pricer=FixedRoute(500), clock=lambda:self.now)
        self.service = TelegramService(self.store, chat=chat, transport=self.transport,
                                       bot_username='agentai_testbot', clock=lambda:self.now)
        self.principal = self.service.principal = Principal('a', 'actor-a', 'customer')
        return self.service

    def seed(self, accounts=('a', 'b')):
        with self.store.connect() as con:
            for a in accounts:
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')", (a,))
                con.execute("INSERT INTO memberships VALUES (?,?,'customer','active')", (a, 'actor-' + a))
                con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES (?,?,1,'stopped')", (a, 'd-' + a))
                con.execute('INSERT INTO projects(account_id,id,name) VALUES (?,?,?)', (a, 'p-' + a, 'Project ' + a))
                con.execute("INSERT INTO entitlements VALUES (?,?,'test-v1','trial',?,datetime(?,'unixepoch'))",
                            (a, 'e-' + a, json.dumps(LIMITS), self.now + 1000000))

    def update(self, update_id, chat_id, user_id, text, chat_type='private'):
        return {'update_id': update_id, 'message': {'message_id': update_id, 'text': text,
                'chat': {'id': chat_id, 'type': chat_type}, 'from': {'id': user_id, 'username': 'x'}}}

    def link(self, chat_id, user_id, account='a'):
        principal = Principal(account, 'actor-' + account, 'customer')
        code = self.service.create_code(principal)['link'].split('=')[1]
        return self.service.handle_update(self.update(1, chat_id, user_id, '/start ' + code))

    def rows(self, sql, args=()):
        with self.store.connect() as con:
            return con.execute(sql, args).fetchall()

    def test_code_hashed_single_use_and_invalidates_previous(self):
        self.seed()
        first = self.service.create_code(self.principal)
        self.assertTrue(first['link'].startswith('https://t.me/agentai_testbot?start='))
        raw_first = first['link'].split('=')[1]
        second = self.service.create_code(self.principal)
        with self.store.connect() as con:
            stored = con.execute('SELECT code_hash,consumed_epoch FROM telegram_link_codes').fetchall()
        self.assertTrue(all(row['code_hash'] != raw_first for row in stored))
        self.assertTrue(all(row['consumed_epoch'] is not None for row in stored[:-1]))
        self.assertEqual(len(stored), 2)

    def test_link_flow_ack_and_binding(self):
        self.seed()
        outcome = self.link(100, 111)
        self.assertEqual(outcome, 'linked')
        self.assertEqual(self.service.bindings(self.principal)[0]['chat_id'], '100')
        # Raw code never appears in the outbox or transport.
        for chat_id, text in self.transport.sent:
            self.assertNotIn('/start', text)

    def test_expired_reused_and_invalid_codes(self):
        self.seed()
        raw = self.service.create_code(self.principal)['link'].split('=')[1]
        self.service.handle_update(self.update(1, 100, 111, '/start ' + raw))
        # Replay from a different, unlinked chat: the code is already consumed.
        self.assertEqual(self.service.handle_update(self.update(2, 200, 222, '/start ' + raw)), 'code_expired_or_used')
        # Invalid codes are only consumable from unlinked chats.
        self.assertEqual(self.service.handle_update(self.update(3, 300, 333, '/start wrong')), 'invalid_code')
        raw2 = self.service.create_code(self.principal)['link'].split('=')[1]
        self.now += 601
        self.assertEqual(self.service.handle_update(self.update(4, 400, 444, '/start ' + raw2)), 'code_expired_or_used')

    def test_swapped_code_binds_code_owner_and_conflicts(self):
        self.seed()
        code_a = self.service.create_code(Principal('a', 'actor-a', 'customer'))['link'].split('=')[1]
        # Chat 200 belongs to B's operator; A's code claims it (bearer semantics).
        self.assertEqual(self.service.handle_update(self.update(1, 200, 222, '/start ' + code_a)), 'linked')
        self.assertEqual(self.service.bindings(Principal('a', 'actor-a', 'customer'))[0]['chat_id'], '200')
        # B then tries to claim the same chat with B's own code: the chat is
        # already linked, and the reply does not reveal which account.
        code_b = self.service.create_code(Principal('b', 'actor-b', 'customer'))['link'].split('=')[1]
        self.assertEqual(self.service.handle_update(self.update(2, 200, 222, '/start ' + code_b)), 'already_linked')
        self.assertEqual(self.service.bindings(Principal('b', 'actor-b', 'customer')), [])
        # The loss-side race guard: a second consumption while bound conflicts.
        self.assertEqual(self.service._consume_code(200, 222, code_b), 'link_conflict')

    def test_simultaneous_consumption_single_winner(self):
        self.seed()
        raw = self.service.create_code(self.principal)['link'].split('=')[1]
        outcomes = []
        barrier = threading.Barrier(2)

        def attempt(n):
            barrier.wait()
            outcomes.append(self.service.handle_update(self.update(10 + n, 100, 111, '/start ' + raw)))
        threads = [threading.Thread(target=attempt, args=(n,)) for n in range(2)]
        for t in threads:t.start()
        for t in threads:t.join(5)
        self.assertEqual(outcomes.count('linked'), 1)
        self.assertTrue(set(outcomes) <= {'linked', 'code_expired_or_used', 'already_linked'})
        self.assertEqual(len(self.rows('SELECT 1 FROM telegram_links')), 1)

    def test_duplicate_updates_route_once(self):
        self.seed()
        self.link(100, 111)
        first = self.service.handle_update(self.update(50, 100, 111, 'hello agent'))
        second = self.service.handle_update(self.update(50, 100, 111, 'hello agent'))
        self.assertEqual((first, second), ('queued', 'duplicate'))
        self.assertEqual(len(self.rows("SELECT 1 FROM tasks WHERE account_id='a'")), 1)
        self.assertEqual(len(self.rows("SELECT 1 FROM customer_requests WHERE idempotency_key='tg50'")), 1)

    def test_unlinked_denial_and_commands_ignored(self):
        self.seed()
        self.assertEqual(self.service.handle_update(self.update(1, 300, 333, 'do work')), 'unlinked')
        self.assertEqual(len(self.rows('SELECT 1 FROM tasks')), 0)
        self.assertTrue(self.rows("SELECT 1 FROM telegram_outbox WHERE chat_id='300'"))

    def test_messages_land_in_conversation_with_provenance(self):
        self.seed()
        self.link(100, 111)
        self.service.handle_update(self.update(10, 100, 111, 'first request'))
        self.service.handle_update(self.update(11, 100, 111, 'second request'))
        messages = self.service.chat.messages(self.principal, self.rows(
            "SELECT conversation_id FROM customer_requests WHERE idempotency_key='tg10'")[0][0])
        self.assertEqual([m['provenance'] for m in messages['messages']], ['telegram', 'telegram'])
        # Both messages share one conversation; one task each.
        self.assertEqual(len(messages['tasks']), 2)

    def test_project_selection_commands(self):
        self.seed()
        self.link(100, 111)
        self.assertEqual(self.service.handle_update(self.update(20, 100, 111, '/projects')), 'projects')
        self.assertEqual(self.service.handle_update(self.update(21, 100, 111, '/use p-b')), 'use_denied')
        self.assertEqual(self.service.handle_update(self.update(22, 100, 111, '/use p-a')), 'use_ok')
        self.service.handle_update(self.update(30, 100, 111, 'work for a'))
        conversation = self.rows("SELECT conversation_id FROM customer_requests WHERE idempotency_key='tg30'")[0][0]
        self.assertEqual(self.rows('SELECT project_id FROM conversations WHERE id=?', (conversation,))[0][0], 'p-a')
        self.assertEqual(self.service.handle_update(self.update(31, 100, 111, '/use zzz')), 'use_denied')

    def test_suspended_revoked_and_unlinked_denials(self):
        self.seed()
        self.link(100, 111)
        with self.store.connect() as con:
            con.execute("UPDATE accounts SET status='suspended' WHERE id='a'")
        self.assertEqual(self.service.handle_update(self.update(40, 100, 111, 'work')), 'account_unavailable')
        with self.store.connect() as con:
            con.execute("UPDATE accounts SET status='active' WHERE id='a'")
            con.execute("UPDATE memberships SET status='revoked' WHERE account_id='a'")
        self.assertEqual(self.service.handle_update(self.update(41, 100, 111, 'work')), 'account_unavailable')
        with self.store.connect() as con:
            con.execute("UPDATE memberships SET status='active' WHERE account_id='a'")
        self.service.unlink(self.principal, '100')
        self.assertEqual(self.service.handle_update(self.update(42, 100, 111, 'work')), 'unlinked')
        self.assertEqual(len(self.rows('SELECT 1 FROM tasks')), 0)

    def test_budget_denial_cancels_and_acks(self):
        self.seed()
        with self.store.connect() as con:
            limits = dict(LIMITS, period_microusd=100)
            con.execute("UPDATE entitlements SET limits_json=? WHERE account_id='a'", (json.dumps(limits),))
        self.link(100, 111)
        self.assertEqual(self.service.handle_update(self.update(77, 100, 111, 'work')), 'budget_denied')
        self.assertEqual(self.rows("SELECT state FROM customer_requests WHERE idempotency_key='tg77'")[0][0], 'cancelled')
        self.assertEqual(len(self.rows('SELECT 1 FROM tasks')), 0)

    def test_outbox_receipts_and_drain(self):
        self.seed()
        self.link(100, 111)
        self.assertEqual(len(self.transport.sent), 1)
        self.assertEqual(self.rows("SELECT state FROM telegram_outbox WHERE chat_id='100'")[0][0], 'sent')
        self.transport.mode = 'network'
        self.service.transport = self.transport
        self.service.handle_update(self.update(2, 100, 111, 'another'))
        self.assertEqual(self.rows("SELECT state FROM telegram_outbox WHERE chat_id='100' ORDER BY created_epoch")[1][0], 'uncertain')
        self.transport.mode = 'reject'
        self.service.handle_update(self.update(3, 100, 111, 'third'))
        self.assertEqual(self.rows("SELECT state FROM telegram_outbox WHERE chat_id='100' ORDER BY created_epoch")[2][0], 'failed')
        self.transport.mode = 'ok'
        self.service.transport = NullTransport()
        self.service.handle_update(self.update(4, 100, 111, 'fourth'))
        self.assertEqual(self.rows("SELECT state FROM telegram_outbox WHERE chat_id='100' ORDER BY created_epoch")[3][0], 'pending')
        self.service.transport = self.transport
        self.assertEqual(self.service.drain(), 1)
        self.assertEqual(self.rows("SELECT state FROM telegram_outbox WHERE chat_id='100' ORDER BY created_epoch")[3][0], 'sent')

    def test_ignores_groups_attachments_and_non_numeric(self):
        self.seed()
        self.assertEqual(self.service.handle_update(self.update(1, -100, 111, 'group text', chat_type='group')), 'ignored')
        self.assertEqual(self.service.handle_update({'update_id': 2, 'message': {'chat': {'id': 1, 'type': 'private'},
                       'from': {'id': 1}, 'photo': [{}]}, }), 'ignored')
        self.assertEqual(self.service.handle_update({'update_id': 3, 'message': {'chat': {'id': 1, 'type': 'private'},
                       'text': 'no from'}}), 'ignored')
        self.assertEqual(self.service.handle_update({'update_id': 'x'}), 'ignored')
        # Dedup runs before content checks: a replayed update id is a duplicate.
        self.assertEqual(self.service.handle_update(self.update(1, 100, 111, 'dup id different body')), 'duplicate')

    def test_bot_api_token_validation(self):
        with self.assertRaises(ValueError):
            TelegramBotApi('bad token with spaces')
        self.assertTrue(TelegramBotApi('123:abc'))


if __name__ == '__main__':
    unittest.main()
