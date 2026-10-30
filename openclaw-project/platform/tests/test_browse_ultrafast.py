import io
import json
import sys
import tempfile
import time
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agentai_platform.browse import service as svc
from agentai_platform.browse import ultrafast as uf
from agentai_platform.browse import ultrafast_driver as drv
from agentai_platform.browse.trace import NULL

RID = 'b' * 32
OWNER, OTHER = 'o' * 32, 'x' * 32


def line(**kw):
    return json.dumps(kw)


STEPS = [line(t='opened', url='https://shop.example/'),
         line(t='step', n=1, action='Search', kind='fill', url='https://shop.example/', changed=True, confidence=0.9, shot='shot-001.jpg'),
         line(t='step', n=2, action='Add to cart', kind='click', url='https://shop.example/cart', changed=True, confidence=0.8, shot=''),
         line(t='final', status='done', reason='finished', url='https://shop.example/cart')]


class FakeChild:
    """The child process: replays lines, then ends (EOF). `hang` returns nothing forever, to test the clock."""
    def __init__(self, lines, hang=False, scratch=None):
        self.lines, self.hang, self.sent, self.killed, self.scratch = list(lines), hang, [], 0, scratch

    def send(self, request):
        self.sent.append(request)

    def read(self, timeout):
        if self.hang:
            return None
        return self.lines.pop(0) if self.lines else uf.EOF

    def kill(self):
        self.killed += 1


def drive(child, *, cancelled=lambda: False, allowed=lambda: True, clock=time.monotonic, max_seconds=600, url='https://shop.example/'):
    events = []
    out = uf.run(child=child, request={'url': url, 'goal': 'buy a paddle', 'out': '/o', 'max_steps': 25}, trace=NULL, on_event=lambda k, d: events.append((k, d)),
                 cancelled=cancelled, allowed=allowed, clock=clock, max_seconds=max_seconds)
    return out, events


class Addresses(unittest.TestCase):
    def test_public_sites_pass_and_internal_or_denied_ones_do_not(self):
        for ok in ('https://shop.example/a?b=1', 'http://books.toscrape.com/', 'about:blank', ''):
            self.assertTrue(uf.address_ok(ok), ok)
        for bad in ('http://10.0.0.5/', 'http://127.0.0.1:8000/', 'http://169.254.169.254/latest', 'file:///etc/passwd', 'https://user:pw@shop.example/', 'https://www.paypal.com/signin',
                    'http://localhost/', 'https://thing.internal/'):
            self.assertFalse(uf.address_ok(bad), bad)


class ChildEnvironment(unittest.TestCase):
    def test_nothing_is_inherited_telemetry_stays_off_and_the_settings_file_cannot_undo_it(self):
        with patch.dict('os.environ', {'DATABASE_URL': 'postgres://secret', 'ANTHROPIC_API_KEY': 'sk-live'}):
            env = uf.child_env('/h', {'BU_CDP_URL': 'http://127.0.0.1:9222', 'BH_TELEMETRY': '1', 'ANONYMIZED_TELEMETRY': 'true', 'TYPESAFE_API_KEY': 'attacker'}, 'tk', 'ok')
        self.assertEqual(sorted(k for k in env if k.endswith('KEY') or k in ('DATABASE_URL',)), ['TEXT_MODEL_API_KEY', 'TYPESAFE_API_KEY'])
        self.assertEqual((env['TYPESAFE_API_KEY'], env['TEXT_MODEL_API_KEY']), ('tk', 'ok'))
        self.assertEqual(env['BU_CDP_URL'], 'http://127.0.0.1:9222')
        for name in ('BH_TELEMETRY', 'BROWSER_HARNESS_TELEMETRY'):
            self.assertEqual(env[name], '0')
        self.assertEqual((env['ANONYMIZED_TELEMETRY'], env['BH_UPDATE_CHECK']), ('false', '0'))
        self.assertEqual((env['HOME'], env['BH_RUNTIME_DIR']), ('/h', '/h/run'))


