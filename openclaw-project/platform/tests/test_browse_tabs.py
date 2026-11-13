"""Several browser tasks of one customer in one cell browser: each owns its tab, steps are taken in turn, at most two tabs stay loaded, and a task whose tab was
closed to make room gets its page back where it was. (Measured on a real 2 GiB cell: five loaded tabs do not fit; see docs/architecture/browsing-redesign.md.)"""
import tempfile
import threading
import unittest

from agentai_platform.browse import service as svc
from agentai_platform.browse.loop import BrowseRunner
from agentai_platform.browse.native_runner import NativeRunner
from agentai_platform.browse.tabs import ACTIVE_LIMIT, LOADED_LIMIT, AccountTabs, TabDesk
from tests.test_native_runner import FakeBridge


class Shared(unittest.TestCase):
    def setUp(self):
        self.bridge, self.tabs, self.now = FakeBridge(), AccountTabs(), [0.0]

    def runner(self, tabs=None):
        out = tempfile.mkdtemp()
        return NativeRunner(self.bridge, out, sleep=lambda s: None, tabs=self.tabs if tabs is None else tabs, clock=self.tick)

    def tick(self):
        self.now[0] += 1
        return self.now[0]

    def open(self, r, url):
        out = r.handle({'id': 1, 'cmd': 'open', 'url': url})
        self.assertTrue(out['ok'], out)
        return out

    def paths(self, start=0):
        return [(c[1].get('path'), (c[1].get('body') or {}).get('targetId')) for c in self.bridge.calls[start:] if c[0] == 'browser.request']

    def test_each_task_gets_a_tab_of_its_own_and_its_commands_name_it(self):
        a, b = self.runner(), self.runner()
        self.open(a, 'https://shop.example/a'); self.open(b, 'https://news.example/b')
        self.assertEqual((a.tab, b.tab), ('T1', 'T2')); self.assertEqual(self.bridge.open_tabs, ['T1', 'T2'])
        mark = len(self.bridge.calls)
        self.assertEqual(a.handle({'id': 2, 'cmd': 'snapshot'})['url'], 'https://shop.example/a')          # each reads its own page, not whichever was opened last
        self.assertEqual(self.paths(mark)[0], ('/tabs/focus', 'T1'))                                      # b's tab was in front: a brings its own forward before it acts
        self.assertTrue(all(tab == 'T1' for path, tab in self.paths(mark) if path == '/act'))
        mark = len(self.bridge.calls)
        self.assertEqual(b.handle({'id': 3, 'cmd': 'snapshot'})['url'], 'https://news.example/b')
        self.assertTrue(all(tab == 'T2' for path, tab in self.paths(mark) if path == '/act'))
        shots = len(self.bridge.calls); a.handle({'id': 4, 'cmd': 'view'})
        self.assertEqual([c[1] for c in self.bridge.calls[shots:] if c[0] == 'browser.shot'], [{'targetId': 'T1'}])

    def test_tabs_the_profile_restored_are_closed_when_the_browser_starts_and_never_adopted(self):
        self.bridge.open_tabs = ['OLD1', 'OLD2']
        a = self.runner(); self.open(a, 'https://shop.example/')
        self.assertEqual(self.bridge.open_tabs, ['T1']); self.assertEqual(a.pages, ['T1'])

    def test_a_popup_belongs_to_the_task_whose_step_opened_it(self):
        a, b = self.runner(), self.runner()
        self.open(a, 'https://shop.example/'); self.open(b, 'https://news.example/')
        self.bridge.open_tabs.append('POP'); self.bridge.urls['POP'] = 'https://pay.example/'            # appears during a's step
        a.handle({'id': 2, 'cmd': 'snapshot'})
        self.assertEqual((a.tab, a.pages), ('POP', ['T1', 'POP'])); self.assertEqual(b.pages, ['T2'])
        b.handle({'id': 3, 'cmd': 'snapshot'})
        self.assertEqual((b.tab, b.pages), ('T2', ['T2']))                                               # b does not follow a's popup

    def test_closing_a_task_closes_only_its_tabs_and_the_browser_stops_with_the_last_one(self):
        a, b = self.runner(), self.runner()
        self.open(a, 'https://shop.example/'); self.open(b, 'https://news.example/')
        a.handle({'id': 2, 'cmd': 'close'})
        self.assertEqual(self.bridge.open_tabs, ['T2']); self.assertFalse(any(c[1].get('path') == '/stop' for c in self.bridge.calls))
        self.assertTrue(b.handle({'id': 3, 'cmd': 'snapshot'})['ok'])                                    # the other task carries on in the same browser
        b.handle({'id': 4, 'cmd': 'close'})
        self.assertTrue(any(c[1].get('path') == '/stop' for c in self.bridge.calls)); self.assertFalse(self.tabs.started)

    def test_at_most_two_tabs_stay_loaded_and_the_task_idle_longest_makes_room(self):
        self.assertEqual((ACTIVE_LIMIT, LOADED_LIMIT), (5, 2))
        runners = [self.runner() for _ in range(5)]
        for i, r in enumerate(runners):
            self.open(r, f'https://site{i}.example/')
            self.assertLessEqual(len(self.bridge.open_tabs), LOADED_LIMIT)
        self.assertEqual([bool(r.pages) for r in runners], [False, False, False, True, True])            # the two that stepped most recently keep their tabs
        self.assertEqual(runners[0].resume_url, 'https://site0.example/')

    def test_a_task_whose_tab_was_closed_gets_its_page_back_where_it_was_and_is_told(self):
        a, b, c = self.runner(), self.runner(), self.runner()
        self.open(a, 'https://shop.example/cart'); self.open(b, 'https://b.example/'); self.open(c, 'https://c.example/')
        self.assertEqual(a.pages, [])                                                                    # a made room for c
        snap = a.handle({'id': 2, 'cmd': 'snapshot'})
        self.assertEqual((snap['ok'], snap['url'], snap.get('reopened')), (True, 'https://shop.example/cart', True))
        self.assertEqual(len(self.bridge.open_tabs), LOADED_LIMIT); self.assertEqual(b.pages, [])        # and now b, idle longest, made room for a
        self.assertNotIn('reopened', a.handle({'id': 3, 'cmd': 'snapshot'}))                             # said once

    def test_a_task_that_never_opened_a_page_cannot_act(self):
        a = self.runner()
        self.assertEqual(a.handle({'id': 1, 'cmd': 'snapshot'})['ok'], False)

    def test_steps_of_two_tasks_never_interleave(self):
        a, b = self.runner(), self.runner()
        self.open(a, 'https://shop.example/'); self.open(b, 'https://news.example/')
        mark = len(self.bridge.calls)
        threads = [threading.Thread(target=lambda r=r: [r.handle({'id': n, 'cmd': 'snapshot'}) for n in range(20)]) for r in (a, b)]
        [t.start() for t in threads]; [t.join() for t in threads]
        front, wrong = None, 0
        for method, params in self.bridge.calls[mark:]:
            if method != 'browser.request':
                continue
            if params.get('path') == '/tabs/focus':
                front = params['body']['targetId']
            elif params.get('path') == '/act' and front is not None and params['body'].get('targetId') != front:
                wrong += 1
        self.assertEqual(wrong, 0)                                                                       # every command went to the tab that was in front for that step

    def test_a_runner_alone_behaves_as_before(self):
        a = self.runner(tabs=AccountTabs())
        self.open(a, 'https://shop.example/a')
        self.assertFalse(a.tabs_of.shared)
        a.handle({'id': 2, 'cmd': 'close'})
        self.assertTrue(any(c[1].get('path') == '/stop' for c in self.bridge.calls))

    def test_the_desk_keeps_accounts_apart(self):
        desk = TabDesk()
        self.assertIs(desk.account('a'), desk.account('a')); self.assertIsNot(desk.account('a'), desk.account('b'))


