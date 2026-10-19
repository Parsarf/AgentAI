import json
from pathlib import Path
import tempfile
import unittest

from agentai_platform.browse import service as svc
from agentai_platform.browse import trace as tr
from agentai_platform.browse.ladder import JevChooser
from agentai_platform.browse.session import RunnerError, Session
from tests.test_browse import ScriptedJev
from tests.test_browse_service import FakeTransport, RID, llm_for, wait


class TraceFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'trace.jsonl'

    def test_events_are_one_json_line_each_with_time_and_step(self):
        t = tr.Trace(self.path); t.step = 3
        t.emit('jev', outcome='click', ms=412, heads={'operation': ['click', 0.93]})
        row = tr.read(self.path)[0]
        self.assertEqual((row['kind'], row['step'], row['ms'], row['heads']['operation']), ('jev', 3, 412, ['click', 0.93]))
        self.assertIn('t', row); self.assertIn('at', row)

    def test_secrets_in_error_text_are_redacted_and_long_text_is_cut(self):
        tr.Trace(self.path).emit('llm', why='bad key sk-ant-api03-' + 'a' * 40 + ' ' + 'x' * 1000)
        why = tr.read(self.path)[0]['why']
        self.assertNotIn('sk-ant', why); self.assertLessEqual(len(why), tr.TEXT_LIMIT)

    def test_an_unwritable_path_never_raises(self):
        tr.Trace(Path(self.tmp.name) / 'missing' / 'trace.jsonl').emit('start')         # no folder: the run must go on
        tr.NULL.emit('anything')

    def test_the_file_is_capped_but_the_end_is_always_written(self):
        t = tr.Trace(self.path)
        for _ in range(8000):
            t.emit('runner', pad='some words here ' * 18)
        t.emit('end', status='done')
        rows = tr.read(self.path)
        self.assertLess(self.path.stat().st_size, tr.MAX_BYTES + 2000)
        self.assertEqual(rows[-1]['kind'], 'end'); self.assertGreater(rows[-1]['dropped_events'], 0)

    def test_viewer_marks_the_first_problem(self):
        t = tr.Trace(self.path)
        t.emit('start'); t.emit('jev', outcome='click', confidence=0.9); t.emit('runner', cmd='act', ok=False, error='covered'); t.emit('end', status='stuck')
        text = tr.render(tr.read(self.path))
        self.assertIn('first problem', text); self.assertIn('covered', text)
        self.assertNotIn('first problem', tr.render([{'t': 0, 'step': 0, 'kind': 'start'}]))


class SessionTrace(unittest.TestCase):
    def test_runner_calls_are_timed_and_the_typed_text_is_not_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'trace.jsonl'
            t = FakeTransport(tmp); s = Session(t, trace=tr.Trace(path))
            s.open('https://shop.example/'); s.act('type', 1, 'my secret text', 'Search paddles')
            rows = tr.read(path)
            self.assertEqual([(r['kind'], r['cmd']) for r in rows], [('runner', 'open'), ('runner', 'act')])
            self.assertEqual((rows[1]['action'], rows[1]['ref'], rows[1]['ok']), ('type', 1, True))
            self.assertNotIn('my secret text', path.read_text()); self.assertNotIn('Search paddles', path.read_text())

    def test_a_dead_runner_is_recorded_with_its_last_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'trace.jsonl'

            class Dead(FakeTransport):
                stderr_tail = ['browser crashed: out of memory']
                def recv(self, timeout): raise RunnerError('runner exited')
            with self.assertRaises(RunnerError):
                Session(Dead(tmp), trace=tr.Trace(path)).snapshot()
            row = tr.read(path)[0]
            self.assertEqual(row['kind'], 'runner_error'); self.assertIn('runner exited', row['why']); self.assertIn('out of memory', row['stderr'][0])


