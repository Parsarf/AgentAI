import unittest
from agentai_platform.adapters import CapabilityUnavailable, GatewayCapabilities
from agentai_platform.gateway import NativeGateway, SyntheticGateway, negotiate, session_ref, SUPPORTED_PROTOCOL_VERSION

SESSION = 'agent:main:dashboard:abc'
METHODS = ['chat.send', 'chat.history', 'chat.abort', 'sessions.create', 'agent.wait', 'sessions.describe', 'sessions.goal.update', 'sessions.goal.clear']


class Rpc:
    """An injected bridge call: answers each method from a table and records every call with the parameters the runtime would see."""
    def __init__(self, **answers):
        self.answers, self.calls = {'hello': {'protocol': 4, 'runtimeVersion': '2026.9.6', 'methods': METHODS}, **answers}, []

    def __call__(self, method, params):
        self.calls.append((method, params))
        answer = self.answers[method]
        return answer(params) if callable(answer) else answer


class NegotiationChecks(unittest.TestCase):
    def test_unprobed_or_wrong_version_fails_closed(self):
        caps = GatewayCapabilities('x', SUPPORTED_PROTOCOL_VERSION, True, True, True, True, False, wait=True, goals=True)
        self.assertFalse(negotiate(caps).send)
        caps = GatewayCapabilities('x', SUPPORTED_PROTOCOL_VERSION + 1, True, True, True, True, True, wait=True, goals=True)
        negotiated = negotiate(caps)
        self.assertFalse(any([negotiated.send, negotiated.history, negotiated.abort, negotiated.wait, negotiated.goals]))
        probed = GatewayCapabilities('x', SUPPORTED_PROTOCOL_VERSION, True, True, True, True, True, wait=True)
        self.assertTrue(negotiate(probed).history and negotiate(probed).send and negotiate(probed).wait)

    def test_session_reference_validation(self):
        self.assertEqual(session_ref('abc-DEF_0123:9.0'), 'abc-DEF_0123:9.0')
        for bad in ['', 'x' * 129, 'space id', None, 5]:
            with self.assertRaises(ValueError):
                session_ref(bad)


