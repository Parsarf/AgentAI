import unittest
from types import SimpleNamespace
from . import test_chat as fixture
from agentai_platform.genui.runtime import GenUiRuntime
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.security import NotFound


class HistoryChecks(unittest.TestCase):
    setUp = fixture.ChatChecks.setUp
    send = fixture.ChatChecks.send
    rows = fixture.ChatChecks.rows

    def test_search_includes_body_and_is_account_scoped(self):
        with self.store.connect() as con:
            con.execute("INSERT INTO chat_messages(account_id,conversation_id,provenance,content) VALUES ('a','c-a','agent','rare word: narwhal')")
            con.execute("INSERT INTO chat_messages(account_id,conversation_id,provenance,content) VALUES ('b','c-b','agent','private narwhal')")
        self.assertEqual([r['id'] for r in self.service.conversations(self.a, query='narwhal')], ['c-a'])
        self.assertEqual(self.service.conversations(self.a, query='private'), [])
        self.assertEqual(self.service.conversations(self.a, query='%'), [])

    def test_archive_restore_preserves_messages_and_requires_restore_before_send(self):
        self.send()
        self.service.archive_conversation(self.a, 'c-a')
        self.assertEqual(self.service.conversations(self.a), [])
        self.assertEqual([r['id'] for r in self.service.conversations(self.a, archived=True)], ['c-a'])
        self.assertEqual(len(self.service.messages(self.a, 'c-a')['messages']), 1)
        with self.assertRaises(Conflict): self.send(key='archived')
        with self.assertRaises(NotFound): self.service.restore_conversation(self.b, 'c-a')
        self.service.restore_conversation(self.a, 'c-a')
        self.assertEqual(len(self.service.conversations(self.a)), 1)
        self.send(key='restored')

    def test_pages_include_messages_beyond_one_hundred_without_duplicates(self):
        with self.store.connect() as con:
            for i in range(205):
                con.execute("INSERT INTO chat_messages(account_id,conversation_id,provenance,content) VALUES ('a','c-a','agent',?)", (str(i),))
        first = self.service.messages(self.a, 'c-a')
        second = self.service.messages(self.a, 'c-a', after=first['next_after'])
        third = self.service.messages(self.a, 'c-a', after=second['next_after'])
        all_rows = first['messages'] + second['messages'] + third['messages']
        self.assertEqual(len(all_rows), 205)
        self.assertEqual(len({r['id'] for r in all_rows}), 205)
        self.assertTrue(first['has_more']); self.assertFalse(third['has_more'])

    def test_history_is_ordered_by_activity_and_paginated(self):
        other = self.service.create_conversation(self.a, 'p-a')['id']
        with self.store.connect() as con:
            con.execute("INSERT INTO chat_messages(account_id,conversation_id,provenance,content,created_at) VALUES ('a','c-a','agent','older','2026-01-01 00:00:00')")
            con.execute("INSERT INTO chat_messages(account_id,conversation_id,provenance,content,created_at) VALUES ('a',?,'agent','recent','2026-10-13 00:00:00')", (other,))
        self.assertEqual(self.service.conversations(self.a, limit=1)[0]['id'], other)
        self.assertEqual(self.service.conversations(self.a, limit=1, offset=1)[0]['id'], 'c-a')

    def test_request_listing_carries_conversation_link(self):
        out = self.send()
        self.assertEqual(out['conversation_id'], 'c-a')
        self.assertEqual(self.queue.get(self.a)[0]['conversation_id'], 'c-a')

    def test_retry_key_cannot_move_a_request_between_chats(self):
        self.send()
        other = self.service.create_conversation(self.a, 'p-a')['id']
        with self.assertRaises(Conflict):
            self.send(conversation=other)

    def test_followup_context_stays_in_its_chat_and_ignores_later_messages(self):
        with self.store.connect() as con:
            con.execute("INSERT INTO chat_messages(account_id,conversation_id,provenance,content) VALUES ('a','c-a','agent','browser result')")
            con.execute("INSERT INTO chat_messages(account_id,conversation_id,provenance,content) VALUES ('b','c-b','agent','foreign secret')")
        out = self.send(message='Explain that result')
        claim = SimpleNamespace(account_id='a', conversation_id='c-a', request_id=out['id'], message='Explain that result')
        with self.store.connect() as con:
            con.execute("INSERT INTO chat_messages(account_id,conversation_id,provenance,content) VALUES ('a','c-a','customer','later request')")
        runtime = GenUiRuntime(self.store, None)
        text = runtime.outgoing(claim, 'chat', {})
        self.assertIn('browser result', text)
        self.assertNotIn('foreign secret', text); self.assertNotIn('later request', text)
        with self.store.connect() as con:
            con.execute("UPDATE conversations SET native_session_ref='existing-session' WHERE account_id='a' AND id='c-a'")
        self.assertEqual(runtime.outgoing(claim, 'chat', {}), 'Explain that result')
