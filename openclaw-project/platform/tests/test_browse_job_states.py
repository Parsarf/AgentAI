"""Browser job states have one definition, an interruption is its own ending that keeps the history, and the record is written by whoever looks."""
import json
import tempfile
import unittest

from agentai_platform.browse import job_states as js
from agentai_platform.browse import service as svc
from tests.test_native_run import Base, OK


class Vocabulary(unittest.TestCase):
    def test_groups(self):
        self.assertLess(set(js.WAITING), set(js.LIVE))
        self.assertEqual(set(js.LIVE) & set(js.FINAL), {'handoff'})                    # over for the loop, still held open for the customer
        self.assertEqual(set(js.OVER), set(js.FINAL) - {'handoff'})
        self.assertIn(js.INTERRUPTED, js.OVER); self.assertNotIn(js.INTERRUPTED, js.FAILED_ATTEMPT)
        self.assertEqual(js.sql_list(('a', 'b')), "('a','b')")

    def test_every_copy_reads_the_one_definition(self):
        from agentai_platform.browse import adapter
        self.assertIs(svc.FINAL, js.FINAL); self.assertIs(adapter.FINALS, js.FINAL)
        client = (__import__('pathlib').Path(__file__).resolve().parents[2] / 'lumina' / 'src' / 'lib' / 'live.ts').read_text()
        listed = client.split('export const LIVE_STATES = [')[1].split(']')[0]
        self.assertEqual(tuple(s.strip().strip("'") for s in listed.split(',')), js.LIVE)       # the web client's list is the server's (it used to lack `asking`)
        self.assertIn('interrupted:', client)


class Records(Base):
    def setUp(self):
        super().setUp()
        self.request = self.say()['id']
        self.queue.claim(owner='w', capacity=OK)
        with self.store.connect() as con:
            con.execute("INSERT INTO browse_runs(account_id,request_id,goal,status,created_epoch,updated_epoch) VALUES ('a',?,?,?,?,?)", (self.request, 'g', 'running', self.now - 100, self.now - 100))

    def run_row(self):
        return dict(self.rows('SELECT * FROM browse_runs')[0])

    def steps(self):
        return [(r['n'], r['kind'], json.loads(r['data_json'])) for r in self.rows('SELECT n,kind,data_json FROM browse_steps ORDER BY n')]

    def test_record_keeps_state_and_steps_and_is_idempotent(self):
        polled = {'state': 'done', 'url': 'https://x.example/', 'answer': 'ok', 'reason': '', 'cost_microusd': 40, 'jev': {'jev_calls': 3, 'jev_acted': 2},
                  'events': [{'n': 1, 'kind': 'step', 'action': 'click'}, {'n': 2, 'kind': 'status', 'state': 'done'}]}
        for _ in range(2):
            with self.store.connect() as con:
                js.record(con, 'a', self.request, polled, offset=5, spent_before=100, now=self.now)
        row = self.run_row()
        self.assertEqual((row['status'], row['answer'], row['estimated_cost_microusd'], row['jev_asked'], row['jev_agree']), ('done', 'ok', 140, 3, 2))
        self.assertEqual([(n, kind) for n, kind, _ in self.steps()], [(6, 'step'), (7, 'status')])           # numbered after the request's earlier steps, once

    def test_record_can_leave_the_cost_alone(self):
        with self.store.connect() as con:
            con.execute('UPDATE browse_runs SET estimated_cost_microusd=77')
            js.record(con, 'a', self.request, {'state': 'done', 'cost_microusd': 5, 'events': []}, spent_before=None, now=self.now)
        self.assertEqual(self.run_row()['estimated_cost_microusd'], 77)

    def test_an_unfinished_record_becomes_interrupted_with_its_history_kept(self):
        with self.store.connect() as con:
            js.record(con, 'a', self.request, {'state': 'running', 'events': [{'n': 1, 'kind': 'step', 'action': 'click'}]}, now=self.now - 100)
            self.assertTrue(js.mark_interrupted(con, 'a', self.request, now=self.now))
            self.assertFalse(js.mark_interrupted(con, 'a', self.request, now=self.now))                      # once
        row = self.run_row()
        self.assertEqual(row['status'], 'interrupted'); self.assertIn('not resumed', row['reason'])
        self.assertEqual([(n, kind) for n, kind, _ in self.steps()], [(1, 'step'), (2, 'status')])           # what was done is still there, and the ending is recorded after it
        self.assertEqual(self.steps()[-1][2]['state'], 'interrupted')

    def test_a_finished_record_a_young_one_and_another_accounts_are_never_touched(self):
        with self.store.connect() as con:
            self.assertFalse(js.mark_interrupted(con, 'b', self.request, now=self.now))
            con.execute('UPDATE browse_runs SET updated_epoch=?', (self.now - 5,))
            self.assertFalse(js.mark_interrupted(con, 'a', self.request, now=self.now))                      # a job this young may still be starting
            con.execute("UPDATE browse_runs SET status='done',updated_epoch=?", (self.now - 100,))
            self.assertFalse(js.mark_interrupted(con, 'a', self.request, now=self.now))
        self.assertEqual(self.run_row()['status'], 'done')


class ForgettingFinishedJobs(unittest.TestCase):
    def test_a_finished_job_lets_go_of_its_steps_after_a_while_and_still_answers(self):
        clock = [1000.0]
        s = svc.BrowseService(spawn=lambda j, o: None, root=tempfile.mkdtemp(), jev_mode='off', clock=lambda: clock[0])
        job = svc.Job('acct', 'a' * 32, 'goal text', None, 1000, 10, 60)
        job.state, job.answer, job.cost, job.ended = 'done', 'the answer', 12, clock[0]
        job.add('step', {'action': 'click'}); job.vault, job.prefs, job.observation = [{'id': 'v'}], {'size': 'M'}, {'n': 1, 'text': 'x'}
        live = svc.Job('acct', 'b' * 32, 'goal text', None, 1000, 10, 60); live.state = 'running'; live.add('step', {'action': 'click'})
        s.jobs = {job.id: job, live.id: live}
        self.assertEqual(s.forget(), 0)                                                # just finished: a viewer may still be reading its steps
        clock[0] += svc.FORGET_AFTER_SECONDS + 1
        self.assertEqual(s.forget(), 1)
        self.assertEqual((job.events, job.vault, job.prefs, job.observation), ([], [], {}, None))
        polled = s.poll('acct', job.id)
        self.assertEqual((polled['state'], polled['answer'], polled['cost_microusd'], polled['events']), ('done', 'the answer', 12, []))
        self.assertEqual(len(live.events), 1)                                           # a job that is still alive keeps everything
        self.assertEqual(s.forget(), 0)

    def test_a_page_still_held_open_for_the_customer_is_not_forgotten(self):
        clock = [1000.0]
        s = svc.BrowseService(spawn=lambda j, o: None, root=tempfile.mkdtemp(), jev_mode='off', clock=lambda: clock[0])
        job = svc.Job('acct', 'c' * 32, 'goal text', None, 1000, 10, 60)
        job.state, job.ended, job.takeover_until = 'handoff', clock[0], clock[0] + 10 ** 6
        job.add('step', {'action': 'click'}); s.jobs = {job.id: job}
        clock[0] += svc.FORGET_AFTER_SECONDS + 1
        self.assertEqual(s.forget(), 0)


if __name__ == '__main__':
    unittest.main()
