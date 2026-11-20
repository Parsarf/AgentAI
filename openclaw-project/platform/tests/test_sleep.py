import unittest
from agentai_platform.lifecycle.sleep import CellFacts, IDLE_AFTER_SECONDS, can_sleep, wake_plan

def cell(acct='a',state='running',last=0,run=0,queue=0,appr=0,maint=False):
    return CellFacts(acct,state,last,run,queue,appr,maint)

class SleepChecks(unittest.TestCase):
    def test_sleeps_only_after_idle_threshold_with_no_work(self):
        self.assertEqual(IDLE_AFTER_SECONDS, 45 * 60)                      # the owner's choice: 45 minutes
        self.assertFalse(can_sleep(cell(last=100),now=500))
        self.assertFalse(can_sleep(cell(last=100),now=100 + IDLE_AFTER_SECONDS - 1))     # one second short of the threshold: still awake
        self.assertTrue(can_sleep(cell(last=100),now=100 + IDLE_AFTER_SECONDS))
    def test_any_live_work_blocks_sleep(self):
        for kw in [dict(run=1),dict(queue=1),dict(appr=1),dict(maint=True)]:
            self.assertFalse(can_sleep(cell(last=0,**kw),now=10**6),kw)
        self.assertFalse(can_sleep(cell(state='stopped'),now=10**6))
    def test_wake_starts_when_nothing_else_runs(self):
        self.assertEqual(wake_plan(cell('b',state='stopped'),[],0),('start',))
        self.assertEqual(wake_plan(cell('b',state='running'),[cell('b')],0),('ready',))
    def test_wake_stops_an_idle_other_cell_first(self):
        plan=wake_plan(cell('b',state='stopped'),[cell('a',last=0)],now=5000)
        self.assertEqual(plan,('stop','a','start'))
    def test_wake_waits_without_naming_or_stopping_a_busy_cell(self):
        plan=wake_plan(cell('b',state='stopped'),[cell('a',run=1)],now=5000)
        self.assertEqual(plan[0],'wait');self.assertNotIn('a',plan[1].split())
        self.assertEqual(wake_plan(cell('b',state='stopped'),[cell('a',last=4900)],now=5000)[0],'wait')
    def test_two_running_cells_require_reconciliation(self):
        self.assertEqual(wake_plan(cell('c',state='stopped'),[cell('a'),cell('b')],0)[0],'wait')
if __name__=='__main__': unittest.main()


class OlderSetup(unittest.TestCase):
    """A running cell set up by older code is restarted at its next quiet moment: a model it no longer routes through, or a tool-ownership hook older than this release's
    (after #66, 2026-11-20, running cells kept the old hook and refused every mail and calendar tool until they happened to sleep)."""
    def test_a_different_model_or_an_older_hook_makes_a_cell_stale_and_nothing_else_does(self):
        from agentai_platform.lifecycle.sleep import configured_by_older_code as old
        here = {'running': True, 'primary': 'selection/selected', 'origin_plugin': 'abc'}
        self.assertFalse(old(here, expect_primary='selection/selected', origin_plugin='abc'))
        self.assertTrue(old({**here, 'primary': 'litellm/old-model'}, expect_primary='selection/selected', origin_plugin='abc'))
        self.assertFalse(old({**here, 'primary': 'byok/mine'}, expect_primary='selection/selected', origin_plugin='abc'))         # an own-model cell stays warm
        self.assertTrue(old({**here, 'origin_plugin': 'older'}, expect_primary='selection/selected', origin_plugin='abc'))
        self.assertFalse(old({**here, 'origin_plugin': None}, expect_primary='selection/selected', origin_plugin='abc'))         # unreadable: nothing is concluded
        self.assertFalse(old({**here, 'running': False, 'origin_plugin': 'older'}, expect_primary=None, origin_plugin='abc'))
        self.assertTrue(old({**here, 'origin_plugin': 'older'}, expect_primary=None, origin_plugin='abc'))                       # the model check switched off, the hook still counts

    def test_the_digest_of_what_a_start_installed_matches_the_release_until_the_hook_changes(self):
        import tempfile
        from pathlib import Path
        from agentai_platform.lifecycle.tool_origin_install import install, installed_digest, release_digest
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(installed_digest(tmp))
            install(tmp)
            self.assertEqual(installed_digest(tmp), release_digest())
            (Path(tmp) / 'extensions/lumina-tool-origin/index.mjs').write_text('// an older hook')
            self.assertNotEqual(installed_digest(tmp), release_digest())
