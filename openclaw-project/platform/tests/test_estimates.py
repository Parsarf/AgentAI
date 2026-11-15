"""Estimates come from what similar finished tasks took, as a range, or not at all (roadmap #9)."""
import tempfile
import unittest
from pathlib import Path

from agentai_platform import estimates
from agentai_platform.store import Store

NOW = 2000000000


class Checks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 's' / 'db.sqlite3'); self.store.initialize()
        self.n = 0
        with self.store.connect() as con:
            for a in ('a', 'b'):
                con.execute("INSERT INTO accounts(id,status) VALUES (?,'active')", (a,))
                con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES (?,?,1,'ready')", (a, 'd-' + a))
                con.execute("INSERT INTO projects(account_id,id,name) VALUES (?,?,'P')", (a, 'p-' + a))
                con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES (?,?,?,?)", (a, 'p-' + a, 'c-' + a, 'd-' + a))
                con.execute("INSERT INTO entitlements VALUES (?,?,'t','trial','{}',datetime(?,'unixepoch'))", (a, 'e-' + a, NOW + 10 ** 6))

    def task(self, account, seconds, cost, *, intent='chat', goal=0, state='completed', outcome='completed', age=1000):
        self.n += 1
        rid, start = f'r{self.n}', NOW - age - self.n
        with self.store.connect() as con:
            con.execute('''INSERT INTO customer_requests(account_id,id,actor_id,project_id,conversation_id,idempotency_key,payload_hash,message,state,created_epoch,intent,goal_mode,outcome)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''', (account, rid, 'x', 'p-' + account, 'c-' + account, rid, 'h', 'm', state, start, intent, goal, outcome))
            con.execute('''INSERT INTO chat_deliveries(account_id,request_id,attempt,idempotency_key,payload_hash,state,native_operation_id,created_epoch,updated_epoch,ended_epoch,kind,payload)
                VALUES (?,?,1,?,?,'completed',?,?,?,?,'turn','p')''', (account, rid, rid + '-a1', 'h', rid + '-a1', start, start, start + seconds))
            con.execute("INSERT INTO tasks(account_id,project_id,conversation_id,id,state,budget_microusd) VALUES (?,?,?,?,'completed',1)", (account, 'p-' + account, 'c-' + account, rid))
            con.execute("INSERT INTO task_reservations VALUES (?,?,?,?,?,?,'settled',?)", (account, rid, rid, 'h', 'e-' + account, 5, start))
            con.execute('INSERT INTO provider_receipts VALUES (?,?,?,?,?,?,?,?)', (account, rid, 'p', 'q' + rid, 'a' * 64, 'v', cost, start))

    def get(self, account, kind):
        with self.store.connect() as con:
            return estimates.estimate(con, account, kind, now=NOW)

    def test_too_little_history_gives_nothing(self):
        for _ in range(estimates.MIN_OWN - 1):
            self.task('a', 30, 1000)
        self.assertIsNone(self.get('a', 'chat'))
        with self.assertRaises(ValueError):
            self.get('a', 'everything')

    def test_enough_of_your_own_history_gives_a_range_from_your_tasks(self):
        for seconds in (10, 20, 30, 40, 200):
            self.task('a', seconds, seconds * 100)
        for _ in range(30):
            self.task('b', 900, 999999)                                # another account's very different tasks do not move a's range
        got = self.get('a', 'chat')
        self.assertEqual((got['scope'], got['based_on']), ('yours', 5))
        self.assertEqual(got['seconds'], {'typical': 30, 'upper': 200})
        self.assertEqual(got['cost_microusd'], {'typical': 3000, 'upper': 20000})

    def test_a_new_account_borrows_numbers_from_everyone_and_only_numbers(self):
        for _ in range(estimates.MIN_ALL):
            self.task('b', 60, 5000)
        got = self.get('a', 'chat')
        self.assertEqual((got['scope'], got['based_on'], got['seconds']['typical']), ('all', estimates.MIN_ALL, 60))
        self.assertEqual(set(got), {'kind', 'based_on', 'scope', 'seconds', 'cost_microusd'})

    def test_only_finished_successful_recent_tasks_of_the_same_kind_count(self):
        for _ in range(5):
            self.task('a', 30, 100)
        self.task('a', 9000, 1, state='failed', outcome='failed')
        self.task('a', 9000, 1, outcome='partial')
        self.task('a', 9000, 1, intent='browse')
        self.task('a', 9000, 1, goal=1)
        self.task('a', 9000, 1, age=estimates.WINDOW_SECONDS + 10)
        self.assertEqual(self.get('a', 'chat')['seconds'], {'typical': 30, 'upper': 30})
        self.assertIsNone(self.get('a', 'goal'))
        self.assertEqual(estimates.kind_of('goal_continue', 0), 'goal'); self.assertEqual(estimates.kind_of('chat', 1), 'goal')
        self.assertEqual(estimates.kind_of('browse', 0), 'browse'); self.assertEqual(estimates.kind_of('odd', 0), 'chat')

    def test_the_hit_rate_says_how_often_the_upper_bound_held(self):
        for i in range(estimates.MIN_ALL + 10):
            self.task('a', 50, 100)
        self.task('a', 5000, 100)                                      # one task far outside what came before
        with self.store.connect() as con:
            rate = estimates.hit_rate(con, 'chat', now=NOW)
        self.assertEqual((rate['checked'], rate['within_upper']), (11, 10))


if __name__ == '__main__':
    unittest.main()
