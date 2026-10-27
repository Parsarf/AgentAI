"""The model probe prints what the gateway says about each model and never the key or the reply."""
import io
import json
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path

from agentai_platform.ops import probe_models as pm

KEY = 'sk-test-secret-key-123'


class Reply:
    def __init__(self, data, status=200): self.data, self.status = data, status
    def read(self, *a): return json.dumps(self.data).encode()
    def __enter__(self): return self
    def __exit__(self, *a): return False


def opener_for(table):
    def opener(req, timeout=0):
        model = json.loads(req.data)['model']
        self_headers = dict(req.header_items())
        assert self_headers['Authorization'] == 'Bearer ' + KEY
        outcome = table[model]
        if isinstance(outcome, int):
            raise urllib.error.HTTPError(req.full_url, outcome, 'x', {}, io.BytesIO(json.dumps({'error': {'type': 'not_found_error', 'message': 'secret detail ' + KEY}}).encode()))
        if outcome == 'down':
            raise urllib.error.URLError('refused')
        return Reply(outcome)
    return opener


class Probe(unittest.TestCase):
    def test_an_accepted_model_reports_usage_field_names_and_cached_token_fields(self):
        data = {'model': 'claude-sonnet-5-5', 'choices': [{'message': {'content': 'ok'}}],
                'usage': {'prompt_tokens': 12, 'completion_tokens': 2, 'total_tokens': 14, 'prompt_tokens_details': {'cached_tokens': 0}}}
        r = pm.probe('http://x', KEY, 'claude-sonnet-5-5', opener=opener_for({'claude-sonnet-5-5': data}))
        self.assertEqual((r['accepted'], r['status'], r['answered_by']), (True, 200, 'claude-sonnet-5-5'))
        self.assertIn('prompt_tokens_details.cached_tokens', r['usage_fields'])
        self.assertEqual(r['tokens']['prompt_tokens'], 12)
        self.assertIn('cached-token fields reported: prompt_tokens_details.cached_tokens', pm.report([r]))

    def test_a_refused_model_a_dead_gateway_and_no_usage_block_are_reported_plainly(self):
        table = {'a': 404, 'b': 'down', 'c': {'model': 'c', 'choices': []}}
        results = [pm.probe('http://x', KEY, m, opener=opener_for(table)) for m in table]
        text = pm.report(results)
        self.assertIn('a: REFUSED (HTTP 404) error=not_found_error', text)
        self.assertIn('b: unreachable (HTTP None) error=URLError', text)
        self.assertIn('usage fields: (none)', text); self.assertIn('cached-token fields reported: none', text)

    def test_neither_the_key_nor_an_error_body_is_ever_printed(self):
        results = [pm.probe('http://x', KEY, 'a', opener=opener_for({'a': 404}))]
        self.assertNotIn(KEY, pm.report(results)); self.assertNotIn('secret detail', pm.report(results))

    def test_main_reads_the_key_file_probes_each_model_and_sets_the_exit_code(self):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        path = Path(d.name) / 'key'; path.write_text(KEY + '\n')
        original = pm.probe
        pm.probe = lambda base, key, model, **kw: {'model': model, 'accepted': model != 'bad', 'status': 200 if model != 'bad' else 400, 'answered_by': model, 'usage_fields': [], 'tokens': {}, 'error': ''}
        self.addCleanup(setattr, pm, 'probe', original)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(pm.main(['--key-file', str(path), '--model', 'good', '--model', 'bad']), 1)
            self.assertEqual(pm.main(['--key-file', str(path), '--model', 'good']), 0)
        self.assertNotIn(KEY, out.getvalue())
        empty = Path(d.name) / 'empty'; empty.write_text('\n')
        with self.assertRaises(SystemExit):
            pm.main(['--key-file', str(empty)])


if __name__ == '__main__':
    unittest.main()
