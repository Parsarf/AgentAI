"""A "keep working until complete" job as a durable objective: checkpoints, a budget, a resume policy, sticky cancel (roadmap #6, #7)."""
import unittest

from agentai_platform.goal_objectives import GoalObjectives, MAX_AUTO_RESUMES
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.security import NotFound, Principal

from tests.test_native_run import Base


class Checks(Base):
    def setUp(self):
        super().setUp()
        self.jobs = self.goals.objectives
        self.b = Principal('b', 'actor-b', 'customer')

    def turn(self, goal_status):
        self.gateway.script = lambda message, run, gw: {'goal': goal_status}
        return self.worker.tick()

    def job(self):
        listing = self.jobs.listing(self.a)
        self.assertEqual(len(listing), 1)
        return listing[0]

    def test_every_finished_turn_is_one_checkpoint_and_the_job_ends_completed(self):
        first = self.say('finish the report', key='g1', goal=True)
        self.turn('active'); self.turn('active'); self.turn('complete')
        self.goals.tick(); self.goals.tick()                                             # looking again never writes a second checkpoint
        job = self.job()
        self.assertEqual((job['state'], job['turns'], job['conversation_id']), ('completed', 3, 'c-a'))
        self.assertEqual([c['step'] for c in job['checkpoints']], ['Turn 1: partial', 'Turn 2: partial', 'Turn 3: completed'])
        self.assertEqual(job['checkpoints'][0]['receipt_id'], first['id'])
        children = self.rows('SELECT child_ref,kind FROM objective_children ORDER BY rowid')
        self.assertEqual(len(children), 2)                                               # the two continuation turns are the job's children
        self.assertEqual(self.jobs.listing(self.b), [])                                  # another account sees nothing
        with self.assertRaises(NotFound):
            self.jobs.get(self.b, job['id'])

    def test_a_job_pauses_at_its_own_turn_budget_and_goes_on_after_the_customer_raises_it_and_resumes(self):
        self.say('long job', key='g1', goal=True)
        self.turn('active')
        job = self.job()
        self.jobs.configure(self.a, job['id'], max_turns=2)
        self.turn('active')                                                              # turn 2 ends with the goal still active: the budget is reached
        job = self.job()
        self.assertEqual((job['state'], job['turns']), ('paused', 2))
        self.assertIn('limit of 2 turns', job['pause_reason'])
        last = self.rows("SELECT continue_goal,outcome,outcome_note FROM customer_requests ORDER BY sequence DESC LIMIT 1")[0]
        self.assertEqual((last['continue_goal'], last['outcome']), (0, 'partial'))
        self.assertIn('limit of 2 turns', last['outcome_note'])
        self.assertEqual(self.rows("SELECT count(*) FROM customer_requests WHERE state='waiting'")[0][0], 0)      # no third turn was admitted
        session = self.rows('SELECT native_session_ref FROM conversations WHERE id="c-a"')[0][0]
        self.assertEqual(self.gateway.session_goal(session)['status'], 'paused')         # paused in the runtime too: nothing picks it up by itself
        self.jobs.configure(self.a, job['id'], max_turns=10)
        self.assertEqual(self.job()['state'], 'paused')                                  # raising the limit never resumes by itself
        self.chat.goal_action(self.a, 'c-a', 'resume', key='r1')
        self.assertEqual(self.job()['state'], 'active')
        self.turn('complete')
        self.goals.tick()
        job = self.job()                                                                 # the resume turn joined the same job
        self.assertEqual((job['state'], job['turns']), ('completed', 3))

    def test_a_time_budget_pauses_the_job_too(self):
        self.say('long job', key='g1', goal=True)
        job_id = None
        self.turn('active')
        job_id = self.job()['id']
        self.jobs.configure(self.a, job_id, max_seconds=3600)
        self.now += 3601
        self.turn('active')
        self.assertIn('time limit', self.job()['pause_reason'])

    def test_a_failed_turn_waits_for_the_customer_unless_they_chose_to_carry_on_automatically(self):
        self.say('long job', key='g1', goal=True)
        self.turn('active')
        job = self.job()
        self.gateway.script = lambda message, run, gw: {'error': 'boom'}
        self.worker.tick()                                                               # the second turn fails
        self.goals.tick()
        job = self.job()
        self.assertEqual((job['state'], job['pause_reason']), ('paused', 'The last turn was interrupted or failed.'))
        self.assertEqual(self.goals.tick(), 0)                                           # policy `ask`: nothing resumes it
        self.jobs.configure(self.a, job['id'], resume_policy='auto')
        self.assertEqual(self.goals.tick(), 1)                                           # policy `auto`: one resume turn is admitted
        self.assertEqual(self.job()['auto_resumes'], 1)
        self.assertEqual(self.goals.tick(), 0)                                           # and only one while it waits or runs
        resume = self.rows("SELECT intent,state FROM customer_requests ORDER BY sequence DESC LIMIT 1")[0]
        self.assertEqual((resume['intent'], resume['state']), ('goal_resume', 'waiting'))

    def test_automatic_resumes_are_bounded(self):
        self.say('long job', key='g1', goal=True)
        self.turn('active')
        job = self.job()
        self.jobs.configure(self.a, job['id'], resume_policy='auto')
        self.gateway.script = lambda message, run, gw: {'error': 'boom'}
        for _ in range(MAX_AUTO_RESUMES + 4):
            self.worker.tick()
        job = self.job()
        self.assertEqual(job['auto_resumes'], MAX_AUTO_RESUMES)
        self.assertEqual(job['state'], 'paused')                                         # after that it waits for the customer after all

    def test_stop_pauses_and_clearing_the_goal_cancels_for_good(self):
        first = self.say('long job', key='g1', goal=True)
        self.turn('active')
        nxt = self.rows("SELECT id FROM customer_requests WHERE continues=?", (first['id'],))[0]['id']
        self.chat.cancel(self.a, nxt)                                                    # Stop on the waiting next turn
        self.worker.tick(); self.goals.tick()
        job = self.job()
        self.assertEqual((job['state'], job['cancelled']), ('paused', False))            # stopped is paused: the customer can resume
        self.chat.goal_action(self.a, 'c-a', 'clear', key='c1')
        job = self.job()
        self.assertEqual((job['state'], job['cancelled']), ('cancelled', True))
        with self.assertRaises(Conflict):
            self.jobs.configure(self.a, job['id'], max_turns=50)                         # a cancelled job is never changed or resumed

    def test_bad_settings_are_refused(self):
        self.say('long job', key='g1', goal=True); self.turn('active')
        job = self.job()
        for kw in ({'resume_policy': 'always'}, {'max_turns': 0}, {'max_turns': 501}, {'max_turns': '5'}, {'max_seconds': 10}, {'max_seconds': 10 ** 9}):
            with self.assertRaises(ValueError):
                self.jobs.configure(self.a, job['id'], **kw)
        with self.assertRaises(NotFound):
            self.jobs.configure(self.b, job['id'], max_turns=5)


if __name__ == '__main__':
    unittest.main()
