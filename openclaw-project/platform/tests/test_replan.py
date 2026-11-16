"""Roadmap #11: a running plan can be revised. The assistant proposes the whole revised plan; it is checked against what has already happened and shown as a difference; the
customer approves it (or the customer chose automatic revision, which is bounded). Phases that are running or finished never change."""
import copy
import json
import unittest

from agentai_platform.genui import replan, schema
from agentai_platform.lifecycle.types import Conflict
from agentai_platform.security import NotFound
from tests import test_genui as G
from tests.test_genui import phase, plan

BASE = plan(phase('a'), phase('b', deps=['a']), phase('c', deps=['b']))


def revised(**changes):
    """a stays; b (failed) is switched off and replaced by b2; c waits for b2."""
    p = copy.deepcopy(BASE)
    p['phases'][1]['enabled'] = False
    p['phases'].insert(2, phase('b2', 'Another way', deps=['a']))
    p['phases'][3]['dependsOn'] = ['b2']
    p.update(changes)
    return p


class PureChecks(unittest.TestCase):
    def test_a_difference_names_what_was_added_removed_changed_and_reordered(self):
        new = revised()
        d = replan.diff(schema.validate_plan(BASE), schema.validate_plan(new))
        self.assertEqual([p['id'] for p in d['added']], ['b2'])
        self.assertEqual(sorted(c['id'] for c in d['changed']), ['b', 'c'])
        self.assertEqual((d['removed'], d['reordered']), ([], False))
        self.assertTrue(replan.is_empty(replan.diff(schema.validate_plan(BASE), schema.validate_plan(BASE))))
        self.assertIn('adds "Another way"', replan.Replanner.describe(d))

    def test_history_cannot_be_rewritten_but_a_failed_phase_can_be_switched_off(self):
        old = schema.validate_plan(BASE)
        runs = {'a': {'state': 'completed'}, 'b': {'state': 'failed'}, 'c': {'state': 'pending'}}
        replan.check_against_runs(runs, old, schema.validate_plan(revised()))              # fine
        gone = copy.deepcopy(BASE); gone['phases'].pop(0); gone['phases'][0]['dependsOn'] = []
        with self.assertRaises(replan.ReplanRefused) as why: replan.check_against_runs(runs, old, schema.validate_plan(gone))
        self.assertIn('already finished', str(why.exception))
        dropped = copy.deepcopy(BASE); dropped['phases'].pop(1)                              # the failed phase simply left out: approving that could never be applied, so it is refused here
        for p in dropped['phases']: p['dependsOn'] = [d for d in p['dependsOn'] if d != 'b']
        with self.assertRaises(replan.ReplanRefused) as why: replan.check_against_runs(runs, old, schema.validate_plan(dropped))
        self.assertIn('not removed', str(why.exception))
        edited = copy.deepcopy(BASE); edited['phases'][0]['description'] = 'something else'
        with self.assertRaises(replan.ReplanRefused): replan.check_against_runs(runs, old, schema.validate_plan(edited))
        rewritten = copy.deepcopy(BASE); rewritten['phases'][1]['description'] = 'try again differently'
        with self.assertRaises(replan.ReplanRefused) as why: replan.check_against_runs(runs, old, schema.validate_plan(rewritten))
        self.assertIn('failed', str(why.exception))
        running = {**runs, 'c': {'state': 'running'}}
        also = copy.deepcopy(BASE); also['phases'][2]['dependsOn'] = ['a']
        with self.assertRaises(replan.ReplanRefused): replan.check_against_runs(running, old, schema.validate_plan(also))


