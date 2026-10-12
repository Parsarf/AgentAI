import unittest
from agentai_platform.adapters import CapabilityUnavailable, GatewayCapabilities
from agentai_platform.gateway import (HttpGateway, GatewayBinding, SyntheticGateway,
                                      negotiate, session_ref, SUPPORTED_PROTOCOL_VERSION)

BINDING = GatewayBinding('deployment-a', 'agent-main', 'https://gateway.example.invalid', 'store-ref-1')


def probe_response(version=SUPPORTED_PROTOCOL_VERSION, methods=None):
    return {'protocolVersion': version, 'runtimeVersion': '2026.9.6',
            'methods': methods or {'chat.send': True, 'chat.history': True, 'events': True, 'chat.abort': True}}


class FakeTransport:
    def __init__(self, responses=None, fail=False):
        self.responses = responses or {}
        self.fail = fail
        self.seen = []

    def __call__(self, request):
        self.seen.append(request)
        if self.fail or request['method'] in self.responses and self.responses[request['method']] is None:
            return {'error': {'code': 'unavailable'}}
        return self.responses.get(request['method'], {})


class NegotiationChecks(unittest.TestCase):
    def test_unprobed_or_wrong_version_fails_closed(self):
        caps = GatewayCapabilities('x', SUPPORTED_PROTOCOL_VERSION, True, True, True, True, False)
        self.assertFalse(negotiate(caps).send)
        caps = GatewayCapabilities('x', SUPPORTED_PROTOCOL_VERSION + 1, True, True, True, True, True)
        negotiated = negotiate(caps)
        self.assertFalse(any([negotiated.send, negotiated.history, negotiated.abort]))
        probed = GatewayCapabilities('x', SUPPORTED_PROTOCOL_VERSION, True, True, True, True, True)
        self.assertTrue(negotiate(probed).history and negotiate(probed).send)

    def test_session_reference_validation(self):
        self.assertEqual(session_ref('abc-DEF_0123:9.0'), 'abc-DEF_0123:9.0')
        for bad in ['', 'x' * 129, 'space id', None, 5]:
            with self.assertRaises(ValueError):
                session_ref(bad)

    def test_binding_rejects_client_fabricated_values(self):
        with self.assertRaises(ValueError):
            GatewayBinding('deployment-a', 'agent-main', 'http://insecure.example.invalid', 'ref')
        with self.assertRaises(ValueError):
            GatewayBinding('bad id', 'agent-main', 'https://gateway.example.invalid', 'ref')


class HttpGatewayChecks(unittest.TestCase):
    def test_probe_and_happy_path(self):
        transport = FakeTransport(responses={
            'chat.history': probe_response(),
            'sessions.create': {'sessionKey': 'sess-1', 'runStarted': False},
            'chat.send': {'status': 'started', 'runStarted': True, 'runId': 'run-1', 'messageSeq': 1, 'messageId': 'm1'},
            'chat.abort': {'aborted': True, 'runId': 'run-1'},
        })
        gateway = HttpGateway(BINDING, transport)
        self.assertTrue(gateway.capabilities().send)
        session, run_started, error = gateway.open_session('op-1', 'label')
        self.assertEqual(session, 'sess-1'); self.assertFalse(run_started); self.assertIsNone(error)
        ack = gateway.send(session, 'op-1', 'hello')
        self.assertEqual(ack, {'run_id': 'run-1', 'message_seq': 1, 'native_message_id': 'm1'})
        page = gateway.history(session, None)
        self.assertEqual(page['kind'], 'tail')
        self.assertEqual(gateway.abort(session, 'run-1')['run_id'], 'run-1')
        self.assertEqual(transport.seen[0]['binding'], BINDING)

    def test_missing_or_unsupported_capability_fails_closed(self):
        gateway = HttpGateway(BINDING, FakeTransport(responses={'chat.history': probe_response(version=SUPPORTED_PROTOCOL_VERSION + 1)}))
        with self.assertRaises(CapabilityUnavailable):
            gateway.require('send')
        gateway = HttpGateway(BINDING, FakeTransport(responses={'chat.history': probe_response(methods={'chat.send': False, 'chat.history': True, 'events': True, 'chat.abort': True})}))
        with self.assertRaises(CapabilityUnavailable):
            gateway.require('send')
        # A failed probe yields disabled capabilities; it never raises out of capabilities().
        self.assertFalse(HttpGateway(BINDING, FakeTransport(fail=True)).capabilities().send)

    def test_bad_shapes_are_unavailable_not_crashes(self):
        gateway = HttpGateway(BINDING, FakeTransport(responses={
            'chat.history': probe_response(),
            'chat.send': {'status': 'queued'},
            'chat.abort': {'aborted': False},
        }))
        gateway.open_session = lambda *a: ('sess-1', False, None)
        with self.assertRaises(CapabilityUnavailable):
            gateway.send('sess-1', 'op', 'hello')
        with self.assertRaises(CapabilityUnavailable):
            gateway.abort('sess-1', 'run-1')

    def test_unknown_rpc_never_reaches_transport(self):
        transport = FakeTransport()
        gateway = HttpGateway(BINDING, transport)
        with self.assertRaises(ValueError):
            gateway._call('sessions.reset', {})


class SyntheticGatewayChecks(unittest.TestCase):
    def test_send_history_and_active_window(self):
        gateway = SyntheticGateway(active_pages=1)
        session, _, _ = gateway.open_session('op-1', 'label')
        ack = gateway.send(session, 'op-1', 'hello')
        self.assertTrue(ack['run_id'] and ack['message_seq'])
        page = gateway.history(session, None)
        self.assertEqual([row['role'] for row in page['messages']], ['customer', 'agent'])
        self.assertTrue(page['active_run'])
        page = gateway.history(session, None)
        self.assertFalse(page['active_run'])

    def test_abort_unsupported_fails_closed(self):
        gateway = SyntheticGateway(abort_supported=False)
        session, _, _ = gateway.open_session('op-1', 'label')
        with self.assertRaises(CapabilityUnavailable):
            gateway.abort(session, None)


if __name__ == '__main__':
    unittest.main()