class ServiceAndLoop(unittest.TestCase):
    def test_native_tasks_of_one_customer_run_five_at_a_time_and_other_engines_one(self):
        s = svc.BrowseService(spawn=lambda j, o: None, root=tempfile.mkdtemp(), jev_mode='off', native_spawn=lambda a, j, o: None, local_spawn=lambda a, j, o: None)
        def slot(engine, account='acct'):
            job = svc.Job(account, 'a' * 32, 'goal text', None, 1000, 10, 60); job.engine = engine
            return s._slot_for(job)
        native = slot('native')
        self.assertTrue(all(native.acquire(blocking=False) for _ in range(ACTIVE_LIMIT))); self.assertFalse(native.acquire(blocking=False))       # a sixth waits
        self.assertIs(slot('native'), native); self.assertIsNot(slot('native', 'other'), native)
        self.assertIs(slot('runner'), s._slot)

    def test_the_loop_tells_the_decider_that_its_page_was_reopened(self):
        from tests.test_browse_modes import runner
        from tests.test_browse_reference import Page, SEARCH, state
        page = Page(SEARCH)
        first = page.snapshot
        calls = [0]
        def snapshot():
            calls[0] += 1
            return {**first(), **({'reopened': True} if calls[0] == 2 else {})}
        page.snapshot = snapshot
        r, jev, _ = runner(page, [{'operation': 'click', 'click_target': 'c3'}, {'operation': 'click', 'click_target': 'c2'}], max_steps=2)
        out = r.run('g', 'https://shop.example/')
        self.assertIn('opened again at the same address', state(jev, 1)); self.assertNotIn('opened again', state(jev, 0))
        self.assertIsInstance(r, BrowseRunner); self.assertEqual([h['action'] for h in out.steps], ['click', 'reopen', 'click'])


if __name__ == '__main__':
    unittest.main()
