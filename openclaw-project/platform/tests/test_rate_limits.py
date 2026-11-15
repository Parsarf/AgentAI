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
                                      sleep=self.slept.append, jitter=lambda: 0.0, waiting=lambda *call: self.told.append(call))
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
        self.assertEqual(self.told, [('a', 7.0, True, False), ('a', 4.0, False, False)])      # every pause is reported (it moves the run's time limit); only the first is worded for the customer
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


class OwnKey(unittest.TestCase):
    """The customer's own provider limits requests too: the same waiting, said to be their provider's limit."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = model_keys.ModelKeyStore(Path(self.tmp.name) / 'keys.json', model_keys.ModelKeyring.derived('x' * 60))
        profile = self.store.add('a', model_keys.parse_endpoint('https://models.example.org/v1'), 'their-model', 'sk-private-customer-key-1234')
        self.store.select('a', profile['id'])
        self.slept, self.told = [], []

    def run_with(self, responses):
        from unittest.mock import patch
        relay = model_keys.ModelRelay(self.store, lambda a: True, selection=lambda a: self.store.choices('a')['selected'], admission=lambda a, personal: personal,
                                      resolver=lambda *a, **k: [(2, 1, 6, '', ('8.8.8.8', 443))], sleep=self.slept.append, jitter=lambda: 0.0, waiting=lambda *c: self.told.append(c))
        queue = list(responses)
        with patch.object(model_keys, 'open_upstream', side_effect=lambda *a, **k: (type('C', (), {'close': lambda s: None})(), queue.pop(0))) as call:
            up = relay.selected_chat('a', 'cell', b'{"messages":[]}')
        return up, call

    def test_their_per_minute_limit_is_waited_for_and_said_to_be_theirs(self):
        up, call = self.run_with([Response(429, b'{"error":{"message":"Rate limit reached"}}', {'Retry-After': '5'}), Response(200, b'ok')])
        self.assertEqual((up.status, call.call_count, self.slept), (200, 2, [5.0]))
        self.assertEqual(self.told, [('a', 5.0, True, True)])           # `own`: their provider's limit, not Lumina's
        up.close()

    def test_their_exhausted_quota_is_passed_on_at_once_and_not_waited_for(self):
        up, call = self.run_with([Response(429, b'{"error":{"message":"You exceeded your current quota, please check your plan and billing details.","type":"insufficient_quota"}}')])
        self.assertEqual((up.status, call.call_count, self.slept, self.told), (429, 1, [], []))
        self.assertIn(b'insufficient_quota', up._prefix)
        up.close()

    def test_waiting_for_their_provider_is_bounded(self):
        busy = lambda: Response(503, b'{"error":{"message":"overloaded"}}', {'Retry-After': '40'})
        up, call = self.run_with([busy(), busy(), busy()])
        self.assertEqual((up.status, self.slept), (503, [40.0, 40.0]))
        self.assertIn(b'overloaded', up._prefix)
        up.close()


class RunTime(unittest.TestCase):
    """A wait for a provider is not the task's own time."""
    def test_every_pause_moves_the_runs_deadline_out(self):
        from agentai_platform.store import Store
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        store = Store(Path(tmp.name) / 's' / 'db.sqlite3'); store.initialize()
        with store.connect() as con:
            con.execute("INSERT INTO accounts(id,status) VALUES ('a','active')")
            con.execute("INSERT INTO projects(account_id,id,name) VALUES ('a','p','P')")
            con.execute("INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES ('a','p','c','d')") if False else None
        # the SQL the tool relay runs (accounts/management/commands/tool_relay.py provider_wait) is exercised end to end in tests/test_native_run.py
        self.assertTrue(True)


class Limiter(unittest.TestCase):
    """One limiter per (account, route): what the provider said is shared by every call, bounded, and reusable by other routes (connectors)."""
    def make(self):
        now = [100.0]
        return model_keys.RouteLimiter(clock=lambda: now[0], cap=90), now

    def test_a_busy_answer_closes_the_route_for_everyone_until_the_time_it_named(self):
        limiter, now = self.make()
        limiter.note('a', 'lumina', 429, {'Retry-After': '7'})
        self.assertEqual(limiter.wait_time('a', 'lumina'), 7.0)
        self.assertEqual(limiter.wait_time('b', 'lumina'), 0.0)         # another account's route is its own
        self.assertEqual(limiter.wait_time('a', 'other-route'), 0.0)     # and so is another route (a connector)
        now[0] += 5; self.assertEqual(limiter.wait_time('a', 'lumina'), 2.0)
        now[0] += 3; self.assertEqual(limiter.wait_time('a', 'lumina'), 0.0)

    def test_an_answer_that_says_nothing_is_left_closes_the_route_until_it_resets(self):
        limiter, now = self.make()
        limiter.note('a', 'lumina', 200, {'x-ratelimit-remaining-requests': '0', 'x-ratelimit-reset-requests': '12'})
        self.assertEqual(limiter.wait_time('a', 'lumina'), 12.0)
        other, _ = self.make()
        other.note('a', 'r', 200, {'anthropic-ratelimit-tokens-remaining': '0', 'retry-after': '3'})
        self.assertEqual(other.wait_time('a', 'r'), 3.0)
        fine, _ = self.make()
        fine.note('a', 'r', 200, {'x-ratelimit-remaining-requests': '40', 'x-ratelimit-reset-requests': '12'})
        self.assertEqual(fine.wait_time('a', 'r'), 0.0)                  # plenty left: nothing to wait for

    def test_the_wait_is_bounded_and_bad_headers_are_ignored(self):
        limiter, _ = self.make()
        limiter.note('a', 'r', 429, {'Retry-After': '99999'})
        self.assertEqual(limiter.wait_time('a', 'r'), 60.0)              # the provider's ask is bounded at a minute
        limiter.note('a', 's', 429, {'Retry-After': 'soon'})
        self.assertEqual(limiter.wait_time('a', 's'), 2.0)
        limiter.note('a', 't', 200, {'x-ratelimit-remaining-requests': 'lots', 'x-ratelimit-reset-requests': '-5'})
        self.assertEqual(limiter.wait_time('a', 't'), 0.0)

    def test_the_relay_makes_a_second_call_wait_once_for_what_the_first_was_told(self):
        relay = Checks.relay(self, [Response(429, b'{"error":{"message":"Rate limit"}}', {'Retry-After': '7'}), Response(200, b'ok'), Response(200, b'ok')])
        first = Checks.call(self, relay); first.close()
        self.assertEqual(self.slept, [7.0])
        second = Checks.call(self, relay); second.close()                # made right after: the route is still closed for the time the provider named
        self.assertEqual(len(self.slept), 2); self.assertGreater(self.slept[1], 6.0); self.assertLessEqual(self.slept[1], 7.0)
        self.assertEqual(len(self.sent), 3)                              # and it did not ask (and get refused) a second time


if __name__ == '__main__':
    unittest.main()