class ReplanChecks(unittest.TestCase):
    setUp, rows, make_plan_block, drive, phases = G.FlowChecks.setUp, G.FlowChecks.rows, G.FlowChecks.make_plan_block, G.FlowChecks.drive, G.FlowChecks.phases

    def failed_plan(self):
        block = self.make_plan_block(BASE)
        self.chat.launch_plan(self.a, block['id'], 1)
        self.drive(['a done'], runs=1)
        rid = self.rows("SELECT request_id FROM plan_phase_runs WHERE phase_id='b'")[0]['request_id']
        with self.store.connect() as con:
            con.execute("UPDATE customer_requests SET state='failed',result='boom' WHERE id=?", (rid,))
            con.execute('DELETE FROM request_slots')
        self.chat.runner.tick()
        self.assertEqual(self.phases(block['id']), {'a': 'completed', 'b': 'failed', 'c': 'pending'})
        return block['id']

    def proposals(self, block):
        return self.chat.blocks.get(self.a, block)['proposals']

    def test_a_failed_phase_leads_to_a_proposal_shown_as_a_difference_and_nothing_changes_until_approved(self):
        block = self.failed_plan()
        started = self.chat.runner.request_replan(self.a, block, 'failure', 'try something else')
        self.assertEqual([p['state'] for p in self.proposals(block)], ['requested'])
        self.drive([json.dumps(revised())], runs=1)
        proposal = self.proposals(block)[0]
        self.assertEqual((proposal['state'], proposal['trigger']), ('proposed', 'failure'))
        self.assertEqual([p['id'] for p in proposal['diff']['added']], ['b2'])
        self.assertEqual(sorted(c['id'] for c in proposal['diff']['changed']), ['b', 'c'])
        self.assertIn('Another way', proposal['summary'])
        self.assertEqual(self.phases(block), {'a': 'completed', 'b': 'failed', 'c': 'pending'})           # not applied
        texts = [m['content'] for m in self.chat.messages(self.a, 'c-a')['messages']]
        self.assertTrue(any('Review it in the plan above' in t for t in texts))                           # a sentence, not the raw JSON
        self.assertFalse(any('"schemaVersion"' in t for t in texts))
        self.assertEqual(started['proposal'], proposal['id'])
        asked = self.gw.sent[-1]
        self.assertIn('try something else', asked); self.assertIn('keep every phase that is running or completed exactly', asked)

    def test_approving_applies_the_revision_the_failed_phase_is_replaced_and_the_plan_carries_on(self):
        block = self.failed_plan()
        self.chat.runner.request_replan(self.a, block, 'failure'); self.drive([json.dumps(revised())], runs=1)
        proposal = self.proposals(block)[0]
        view = self.chat.runner.approve_proposal(self.a, block, proposal['id'])
        self.assertEqual([p['id'] for p in view['state']['plan']['phases']], ['a', 'b', 'b2', 'c'])
        states = self.phases(block)
        self.assertEqual((states['a'], states['b'], states['b2']), ('completed', 'skipped', 'running'))    # the new phase started at once
        self.assertEqual(self.chat.blocks.get(self.a, block)['proposals'][0]['state'], 'applied')
        self.assertEqual([r['source'] for r in self.rows('SELECT source FROM plan_revisions ORDER BY revision')][-1], 'approved')
        self.drive(['b2 done', 'c done'])
        self.assertEqual(self.chat.blocks.get(self.a, block)['run_status'], 'completed')
        with self.assertRaises(Conflict): self.chat.runner.approve_proposal(self.a, block, proposal['id'])     # decided once

    def test_a_revision_that_rewrites_a_finished_phase_is_refused_with_a_reason(self):
        block = self.failed_plan()
        bad = revised(); bad['phases'][0]['description'] = 'changed after it finished'
        self.chat.runner.request_replan(self.a, block, 'invalidated', 'the first result changes things'); self.drive([json.dumps(bad)], runs=1)
        p = self.proposals(block)[0]
        self.assertEqual(p['state'], 'failed'); self.assertIn('already finished', p['summary']); self.assertIsNone(p['plan'])
        self.assertEqual(self.phases(block), {'a': 'completed', 'b': 'failed', 'c': 'pending'})
        texts = [m['content'] for m in self.chat.messages(self.a, 'c-a')['messages']]
        self.assertTrue(any('The plan is unchanged' in t for t in texts))

    def test_a_reply_that_changes_nothing_or_is_not_a_plan_is_a_failed_proposal(self):
        block = self.failed_plan()
        self.chat.runner.request_replan(self.a, block, 'instruction', 'anything'); self.drive([json.dumps(BASE)], runs=1)
        self.assertIn('did not suggest any change', self.proposals(block)[0]['summary'])
        self.chat.runner.request_replan(self.a, block, 'instruction', 'again'); self.drive(['no json here', 'still not json'], runs=1)
        newest = self.proposals(block)[0]
        self.assertEqual(newest['state'], 'failed'); self.assertIn('could not be read as a plan', newest['summary'])

    def test_declining_leaves_the_plan_alone_and_a_new_request_supersedes_an_old_proposal(self):
        block = self.failed_plan()
        self.chat.runner.request_replan(self.a, block, 'failure'); self.drive([json.dumps(revised())], runs=1)
        first = self.proposals(block)[0]['id']
        self.chat.runner.decline_proposal(self.a, block, first)
        self.assertEqual(self.proposals(block)[0]['state'], 'declined')
        with self.assertRaises(Conflict): self.chat.runner.decline_proposal(self.a, block, first)
        self.chat.runner.request_replan(self.a, block, 'failure'); self.drive([json.dumps(revised())], runs=1)
        second = self.proposals(block)[0]['id']
        self.chat.runner.request_replan(self.a, block, 'instruction', 'one more thing')
        by = {p['id']: p['state'] for p in self.proposals(block)}
        self.assertEqual((by[first], by[second]), ('declined', 'superseded'))
        with self.assertRaises(Conflict): self.chat.runner.request_replan(self.a, block, 'failure')          # one revision is prepared at a time

    def test_an_edit_made_after_the_suggestion_makes_it_stale_and_it_cannot_be_applied(self):
        block = self.failed_plan()
        self.chat.runner.request_replan(self.a, block, 'failure'); self.drive([json.dumps(revised())], runs=1)
        proposal = self.proposals(block)[0]
        view = self.chat.blocks.get(self.a, block)
        edited = copy.deepcopy(view['state']['plan']); edited['phases'][2]['description'] = 'the customer edited this phase'
        self.chat.runner.edit(self.a, block, view['version'], edited)
        with self.assertRaises(Conflict): self.chat.runner.approve_proposal(self.a, block, proposal['id'])
        stale = self.proposals(block)[0]
        self.assertEqual(stale['state'], 'superseded'); self.assertIn('no longer fits', stale['summary'])

    def test_automatic_replanning_asks_applies_and_stops_after_its_limit(self):
        block = self.failed_plan()
        view = self.chat.runner.set_auto_replan(self.a, block, True)
        self.assertEqual(view['replan'], {'auto': True, 'auto_used': 0, 'auto_limit': replan.MAX_AUTO_REPLANS})
        self.chat.runner.tick()                                                        # a phase failed and the customer chose automatic: the assistant is asked
        self.assertEqual([(p['state'], p['auto']) for p in self.proposals(block)], [('requested', True)])
        self.drive([json.dumps(revised())], runs=1)
        self.chat.runner.tick()                                                        # the checked revision is applied without waiting for the customer
        self.assertEqual(self.proposals(block)[0]['state'], 'applied')
        self.assertEqual(self.phases(block)['b'], 'skipped')
        self.assertEqual(self.chat.blocks.get(self.a, block)['replan']['auto_used'], 1)
        # the new phase fails too: a second automatic revision is allowed, a third is not
        for round_ in range(2):
            running = [r for r in self.rows("SELECT phase_id,request_id FROM plan_phase_runs WHERE state='running'")]
            if running:
                with self.store.connect() as con:
                    con.execute("UPDATE customer_requests SET state='failed',result='boom' WHERE id=?", (running[0]['request_id'],)); con.execute('DELETE FROM request_slots')
            self.chat.runner.tick()
            used = self.chat.blocks.get(self.a, block)['replan']['auto_used']
            if used < replan.MAX_AUTO_REPLANS:
                self.drive([json.dumps(self.next_revision(block))], runs=1); self.chat.runner.tick()
        self.assertLessEqual(self.chat.blocks.get(self.a, block)['replan']['auto_used'], replan.MAX_AUTO_REPLANS)
        before = len(self.proposals(block))
        self.chat.runner.tick(); self.chat.runner.tick()
        self.assertEqual(len(self.proposals(block)), before)                          # no endless revising: past the limit the customer decides

    def next_revision(self, block):
        current = copy.deepcopy(self.chat.blocks.get(self.a, block)['state']['plan'])
        failed = [r['phase_id'] for r in self.rows("SELECT phase_id FROM plan_phase_runs WHERE state='failed'")][0]
        for p in current['phases']:
            if p['id'] == failed:
                p['enabled'] = False
        current['phases'].append(phase('extra' + failed, 'Plan C for ' + failed, deps=['a']))
        for p in current['phases']:
            if p['id'] == 'c':
                p['dependsOn'] = ['extra' + failed]
        return current

    def test_customers_only_ever_reach_their_own_proposals(self):
        block = self.failed_plan()
        self.chat.runner.request_replan(self.a, block, 'failure'); self.drive([json.dumps(revised())], runs=1)
        proposal = self.proposals(block)[0]['id']
        with self.assertRaises(NotFound): self.chat.runner.approve_proposal(self.b, block, proposal)
        with self.assertRaises(NotFound): self.chat.runner.decline_proposal(self.b, block, proposal)
        with self.assertRaises((NotFound, Conflict)): self.chat.runner.request_replan(self.b, block, 'failure')
        with self.assertRaises((NotFound, Conflict)): self.chat.runner.set_auto_replan(self.b, block, True)
        self.assertEqual(self.proposals(block)[0]['state'], 'proposed')

    def test_input_is_validated(self):
        block = self.failed_plan()
        for trigger, text in (('nonsense', ''), ('instruction', ''), ('instruction', 'x' * 2001), ('instruction', 'a\x00b')):
            with self.assertRaises(ValueError): self.chat.runner.request_replan(self.a, block, trigger, text)
        with self.assertRaises(ValueError): self.chat.runner.set_auto_replan(self.a, block, 'yes')

    def test_why_a_phase_is_waiting_is_stated_and_a_failed_prerequisite_blocks_its_dependants(self):
        block = self.failed_plan()
        waiting = self.chat.blocks.get(self.a, block)['why_waiting']
        self.assertEqual(waiting, {'c': {'reason': 'blocked', 'on': ['b']}})


if __name__ == '__main__':
    unittest.main()