class RunRules(unittest.TestCase):
    def test_a_normal_run_reports_steps_and_pictures_and_ends_done(self):
        child = FakeChild(STEPS)
        (status, reason, url), events = drive(child)
        self.assertEqual((status, url), ('done', 'https://shop.example/cart'))
        kinds = [k for k, _ in events]
        self.assertEqual(kinds, ['opened', 'step', 'screenshot', 'step'])
        steps = [d for k, d in events if k == 'step']
        self.assertEqual([(s['step'], s['action'], s['by']) for s in steps], [(1, 'type', 'ultrafast'), (2, 'click', 'ultrafast')])
        self.assertEqual([d for k, d in events if k == 'screenshot'], [{'file': 'shot-001.jpg', 'step': 1}])
        self.assertEqual(child.sent, [{'url': 'https://shop.example/', 'goal': 'buy a paddle', 'out': '/o', 'max_steps': 25}])

    def test_the_start_address_is_checked_before_the_child_hears_of_it(self):
        for bad in ('http://10.1.2.3/', 'https://www.paypal.com/', 'about:blank'):
            child = FakeChild(STEPS)
            (status, _, _), _ = drive(child, url=bad)
            self.assertEqual(status, 'blocked')
            self.assertEqual(child.sent, [])

    def test_stop_kills_the_child(self):
        child = FakeChild(STEPS, hang=True)
        (status, reason, _), _ = drive(child, cancelled=lambda: True)
        self.assertEqual((status, reason, child.killed), ('cancelled', 'stopped by you', 1))

    def test_the_toggle_expiring_stops_a_running_task(self):
        flips = iter([True, True, False])
        child = FakeChild([STEPS[0], STEPS[1]] + [None] * 5)
        child.read = lambda timeout, _r=iter(STEPS[:2]): next(_r, None)
        (status, reason, _), events = drive(child, allowed=lambda: next(flips, False))
        self.assertEqual(status, 'cancelled')
        self.assertIn('switched off', reason)
        self.assertEqual(child.killed, 1)

    def test_moving_to_an_internal_address_stops_and_kills(self):
        child = FakeChild([line(t='opened', url='https://shop.example/'), line(t='step', n=1, action='Link', kind='click', url='http://169.254.169.254/latest/meta-data', changed=True, confidence=1, shot='shot-001.jpg')])
        (status, reason, _), events = drive(child)
        self.assertEqual((status, child.killed), ('blocked', 1))
        self.assertEqual([k for k, _ in events], ['opened'])             # the step on the internal page is never shown, nor its picture

    def test_a_child_that_dies_without_finishing_is_an_error(self):
        (status, reason, _), _ = drive(FakeChild(STEPS[:2]))
        self.assertEqual(status, 'error')

    def test_the_time_limit_kills_the_child(self):
        ticks = iter(range(0, 10_000, 100))
        child = FakeChild([], hang=True)
        (status, _, _), _ = drive(child, clock=lambda: next(ticks), max_seconds=600)
        self.assertEqual((status, child.killed), ('deadline', 1))

    def test_noise_on_stdout_is_ignored(self):
        child = FakeChild(['Loading model...', '{not json', '[]', '{"t":1}'] + STEPS)
        (status, _, _), events = drive(child)
        self.assertEqual(status, 'done')
        self.assertEqual(len([1 for k, _ in events if k == 'step']), 2)

    def test_an_unknown_final_status_is_an_error_not_a_success(self):
        (status, _, _), _ = drive(FakeChild([line(t='final', status='success!', reason='x', url='https://shop.example/')]))
        self.assertEqual(status, 'error')


