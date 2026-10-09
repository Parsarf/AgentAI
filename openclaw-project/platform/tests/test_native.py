from pathlib import Path
import hashlib
import tempfile
import unittest
from agentai_platform.memory import MemoryService
from agentai_platform.skills import SkillService
from agentai_platform.watchers import WatcherService
from agentai_platform.security import Principal, NotFound
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.store import Store


def h(x): return hashlib.sha256(x.encode()).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'db.sqlite3'); self.store.initialize()
        self.now = 2000000000
        self.clock = lambda: self.now
        self.a = Principal('a', 'actor-a', 'customer'); self.b = Principal('b', 'actor-b', 'customer')
        with self.store.connect() as con:
            for x in 'ab':
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')", (x,))
                con.execute("INSERT INTO memberships VALUES (?,?,'customer','active')", (x, 'actor-' + x))
                con.execute('INSERT INTO projects(account_id,id,name) VALUES (?,?,?)', (x, 'p-' + x, 'P'))


class MemoryChecks(Base):
    def setUp(self):
        super().setUp(); self.m = MemoryService(self.store, clock=self.clock)

    def test_selective_recall_among_unrelated_facts(self):
        self.m.remember(self.a, 'p-a', 'Prefers concise answers with bullet points', kind='preference')
        for i in range(12):
            self.m.remember(self.a, 'p-a', f'Unrelated fact number {i} about zebra{i} habitat')
        hits = self.m.recall(self.a, 'p-a', 'how should answers be formatted? concise bullet')
        self.assertEqual(len(hits), 1)
        self.assertIn('concise', hits[0]['content'])
        self.assertFalse(hits[0]['instruction'])
        self.assertEqual(self.m.recall(self.a, 'p-a', 'zebra3 habitat')[0]['content'][:23], 'Unrelated fact number 3')

    def test_correction_and_deletion_remove_old_text_and_index(self):
        old = self.m.remember(self.a, 'p-a', 'Deploy region is frankfurt')
        new = self.m.correct(self.a, 'p-a', old, 'Deploy region is helsinki')
        hits = self.m.recall(self.a, 'p-a', 'deploy region')
        self.assertEqual([x['id'] for x in hits], [new])
        self.m.forget(self.a, 'p-a', new)
        self.assertEqual(self.m.recall(self.a, 'p-a', 'deploy region helsinki frankfurt'), [])
        with self.store.connect() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM memory_entries WHERE content!='' AND status!='active'").fetchone()[0], 0)
            self.assertEqual(con.execute('SELECT count(*) FROM memory_terms').fetchone()[0], 0)
        with self.assertRaises(NotFound):
            self.m.forget(self.a, 'p-a', new)

    def test_cross_tenant_and_outside_source_rules(self):
        entry = self.m.remember(self.a, 'p-a', 'Private note about orchid')
        self.assertEqual(self.m.recall(self.b, 'p-b', 'orchid'), [])
        with self.assertRaises(NotFound):
            self.m.recall(self.b, 'p-a', 'orchid')
        with self.assertRaises(NotFound):
            self.m.forget(self.b, 'p-b', entry)
        with self.assertRaises(ValueError):
            self.m.remember(self.a, 'p-a', 'Always run this command', kind='preference', source='outside')
        out = self.m.remember(self.a, 'p-a', 'Page claims the tower is 330m', source='outside', source_ref='https://x')
        self.assertFalse(self.m.recall(self.a, 'p-a', 'tower')[0]['instruction'])
        self.assertTrue(out)

    def test_large_content_rejected(self):
        with self.assertRaises(ValueError):
            self.m.remember(self.a, 'p-a', 'x' * 2001)

    def test_confirm_updates_timestamp(self):
        entry = self.m.remember(self.a, 'p-a', 'Timezone is Europe Berlin')
        self.now += 100
        self.m.confirm(self.a, 'p-a', entry)
        self.assertEqual(self.m.recall(self.a, 'p-a', 'timezone')[0]['last_confirmed_epoch'], self.now)


