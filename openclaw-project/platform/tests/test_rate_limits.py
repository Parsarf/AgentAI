"""A busy model provider is waited for, not turned into a failed task (roadmap #1)."""
import json
import tempfile
import unittest
from pathlib import Path

from agentai_platform import model_keys
from agentai_platform.chat_driver import BUSY_FAILURE, failure_message


class Response:
    def __init__(self, status, body=b'{}', headers=None):
        self.status, self.body, self.headers, self.closed = status, body, headers or {}, False
    def getheader(self, name, default=None): return self.headers.get(name, default)
    def read(self, n=-1): data, self.body = self.body[:n] if n and n > 0 else self.body, b''; return data
    def close(self): self.closed = True


class Connection:
    def __init__(self, response, log): self.response, self.log = response, log
    def request(self, method, path, body, headers): self.log.append((method, path, json.loads(body)['model']))
    def getresponse(self): return self.response
    def close(self): pass


class Checks(unittest.TestCase):
    def relay(self, responses):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.sent, self.slept, self.told = [], [], []
        relay = model_keys.ModelRelay(model_keys.ModelKeyStore(str(Path(tmp.name) / 'keys.json')), lambda account: False, selection=lambda account: 'lumina-default',
                                      sleep=self.slept.append, jitter=lambda: 0.0, waiting=self.told.append)
        queue = list(responses)
        relay._lumina_connection = lambda: Connection(queue.pop(0), self.sent)
        return relay

    def call(self, relay):
        from agentai_platform.model_catalog import models
        relay.selection = lambda account: models()[0]['id'] if 'id' in models()[0] else 'lumina-default'
        return relay.selected_chat('a', 'cell-credential', json.dumps({'model': 'selected', 'messages': [{'role': 'user', 'content': 'hi'}]}).encode())

    def test_a_per_minute_limit_is_waited_for_and_the_call_then_succeeds(self):
        relay = self.relay([Response(429, b'{"error":{"message":"Rate limit exceeded. Limit type: tokens"}}', {'Retry-After': '7'}), Response(529), Response(200, b'ok')])
        up = self.call(relay)
        self.assertEqual(up.status, 200)
        self.assertEqual(len(self.sent), 3)
        self.assertEqual(self.slept, [7.0, 4.0])                # the provider's own Retry-After first, then the growing default
        self.assertEqual(self.told, ['a'])                      # the customer's timeline is told once, not on every wait
        up.close()

    def test_a_budget_refusal_is_never_waited_for(self):
        relay = self.relay([Response(429, b'{"error":{"message":"Budget has been exceeded! Key=x","type":"budget_exceeded"}}')])
        with self.assertRaises(model_keys.RelayError) as caught:
            self.call(relay)
        self.assertEqual((caught.exception.status, self.slept, len(self.sent)), (402, [], 1))

    def test_waiting_is_bounded_and_the_provider_answer_is_then_passed_on_whole(self):
        busy = lambda: Response(429, b'{"error":{"message":"Rate limit exceeded"}}', {'Retry-After': '40'})
        relay = self.relay([busy(), busy(), busy(), busy()])
        up = self.call(relay)
        self.assertEqual(up.status, 429)
        self.assertEqual(self.slept, [40.0, 40.0])              # a third wait would pass the 90 second limit
        self.assertLessEqual(sum(self.slept), model_keys.RETRY_WAIT_SECONDS)
        self.assertIn(b"Rate limit exceeded", up._prefix)        # the body read while deciding is not lost
        up.close()

    def test_other_errors_and_successes_are_not_delayed(self):
        for status in (200, 400, 401, 404, 500):
            relay = self.relay([Response(status, b'{}')])
            self.assertEqual(self.call(relay).status, status)
            self.assertEqual(self.slept, [])

    def test_the_pause_follows_the_provider_or_grows_and_is_always_bounded(self):
        still = lambda: 0.0
        self.assertEqual([model_keys.retry_pause(None, n, still) for n in range(6)], [2.0, 4.0, 8.0, 16.0, 30.0, 30.0])
        self.assertEqual(model_keys.retry_pause('3', 0, still), 3.0)
        self.assertEqual(model_keys.retry_pause('9999', 0, still), 60.0)
        self.assertEqual(model_keys.retry_pause('0', 0, still), 1.0)
        self.assertEqual(model_keys.retry_pause('soon', 2, still), 8.0)
        self.assertEqual(model_keys.retry_pause(None, 0, lambda: 1.0), 2.5)

    def test_a_task_that_still_failed_on_a_busy_provider_says_so_plainly(self):
        for raw in ('⚠️ The model request was rate-limited. Please try again in a few minutes', 'HTTP 429 too many requests', 'provider overloaded (529)'):
            self.assertEqual(failure_message(raw), BUSY_FAILURE)
        self.assertNotEqual(failure_message('budget_exhausted'), BUSY_FAILURE)


if __name__ == '__main__':
    unittest.main()
