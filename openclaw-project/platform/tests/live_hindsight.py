"""Long-term memory against a REAL Hindsight server. Skipped unless AGENTAI_LIVE_HINDSIGHT_URL is set (the normal suite never needs a server).

    AGENTAI_LIVE_HINDSIGHT_URL=http://127.0.0.1:8888 [AGENTAI_LIVE_HINDSIGHT_KEY=...] python -m unittest tests.live_hindsight

Uses throwaway accounts and a throwaway bank secret, and removes every bank it created. Run it before turning the feature on (deploy/LONG_TERM_MEMORY.md)."""
import os
import tempfile
import unittest
import uuid
from pathlib import Path

from agentai_platform.longterm_memory import HindsightClient, HindsightError, LongTermMemory
from agentai_platform.store import Store

URL = os.environ.get('AGENTAI_LIVE_HINDSIGHT_URL', '')
KEY = os.environ.get('AGENTAI_LIVE_HINDSIGHT_KEY', '')


@unittest.skipUnless(URL, 'AGENTAI_LIVE_HINDSIGHT_URL is not set')
class Live(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'db.sqlite3'); self.store.initialize()
        self.run_id = uuid.uuid4().hex[:8]
        self.a, self.b = 'live-a-' + self.run_id, 'live-b-' + self.run_id
        with self.store.connect() as con:
            for x in (self.a, self.b):
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')", (x,))
        self.client = HindsightClient(URL, KEY, timeout=120)
        self.memory = LongTermMemory(self.store, self.client, os.urandom(32))
        self.addCleanup(self.cleanup_banks)

    def cleanup_banks(self):
        for x in (self.a, self.b):
            try:
                self.client.delete_bank(self.memory.bank(x))
            except HindsightError:
                pass

    def texts(self, account, query):
        return [h['text'] for h in self.memory.recall(account, query)]

    def test_isolation_recall_delete_and_rebuild_on_a_real_server(self):
        m, a, b = self.memory, self.a, self.b
        seat = m.remember(a, 'Prefers aisle seats on long flights', kind='preference')
        m.remember(a, 'Works in the Berlin office on Tuesdays')
        peanuts = m.remember(b, 'Is allergic to peanuts')

        # meaning, not just words: a differently worded question finds the note
        self.assertTrue(any('aisle' in t for t in self.texts(a, 'where does this person like to sit on a plane?')), self.texts(a, 'where does this person like to sit on a plane?'))
        # nothing crosses between accounts, in either direction
        for q in ('aisle seats flights', 'Berlin office', 'plane seat preference'):
            self.assertEqual([t for t in self.texts(b, q) if 'aisle' in t or 'Berlin' in t], [], q)
        for q in ('peanuts allergy', 'is this person allergic to anything?'):
            self.assertEqual([t for t in self.texts(a, q) if 'peanut' in t.lower()], [], q)
        self.assertTrue(any('peanut' in t.lower() for t in self.texts(b, 'peanuts allergy')))
        # a bank nobody has written to remembers nothing and is not created by a read
        fresh = 'live-c-' + self.run_id
        with self.store.connect() as con:
            con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')", (fresh,))
        self.assertEqual(m.recall(fresh, 'aisle seats'), [])

        # delete one note: gone from the ledger list and from recall, the other note stays
        m.forget(a, seat)
        self.assertEqual([e['content'] for e in m.entries(a)], ['Works in the Berlin office on Tuesdays'])
        self.assertEqual([t for t in self.texts(a, 'aisle seats on long flights') if 'aisle' in t], [])
        self.assertTrue(any('Berlin' in t for t in self.texts(a, 'Berlin office')))

        # the index lost everything (new server): rebuild one account from the ledger
        self.client.delete_bank(m.bank(a))
        self.assertEqual(m.recall(a, 'Berlin office'), [])
        self.assertEqual(m.reindex(a), 1)
        self.assertTrue(any('Berlin' in t for t in self.texts(a, 'Berlin office')))
        self.assertEqual([t for t in self.texts(a, 'aisle seats') if 'aisle' in t], [])         # the deleted note does not come back
        self.assertTrue(any('peanut' in t.lower() for t in self.texts(b, 'peanuts')))            # b untouched throughout

        # delete everything: the whole bank is gone, the other account is not
        m.forget_all(a)
        self.assertEqual(m.recall(a, 'Berlin office'), [])
        self.assertEqual(m.entries(a), [])
        self.assertTrue(any('peanut' in t.lower() for t in self.texts(b, 'peanuts')))
        m.forget(b, peanuts)
        self.assertEqual([t for t in self.texts(b, 'peanuts') if 'peanut' in t.lower()], [])

    def test_a_wrong_key_is_refused_when_the_server_requires_one(self):
        if not KEY:
            self.skipTest('no key configured; the server is open')
        bad = LongTermMemory(self.store, HindsightClient(URL, 'definitely-not-the-key'), os.urandom(32))
        with self.assertRaises(HindsightError):
            bad.remember(self.a, 'Should never be stored')
        self.assertEqual(self.memory.entries(self.a), [])


if __name__ == '__main__':
    unittest.main()