class NativeGatewayChecks(unittest.TestCase):
    def test_capabilities_come_from_the_methods_the_runtime_lists(self):
        caps = NativeGateway(Rpc()).capabilities()
        self.assertTrue(caps.send and caps.history and caps.abort and caps.wait and caps.goals)
        old = NativeGateway(Rpc(hello={'protocol': 4, 'methods': ['chat.send', 'chat.history', 'chat.abort']})).capabilities()
        self.assertTrue(old.send)
        self.assertFalse(old.wait or old.goals)                                         # a runtime without them: the driver refuses to start, it does not guess
        with self.assertRaises(CapabilityUnavailable):
            NativeGateway(Rpc(hello={'protocol': 4, 'methods': ['chat.send']})).wait('r1', 0)
        down = NativeGateway(lambda m, p: {'__error__': 'x'})
        self.assertFalse(down.capabilities().send)
        self.assertFalse(NativeGateway(Rpc(hello={'protocol': 5, 'methods': METHODS})).capabilities().send)

    def test_send_passes_the_key_as_the_run_id_and_flags_a_repeat(self):
        rpc = Rpc(**{'chat.send': lambda p: {'runId': p['idempotencyKey'], 'status': 'ok' if p['idempotencyKey'] == 'old' else 'started'}})
        gw = NativeGateway(rpc)
        first = gw.send(SESSION, 'new', 'hi')
        self.assertEqual((first['run_id'], first['duplicate']), ('new', False))
        self.assertEqual(rpc.calls[-1], ('chat.send', {'sessionKey': SESSION, 'message': 'hi', 'idempotencyKey': 'new'}))
        self.assertTrue(gw.send(SESSION, 'old', 'hi')['duplicate'])                      # the runtime already has this input: no second run
        gw.send(SESSION, 'steer-1', 'more', queue_mode='steer')
        self.assertEqual(rpc.calls[-1][1]['queueMode'], 'steer')
        gw.send(SESSION, 'goal-1', 'finish the report', goal_issued_ms=1234)
        self.assertEqual(rpc.calls[-1][1]['intent'], {'kind': 'session-goal-start', 'version': 1, 'issuedAtMs': 1234})
        with self.assertRaises(CapabilityUnavailable):
            NativeGateway(Rpc(**{'chat.send': {'status': 'queued', 'runId': 'x'}})).send(SESSION, 'k', 'm')
        with self.assertRaises(CapabilityUnavailable):
            NativeGateway(Rpc(**{'chat.send': {'status': 'started'}})).send(SESSION, 'k', 'm')

    def test_wait_reads_the_runtimes_own_verdict(self):
        replies = {'ok': {'status': 'ok', 'terminalReply': {'disposition': 'visible', 'text': 'done'}, 'terminalReceipt': {'successfulToolNames': ['exec', 'lumina__lumina_browser']}},
                   'silent': {'status': 'ok', 'terminalReply': {'disposition': 'silent'}},
                   'aborted': {'status': 'error', 'error': 'aborted', 'stopReason': 'rpc'},
                   'aborted-first-read': {'status': 'error', 'stopReason': 'rpc'},
                   'failed': {'status': 'error', 'error': 'provider exploded'},
                   'timeout': {'status': 'timeout'}, 'queued': {'status': 'pending', 'timeoutPhase': 'queue'}}
        gw = NativeGateway(Rpc(**{'agent.wait': lambda p: replies[p['runId']]}))
        ok = gw.wait('ok', 3000)
        self.assertEqual((ok['status'], ok['text'], ok['tools']), ('ok', 'done', ['exec', 'lumina__lumina_browser']))
        self.assertIsNone(gw.wait('silent', 0)['text'])
        self.assertTrue(gw.wait('aborted', 0)['aborted'] and gw.wait('aborted-first-read', 0)['aborted'])
        failed = gw.wait('failed', 0)
        self.assertEqual((failed['status'], failed['aborted'], failed['error']), ('error', False, 'provider exploded'))
        self.assertEqual([gw.wait(r, 0)['status'] for r in ('timeout', 'queued')], ['running', 'running'])      # not over: wait again, never assume

    def test_abort_needs_the_runtime_to_confirm(self):
        gw = NativeGateway(Rpc(**{'chat.abort': {'ok': True, 'aborted': True, 'runIds': ['r1']}}))
        self.assertEqual(gw.abort(SESSION, 'r1'), {'run_ids': ['r1']})
        with self.assertRaises(CapabilityUnavailable):
            NativeGateway(Rpc(**{'chat.abort': {'aborted': False}})).abort(SESSION)
        with self.assertRaises(CapabilityUnavailable):
            NativeGateway(Rpc(hello={'protocol': 4, 'methods': ['chat.send', 'chat.history']})).abort(SESSION)

    def test_history_rows_carry_their_run_and_a_pending_input_counts_as_active(self):
        page = {'messages': [{'role': 'user', 'content': 'hi', 'idempotencyKey': 'r1:user', '__openclaw': {'id': 'u1', 'seq': 1}},
                             {'role': 'assistant', 'content': [{'type': 'toolCall', 'id': 't1', 'name': 'exec', 'arguments': {'command': 'ls'}}], '__openclaw': {'id': 'a0', 'seq': 2, 'runId': 'r1'}},
                             {'role': 'assistant', 'content': [{'type': 'text', 'text': 'pong'}], '__openclaw': {'id': 'a1', 'seq': 3, 'runId': 'r1'}}],
                'sessionInfo': {'hasActiveRun': False}, 'pendingInputs': {'items': [1], 'total': 1}}
        got = NativeGateway(Rpc(**{'chat.history': page})).history(SESSION)
        self.assertEqual([(r['role'], r['run_id'], r['idempotency_key']) for r in got['messages']], [('customer', None, 'r1:user'), ('agent', 'r1', None)])
        self.assertTrue(got['active_run'])
        self.assertEqual([a['tool'] for a in got['activity']], ['exec'])
        self.assertEqual(got['activity'][0]['run_id'], 'r1')

    def test_an_interrupted_pending_input_is_reported_as_pending_but_is_not_a_running_run(self):
        item = lambda state: {'id': 'p1', 'state': state, 'runId': 'r1-a1', 'message': {'role': 'user', 'content': 'hi'}}
        page = lambda state: {'messages': [], 'sessionInfo': {'hasActiveRun': False}, 'pendingInputs': {'items': [item(state)], 'total': 1}}
        queued = NativeGateway(Rpc(**{'chat.history': page('queued')})).history(SESSION)
        self.assertTrue(queued['active_run'])
        interrupted = NativeGateway(Rpc(**{'chat.history': page('interrupted')})).history(SESSION)
        self.assertFalse(interrupted['active_run'])                                          # a restart left it inert: nothing is running, and nothing will start by itself
        self.assertEqual(interrupted['pending'], [{'run_id': 'r1-a1', 'state': 'interrupted'}])

    def test_goal_calls_have_the_exact_shape_the_runtime_expects(self):
        rpc = Rpc(**{'sessions.describe': {'session': {'goal': {'id': 'g1', 'status': 'active', 'objective': 'x', 'tokensUsed': 40}}},
                     'sessions.goal.update': lambda p: {'status': 'started' if p['action'] == 'resume' else 'updated', 'goal': {'id': 'g1', 'status': 'active'}, **({'runId': p['operationId']} if p['action'] == 'resume' else {})},
                     'sessions.goal.clear': {'status': 'cleared'}})
        gw = NativeGateway(rpc)
        self.assertEqual(gw.session_goal(SESSION), {'id': 'g1', 'status': 'active', 'objective': 'x', 'tokens_used': 40, 'note': ''})
        self.assertEqual(rpc.calls[-1], ('sessions.describe', {'key': SESSION}))
        self.assertIsNone(NativeGateway(Rpc(**{'sessions.describe': {'session': {}}})).session_goal(SESSION))
        resumed = gw.goal_update(SESSION, 'g1', 'resume', 'op-1', note='go', issued_ms=77)
        self.assertEqual(resumed['run_id'], 'op-1')
        self.assertEqual(rpc.calls[-1][1], {'sessionKey': SESSION, 'goalId': 'g1', 'operationId': 'op-1', 'action': 'resume', 'issuedAtMs': 77, 'note': 'go'})
        self.assertIsNone(gw.goal_update(SESSION, 'g1', 'pause', 'op-2')['run_id'])
        gw.goal_clear(SESSION, 'g1', 'op-3', issued_ms=78)
        self.assertEqual(rpc.calls[-1], ('sessions.goal.clear', {'sessionKey': SESSION, 'goalId': 'g1', 'operationId': 'op-3', 'issuedAtMs': 78}))