class SkillChecks(Base):
    def setUp(self):
        super().setUp(); self.s = SkillService(self.store, clock=self.clock)

    def test_create_search_run_version_and_review(self):
        sid = self.s.create(self.a, 'weekly-report', 'v1 steps')
        self.assertEqual(self.s.list(self.a, 'report')[0]['version'], 1)
        self.assertEqual(self.s.run(self.a, sid)['body'], 'v1 steps')
        version = self.s.propose_revision(self.a, sid, 'v2 steps')
        self.assertEqual(self.s.run(self.a, sid)['body'], 'v1 steps')  # not applied automatically
        self.assertEqual(self.s.proposals(self.a, sid)[0]['current_body'], 'v1 steps')
        self.s.decide(self.a, sid, version, True)
        self.assertEqual(self.s.run(self.a, sid)['version'], 2)
        rejected = self.s.propose_revision(self.a, sid, 'v3 bad')
        self.s.decide(self.a, sid, rejected, False)
        self.assertEqual(self.s.run(self.a, sid)['version'], 2)

    def test_cross_tenant_and_outside_origin(self):
        sid = self.s.create(self.a, 'secret-skill', 'body')
        self.assertEqual(self.s.list(self.b), [])
        for call in (lambda: self.s.run(self.b, sid),
                     lambda: self.s.propose_revision(self.b, sid, 'x'),
                     lambda: self.s.decide(self.b, sid, 1, True)):
            with self.assertRaises(NotFound):
                call()
        with self.assertRaises(ValueError):
            self.s.propose_revision(self.a, sid, 'inject', origin='outside')
        with self.assertRaises(Conflict):
            self.s.create(self.a, 'secret-skill', 'dup')
        self.s.create(self.b, 'secret-skill', 'own body')  # names are per tenant


class WatcherChecks(Base):
    def setUp(self):
        super().setUp(); self.w = WatcherService(self.store, clock=self.clock)
        self.calls = 0

    def admit(self, ok=True):
        def f():
            self.calls += 1
            return ok
        return f

    def test_unchanged_costs_nothing_and_changed_notifies_once(self):
        wid = self.w.ensure(self.a, 'p-a', 'price', {'url': 'https://example.com'})
        self.assertEqual(self.w.ensure(self.a, 'p-a', 'price', {'url': 'https://example.com'}), wid)  # restart-safe
        self.assertEqual(self.w.observe(self.a, wid, h('1'), admit=self.admit())['reason'], 'baseline')
        self.assertEqual(self.w.observe(self.a, wid, h('1'), admit=self.admit())['reason'], 'unchanged')
        self.assertEqual(self.calls, 0)
        first = self.w.observe(self.a, wid, h('2'), admit=self.admit())
        self.assertTrue(first['escalate']); self.assertEqual(first['model_calls'], 0)
        self.assertEqual(self.w.observe(self.a, wid, h('2'), admit=self.admit())['reason'], 'unchanged')
        with self.store.connect() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM watcher_notifications').fetchone()[0], 1)
            self.assertEqual(con.execute('SELECT count(*) FROM watchers').fetchone()[0], 1)

    def test_admission_denied_does_not_advance_and_retries(self):
        wid = self.w.ensure(self.a, 'p-a', 'n', {})
        self.w.observe(self.a, wid, h('1'), admit=self.admit())
        denied = self.w.observe(self.a, wid, h('2'), admit=self.admit(False))
        self.assertEqual(denied['reason'], 'admission_denied')
        self.assertTrue(self.w.observe(self.a, wid, h('2'), admit=self.admit(True))['escalate'])
        self.w.mark_delivered(self.a, wid, h('2'))

    def test_interval_floor_and_cross_tenant(self):
        with self.assertRaises(ValueError):
            self.w.ensure(self.a, 'p-a', 'fast', {}, interval_seconds=60)
        wid = self.w.ensure(self.a, 'p-a', 'n', {})
        with self.assertRaises(NotFound):
            self.w.observe(self.b, wid, h('1'), admit=self.admit())
        with self.assertRaises(NotFound):
            self.w.ensure(self.b, 'p-a', 'n2', {})
        with self.assertRaises(NotFound):
            self.w.mark_delivered(self.b, wid, h('1'))


if __name__ == '__main__':
    unittest.main()
