import unittest
from agentai_platform.lifecycle.sleep import CellFacts, can_sleep, wake_plan

def cell(acct='a',state='running',last=0,run=0,queue=0,appr=0,maint=False):
    return CellFacts(acct,state,last,run,queue,appr,maint)

class SleepChecks(unittest.TestCase):
    def test_sleeps_only_after_idle_threshold_with_no_work(self):
        self.assertFalse(can_sleep(cell(last=100),now=500))
        self.assertTrue(can_sleep(cell(last=100),now=1000))
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