class SyntheticGatewayChecks(unittest.TestCase):
    def open(self, **kw):
        gw = SyntheticGateway(**kw)
        return gw, gw.open_session('op', 'label')[0]

    def test_a_run_lasts_as_many_waits_as_configured_then_ends_with_its_reply(self):
        gw, session = self.open(polls=2)
        ack = gw.send(session, 'run-1', 'hello')
        self.assertEqual((ack['run_id'], ack['duplicate']), ('run-1', False))
        self.assertEqual([gw.wait('run-1', 0)['status'] for _ in range(2)], ['running', 'running'])
        done = gw.wait('run-1', 0)
        self.assertEqual((done['status'], done['text']), ('ok', 'ack run-1'))
        page = gw.history(session)
        self.assertEqual([(r['role'], r['run_id']) for r in page['messages']], [('customer', None), ('agent', 'run-1')])
        self.assertFalse(page['active_run'])

    def test_the_same_key_never_starts_a_second_run_and_a_steer_joins_the_active_one(self):
        gw, session = self.open(polls=1)
        gw.send(session, 'run-1', 'hello')
        self.assertTrue(gw.send(session, 'run-1', 'hello')['duplicate'])
        self.assertEqual(len(gw.runs), 1)
        gw.send(session, 'steer-1', 'also this', queue_mode='steer')
        self.assertEqual(gw.wait('steer-1', 0)['status'], 'ok')                          # merged: no run of its own
        gw.wait('run-1', 0); done = gw.wait('run-1', 0)
        self.assertEqual(done['status'], 'ok')
        self.assertEqual(len([r for r in gw.history(session)['messages'] if r['role'] == 'agent']), 2)      # one answer per input, in order

    def test_abort_ends_the_run_and_unsupported_abort_fails_closed(self):
        gw, session = self.open(polls=9)
        gw.send(session, 'run-1', 'hello')
        self.assertEqual(gw.abort(session, 'run-1'), {'run_ids': ['run-1']})
        result = gw.wait('run-1', 0)
        self.assertEqual((result['status'], result['aborted']), ('error', True))
        gw, session = self.open(abort_supported=False)
        with self.assertRaises(CapabilityUnavailable):
            gw.abort(session)

    def test_goal_start_pause_resume(self):
        gw, session = self.open()
        gw.send(session, 'run-1', 'finish the report', goal_issued_ms=1)
        gw.wait('run-1', 0)
        goal = gw.session_goal(session)
        self.assertEqual((goal['status'], goal['objective']), ('active', 'finish the report'))
        self.assertEqual(gw.goal_update(session, goal['id'], 'pause', 'op-1')['goal']['status'], 'paused')
        resumed = gw.goal_update(session, goal['id'], 'resume', 'op-2')
        self.assertEqual(resumed['run_id'], 'op-2')
        self.assertEqual(gw.wait('op-2', 0)['status'], 'ok')


if __name__ == '__main__':
    unittest.main()
