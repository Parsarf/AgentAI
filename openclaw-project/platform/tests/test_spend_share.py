"""Roadmap #10: every cent the cell's key spent is charged to some request once, however requests overlap."""
import tempfile
import unittest
from pathlib import Path

from agentai_platform.spend_share import SpendShare
from agentai_platform.store import Store

S = SpendShare.walk


class Walk(unittest.TestCase):
    def test_a_request_that_ran_alone_is_charged_exactly_its_end_minus_its_start(self):
        self.assertEqual(S([('a', 'start', 100), ('a', 'end', 350)], 'a'), 250)

    def test_two_requests_that_overlap_share_the_overlap_and_the_total_is_conserved(self):
        marks = [('a', 'start', 0), ('b', 'start', 5), ('a', 'end', 10), ('b', 'end', 15)]            # 1 unit per second
        a, b = S(marks, 'a'), S(marks, 'b')
        self.assertEqual((a, b), (7, 7))                                                                 # 5 alone + 5 shared / 2 = 7 (the half unit is lost to rounding, never added)
        self.assertLessEqual(15 - (a + b), 1)

    def test_three_at_once(self):
        marks = [('a', 'start', 0), ('b', 'start', 0), ('c', 'start', 0), ('a', 'end', 30), ('b', 'end', 30), ('c', 'end', 30)]
        self.assertEqual([S(marks, x) for x in 'abc'], [10, 10, 10])

    def test_a_request_that_started_before_the_one_asked_about_shares_from_its_start_only(self):
        marks = [('a', 'start', 0), ('b', 'start', 40), ('b', 'end', 60), ('a', 'end', 100)]
        self.assertEqual(S(marks, 'b'), 10)                                                              # 40..60 shared with a
        self.assertEqual(S(marks, 'a'), 40 + 10 + 40)

    def test_a_request_still_running_is_charged_up_to_now(self):
        marks = [('a', 'start', 0), ('b', 'start', 10)]
        self.assertEqual(S(marks, 'a', now_spend=30), 10 + 10)                                           # 10 alone, then half of the next 20
        self.assertEqual(S(marks, 'b', now_spend=30), 10)

    def test_no_start_mark_means_the_caller_uses_end_minus_start(self):
        self.assertIsNone(S([('a', 'start', 0)], 'zzz'))

    def test_a_request_that_spent_nothing_costs_nothing(self):
        self.assertEqual(S([('a', 'start', 50), ('a', 'end', 50)], 'a'), 0)


class Stored(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 's' / 'db.sqlite3'); self.store.initialize()
        self.share = SpendShare(self.store, clock=lambda: 2000000000)

    def test_marks_are_kept_once_and_accounts_never_mix(self):
        self.share.mark('x', 'r1', 'start', 0); self.share.mark('x', 'r1', 'start', 999)         # a repeat changes nothing
        self.share.mark('x', 'r1', 'end', 40); self.share.mark('y', 'r9', 'start', 0); self.share.mark('y', 'r9', 'end', 500)
        self.assertEqual(self.share.cost('x', 'r1'), 40)
        self.assertEqual(self.share.cost('y', 'r9'), 500)
        self.assertIsNone(self.share.cost('x', 'r9'))                                                   # another account's request is not this account's
        self.share.mark('x', 'r2', 'start', -5); self.share.mark('x', 'r2', 'frog', 5)
        self.assertIsNone(self.share.cost('x', 'r2'))

    def test_a_request_that_ended_without_a_reading_does_not_share_later_requests_costs(self):
        self.share.mark('x', 'gone', 'start', 100)                               # abandoned: the runtime was unreachable, its end was never read
        self.share.close('x', 'gone')
        self.share.mark('x', 'r', 'start', 500); self.share.mark('x', 'r', 'end', 600)
        self.assertEqual(self.share.cost('x', 'r'), 100)                         # all of it, not half
        self.assertEqual(self.share.cost('x', 'gone'), 0)
        self.share.close('x', 'r'); self.share.close('x', 'never-started')       # closing again, or something that never started, changes nothing
        self.assertEqual(self.share.cost('x', 'r'), 100)
        self.assertIsNone(self.share.cost('x', 'never-started'))

    def test_a_leftover_start_mark_of_a_finished_request_is_ignored(self):
        with self.store.connect() as con:                                       # a request that is over, with a start mark and no end mark (written before `close` existed)
            con.execute("INSERT INTO accounts(id,status) VALUES ('x','active')")
            con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES ('x','d',1,'ready')")
            con.execute("INSERT INTO projects(account_id,id,name) VALUES ('x','p','P')")
            con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES ('x','p','c','d')")
            for rid, state in (('old', 'failed'), ('beside', 'running')):
                con.execute('''INSERT INTO customer_requests(account_id,id,actor_id,project_id,conversation_id,idempotency_key,payload_hash,message,state,created_epoch)
                    VALUES ('x',?,'actor','p','c',?,'h','m',?,1)''', (rid, rid, state))
        self.share.mark('x', 'old', 'start', 100)
        self.share.mark('x', 'r', 'start', 500); self.share.mark('x', 'r', 'end', 600)
        self.assertEqual(self.share.cost('x', 'r'), 100)
        self.share.mark('x', 'beside', 'start', 600); self.share.mark('x', 'r2', 'start', 600); self.share.mark('x', 'r2', 'end', 700)
        self.assertEqual(self.share.cost('x', 'r2'), 50)                         # one that really is still running does share

    def test_overlap_through_the_database(self):
        for who, kind, total in (('a', 'start', 0), ('b', 'start', 5), ('a', 'end', 10), ('b', 'end', 15)):
            self.share.mark('x', who, kind, total)
        self.assertEqual((self.share.cost('x', 'a'), self.share.cost('x', 'b')), (7, 7))


if __name__ == '__main__':
    unittest.main()