class RunTrace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)

    def service(self, script, jev=None, mode='off', **kw):
        return svc.BrowseService(spawn=lambda j, o: FakeTransport(o, **kw), llm_for=llm_for(script), root=self.tmp.name, jev_mode=mode, takeover_seconds=1,
                                 jev_for=(lambda account: JevChooser('https://x', 'jev-1.13.0', 'k', jev)) if jev else (lambda account: None))

    def rows(self):
        return tr.read(Path(self.tmp.name) / RID / 'trace.jsonl')

    def test_a_run_leaves_start_steps_decisions_and_an_end(self):
        s = self.service(['{"action":"click","ref":2}', '{"action":"click","ref":1}'])
        s.start('acct', RID, 'buy a paddle at https://shop.example/'); wait(s, ('handoff',))
        kinds = [r['kind'] for r in self.rows()]
        for kind in ('start', 'ready', 'snapshot', 'route', 'llm', 'decision', 'runner', 'act', 'floor', 'end', 'final'):
            self.assertIn(kind, kinds)
        floor = next(r for r in self.rows() if r['kind'] == 'floor'); self.assertEqual(floor['rule'], 'sensitive control')
        end = next(r for r in self.rows() if r['kind'] == 'end'); self.assertEqual(end['status'], 'handoff'); self.assertEqual(end['where'], 'shop.example/cart')

    def test_the_trace_holds_no_request_text_no_query_string_and_no_page_text(self):
        pages = {'start': {'url': 'https://shop.example/?token=SECRETQUERY#frag', 'snap': '[1] <a> "Next"', 'text': 'PAGE BODY WORDS', 'go': {1: 'start'}}}
        s = self.service(['{"action":"click","ref":1}', '{"action":"stop","reason":"enough"}'] * 3, transport_kw=None) if False else svc.BrowseService(
            spawn=lambda j, o: FakeTransport(o, pages=pages), llm_for=llm_for(['{"action":"stop","reason":"done here"}']), root=self.tmp.name, jev_mode='off', takeover_seconds=1)
        s.start('acct', RID, 'find my private goal words at https://shop.example/?token=SECRETQUERY'); wait(s, ('stopped', 'done', 'error'))
        raw = (Path(self.tmp.name) / RID / 'trace.jsonl').read_text()
        for leaked in ('private goal words', 'SECRETQUERY', 'PAGE BODY WORDS', 'frag'):
            self.assertNotIn(leaked, raw)
        self.assertIn('goal_chars', raw)

    def test_a_jev_miss_records_why_with_timing_and_what_jev_said(self):
        jev = ScriptedJev('this is not json', {'operation': 'click', 'click_target': 'c2'}, p=0.5)
        s = self.service(['{"action":"click","ref":2}', '{"action":"click","ref":1}', '{"action":"click","ref":1}'], jev=jev, mode='live')
        s.start('acct', RID, 'buy a paddle at https://shop.example/'); wait(s, ('handoff',))
        jevs = [r for r in self.rows() if r['kind'] == 'jev']
        self.assertEqual(jevs[0]['outcome'], 'invalid'); self.assertIn('ms', jevs[0]); self.assertTrue(jevs[0]['why'])
        low = next(r for r in jevs if r['outcome'] == 'low_confidence'); self.assertEqual(low['threshold'], 0.85); self.assertIn('operation', low['heads'])
        routes = [r for r in self.rows() if r['kind'] == 'route']
        self.assertTrue(routes[0]['jev_asked']); self.assertIn('jev_misses', routes[0])

    def test_a_crash_is_recorded_with_where_it_happened(self):
        s = self.service([], hang=True)
        s.start('acct', RID, 'buy a paddle at https://shop.example/'); wait(s, ('error',))
        kinds = [r['kind'] for r in self.rows()]
        self.assertIn('runner_error', kinds)
        crash = [r for r in self.rows() if r['kind'] == 'crash']
        self.assertTrue(crash and crash[0]['frames'])

    def test_user_actions_are_recorded_without_the_text_typed(self):
        s = self.service(['{"action":"click","ref":2}', '{"action":"click","ref":1}'])
        s.start('acct', RID, 'buy a paddle at https://shop.example/'); wait(s, ('handoff',))
        s.control('acct', RID, 'type', text='MY PASSWORD 123'); s.release('acct', RID)
        raw = (Path(self.tmp.name) / RID / 'trace.jsonl').read_text()
        self.assertNotIn('MY PASSWORD', raw)
        self.assertTrue(any(r['kind'] == 'runner' and r['cmd'] == 'xy' and r['action'] == 'type' for r in self.rows()))
        self.assertTrue(any(r['kind'] == 'user' and 'released' in r['what'] for r in self.rows()))


if __name__ == '__main__':
    unittest.main()