class Service(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.children = []

    def make(self, owner_only=True, lines=STEPS):
        def spawn_uf(job_id, out_dir):
            scratch = Path(self.tmp.name) / 'scratch'
            scratch.mkdir(exist_ok=True)
            (scratch / 'shot-001.jpg').write_bytes(b'\xff\xd8jpeg')
            child = FakeChild(lines, scratch=scratch)
            self.children.append(child)
            return child

        def spawn_runner(job_id, out_dir):
            raise AssertionError('the standard browser must not start for an experimental job')

        return svc.BrowseService(spawn=spawn_runner, root=self.tmp.name, jev_mode='off', takeover_seconds=1, ultrafast_spawn=spawn_uf,
                                 ultrafast_for=lambda account: account == OWNER if owner_only else True)

    def wait(self, service, account, rid=RID, seconds=5):
        end = time.time() + seconds
        while time.time() < end:
            out = service.poll(account, rid)
            if out['state'] in svc.FINAL:
                return out
            time.sleep(0.02)
        self.fail('did not finish')

    def test_the_owner_runs_on_the_experimental_engine_and_the_job_looks_like_any_other(self):
        service = self.make()
        service.start(OWNER, RID, 'find a paddle at https://shop.example/ and add it to the cart')
        out = self.wait(service, OWNER)
        self.assertEqual(out['state'], 'done')
        self.assertEqual(service.jobs[RID].engine, 'ultrafast')
        self.assertEqual([e['kind'] for e in out['events']][:3], ['opened', 'step', 'screenshot'])
        self.assertEqual(out['url'], 'https://shop.example/cart')
        self.assertEqual(len(self.children), 1)
        self.assertTrue(self.children[0].killed)                      # always cleaned up, even after a normal finish
        trace = (Path(self.tmp.name) / RID / 'trace.jsonl').read_text()
        self.assertIn('"engine":"ultrafast"', trace.replace(' ', ''))

    def test_nobody_else_ever_gets_it(self):
        service = self.make()
        with patch.object(service, '_run_ultrafast', side_effect=AssertionError('must not run')), patch.object(service, '_run'):
            service.start(OTHER, 'c' * 32, 'open https://shop.example/')
        self.assertEqual(service.jobs['c' * 32].engine, 'runner')

    def test_without_the_environment_the_standard_browser_is_used(self):
        service = svc.BrowseService(spawn=lambda j, o: None, root=self.tmp.name, jev_mode='off')       # no ultrafast wiring at all
        with patch.object(service, '_run'):
            service.start(OWNER, RID, 'open https://shop.example/')
        self.assertEqual(service.jobs[RID].engine, 'runner')

    def test_only_the_current_request_leaves_the_server_and_personal_data_is_scrubbed(self):
        service = self.make()
        history = json.dumps([{'role': 'user', 'content': 'my secret earlier chat'}])
        goal = f'{svc.HISTORY_HEADER if hasattr(svc, "HISTORY_HEADER") else ""}'
        from agentai_platform.browse import goals
        goal = goals.HISTORY_HEADER + history + goals.CURRENT_MARKER + 'Email me at someone@example.com after you open https://shop.example/'
        service.start(OWNER, RID, goal)
        self.wait(service, OWNER)
        sent = self.children[0].sent[0]
        self.assertNotIn('secret earlier chat', json.dumps(sent))
        self.assertNotIn('someone@example.com', sent['goal'])
        self.assertEqual(sent['url'], 'https://shop.example/')

    def test_a_task_with_no_site_ends_in_an_error_not_a_hang(self):
        service = self.make()
        service.start(OWNER, RID, 'find me something nice')
        out = self.wait(service, OWNER)
        self.assertEqual(out['state'], 'error')
        self.assertEqual(self.children, [])

    def test_stop_ends_an_experimental_task(self):
        service = self.make(lines=[STEPS[0]])
        original = FakeChild.read
        FakeChild.read = lambda self_, timeout: self_.lines.pop(0) if self_.lines else (time.sleep(0.05) or None)
        self.addCleanup(setattr, FakeChild, 'read', original)
        service.start(OWNER, RID, 'open https://shop.example/ and look around')
        time.sleep(0.3)
        service.cancel(OWNER, RID)
        out = self.wait(service, OWNER)
        self.assertEqual(out['state'], 'cancelled')


class Pictures(unittest.TestCase):
    def test_only_plain_files_of_the_right_name_and_size_are_copied(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst, tempfile.TemporaryDirectory() as secret:
            src, dst, secret = Path(src), Path(dst), Path(secret)
            (src / 'shot-001.jpg').write_bytes(b'pic')
            (secret / 'root-only').write_text('root secret')
            (src / 'shot-002.jpg').symlink_to(secret / 'root-only')
            (src / 'shot-003.jpg').write_bytes(b'x' * (uf.MAX_SHOT_BYTES + 1))
            (src / 'notes.txt').write_text('hi')
            self.assertTrue(uf.copy_shot(src, dst, 'shot-001.jpg'))
            self.assertEqual((dst / 'shot-001.jpg').read_bytes(), b'pic')
            for bad in ('shot-002.jpg', 'shot-003.jpg', 'notes.txt', '../shot-001.jpg', 'shot-9.jpg', '', None, 'shot-004.jpg'):
                self.assertFalse(uf.copy_shot(src, dst, bad), bad)
            self.assertEqual(sorted(p.name for p in dst.iterdir()), ['shot-001.jpg'])

    def test_a_picture_that_does_not_arrive_is_not_announced(self):
        events = []
        child = FakeChild(STEPS)
        uf.run(child=child, request={'url': 'https://shop.example/', 'goal': 'g', 'out': '/o', 'max_steps': 5}, trace=NULL, on_event=lambda k, d: events.append(k),
               cancelled=lambda: False, allowed=lambda: True, collect=lambda name: False)
        self.assertNotIn('screenshot', events)


class Driver(unittest.TestCase):
    def test_pictures_are_named_the_way_the_service_serves_them(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(drv.save_shot(Path(d), 3, {'screenshot': 'QUJD'}), 'shot-003.jpg')
            self.assertEqual((Path(d) / 'shot-003.jpg').read_bytes(), b'ABC')
            self.assertEqual(drv.save_shot(Path(d), 1, {}), '')
            self.assertEqual(drv.save_shot(Path(d), 1000, {'screenshot': 'QUJD'}), '')
        self.assertTrue(svc.FILE.fullmatch('shot-003.jpg'))

    def test_the_driver_reports_each_action_once_and_never_the_typed_text(self):
        history = []
        page = {'url': 'https://shop.example/', 'screenshot': 'QUJD'}

        class FakeAgent:
            def __init__(self, url, goal, screenshots=False):
                self.state = {'page': page, 'history': history, 'status': 'ready'}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def run(self):
                for n, kind in ((1, 'fill'), (2, 'click')):
                    history.append({'step': n, 'action': f'Field {n}', 'kind': kind, 'url': 'https://shop.example/', 'page_changed': True, 'confidence': 0.9, 'text': 'MY-CARD-NUMBER'})
                    yield {'history': history, 'page': page, 'status': 'ready'}
                self.state['status'] = 'done'
                yield {'history': history, 'page': page, 'status': 'done'}

        module = types.ModuleType('jev_ultrafast')
        module.Agent = FakeAgent
        with tempfile.TemporaryDirectory() as d:
            request = json.dumps({'url': 'https://shop.example/', 'goal': 'g', 'out': d, 'max_steps': 25}) + '\n'
            out = io.StringIO()
            with patch.dict(sys.modules, {'jev_ultrafast': module}), patch('sys.stdin', io.StringIO(request)), redirect_stdout(out):
                self.assertEqual(drv.main(), 0)
            lines = [json.loads(x) for x in out.getvalue().splitlines()]
            self.assertEqual([x['t'] for x in lines], ['opened', 'step', 'step', 'final'])
            self.assertEqual(lines[-1]['status'], 'done')
            self.assertNotIn('MY-CARD-NUMBER', out.getvalue())
            self.assertTrue((Path(d) / 'shot-001.jpg').exists())

    def test_the_step_limit_ends_the_run(self):
        history = []
        page = {'url': 'https://shop.example/'}

        class Endless:
            def __init__(self, *a, **k):
                self.state = {'page': page, 'history': history, 'status': 'ready'}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def run(self):
                while True:
                    history.append({'step': len(history) + 1, 'action': 'x', 'kind': 'click', 'url': page['url'], 'page_changed': True, 'confidence': 1})
                    yield {'history': history, 'page': page, 'status': 'ready'}

        module = types.ModuleType('jev_ultrafast')
        module.Agent = Endless
        with tempfile.TemporaryDirectory() as d:
            request = json.dumps({'url': 'https://shop.example/', 'goal': 'g', 'out': d, 'max_steps': 3}) + '\n'
            out = io.StringIO()
            with patch.dict(sys.modules, {'jev_ultrafast': module}), patch('sys.stdin', io.StringIO(request)), redirect_stdout(out):
                drv.main()
        final = json.loads(out.getvalue().splitlines()[-1])
        self.assertEqual(final['status'], 'max_steps')


if __name__ == '__main__':
    unittest.main()
