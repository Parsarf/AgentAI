import io, json, logging, os, unittest
from unittest import mock
from agentai_platform import timing


class TimingTests(unittest.TestCase):
    def capture(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        timing._log.handlers[:] = [handler]
        timing._log.setLevel(logging.INFO)
        return stream

    def test_off_by_default_writes_nothing(self):
        stream = self.capture()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('AGENTAI_TIMING', None)
            timing.mark('r1', 'claim')
        self.assertEqual(stream.getvalue(), '')

    def test_mark_is_structured_and_drops_free_text(self):
        stream = self.capture()
        with mock.patch.dict(os.environ, {'AGENTAI_TIMING': '1'}):
            timing.mark('r1', 'mirror', new_rows=2, ok=True, dur_ms=1.5, text='hello this has spaces and private content', blob={'a': 1})
        row = json.loads(stream.getvalue())
        self.assertEqual((row['rid'], row['stage'], row['new_rows'], row['ok']), ('r1', 'mirror', 2, True))
        self.assertNotIn('text', row)
        self.assertNotIn('blob', row)
        self.assertIn('wall_ms', row) and self.assertIn('mono_ms', row)

    def test_bound_request_id_is_used_below_the_driver(self):
        stream = self.capture()
        with mock.patch.dict(os.environ, {'AGENTAI_TIMING': '1'}):
            timing.bind('req-9')
            timing.mark(None, 'rpc', method='chat.history', dur_ms=3)
        self.assertEqual(json.loads(stream.getvalue())['rid'], 'req-9')

    def test_never_raises(self):
        with mock.patch.dict(os.environ, {'AGENTAI_TIMING': '1'}), mock.patch.object(timing, '_logger', side_effect=RuntimeError):
            timing.mark('r', 'x')


if __name__ == '__main__':
    unittest.main()
