import json, os, queue, socket, tempfile, threading, time, unittest
from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.bridge_client import BridgeRpc
from agentai_platform.gateway import NativeGateway
from agentai_platform.lifecycle.cell_bridge import BridgeError, CellBridge, serve


class FakeRelay:
    """Replies come from an inbox the bridge's reader thread drains, like the real relay. `hold` withholds the reply of a method until release()."""
    PAYLOADS = {'sessions.create': {'key': 'agent:main:dashboard:abc'},
                'chat.send': {'runId': 'r1', 'status': 'started'},
                'chat.abort': {'ok': True, 'aborted': True, 'runIds': ['r1']},
                'agent.wait': {'runId': 'r1', 'status': 'ok', 'terminalReply': {'disposition': 'visible', 'text': 'pong'}},
                'sessions.describe': {'session': {'goal': {'id': 'g1', 'status': 'active', 'objective': 'x'}}},
                'sessions.goal.update': {'status': 'updated', 'goal': {'status': 'paused'}},
                'sessions.goal.clear': {'status': 'cleared'},
                'browser.request': {'ok': True, 'result': 1}, 'browser.shot': {'data_b64': 'AAAA', 'url': 'https://example.com/'}, 'browser.live': {'on': True},
                'browser.frame': {'on': True, 'seq': 1},
                'chat.history': {'messages': [{'role': 'user', 'content': 'hi', '__openclaw': {'id': 'u1', 'seq': 1}},
                                              {'role': 'assistant', 'content': [{'type': 'text', 'text': 'pong'}], '__openclaw': {'id': 'a1', 'seq': 2}}],
                                 'sessionInfo': {'hasActiveRun': False}, 'pendingInputs': {'items': [], 'total': 0}}}

    def __init__(self, tenant, token, hold=(), scopes=None):
        self.tenant, self.token, self.sent, self.closed, self.scopes = tenant, token, [], False, scopes
        self.inbox, self.hold, self.held = queue.Queue(), set(hold), []
        self.inbox.put({'ready': True, 'protocol': 4, 'server': {'version': '2026.9.6'},
                        'methods': ['chat.send', 'chat.history', 'chat.abort', 'sessions.create', 'agent.wait', 'sessions.describe', 'sessions.goal.update', 'sessions.goal.clear']})
    def write(self, obj):
        self.sent.append(obj)
        if obj['method'] in self.hold:
            self.held.append(obj)
        else:
            self._reply(obj)
    def _reply(self, obj):
        self.inbox.put({'id': obj['id'], 'ok': True, 'payload': self.PAYLOADS[obj['method']]})
    def release(self):
        for obj in self.held:
            self._reply(obj)
        self.held = []
    def read(self, timeout):
        try:
            return self.inbox.get(timeout=min(timeout, 0.2))
        except queue.Empty:
            return None
    def alive(self): return not self.closed
    def close(self): self.closed = True


def bridge(relays, hold=()):
    def spawn(tenant, token, scopes=None):
        r = FakeRelay(tenant, token, hold, scopes); relays.append(r); return r
    return CellBridge(lambda a: ('aa-' + 'a' * 32, 'tok') if a == 'acct' else None, spawn, lambda t: 12345,
                      identify=lambda credential: 'acct' if credential == 'cell-model-key' else None, browser_callers={0})


class BridgeTests(unittest.TestCase):
    def test_same_session_name_in_two_accounts_uses_distinct_cell_credentials_and_relays(self):
        relays = []
        bindings = {'a': ('aa-' + 'a' * 32, 'token-a'), 'b': ('aa-' + 'b' * 32, 'token-b')}
        def spawn(tenant, token):
            relay = FakeRelay(tenant, token); relays.append(relay); return relay
        b = CellBridge(bindings.get, spawn, lambda tenant: 0)
        self.addCleanup(b.close_all)
        params = {'sessionKey': 'agent:main:dashboard:shared'}
        b.call('a', 'chat.history', params)
        b.call('b', 'chat.history', params)
        b.call('a', 'chat.history', params)
        self.assertEqual([(r.tenant, r.token) for r in relays], [bindings['a'], bindings['b']])
        self.assertEqual([len(r.sent) for r in relays], [2, 1])
        with self.assertRaises(BridgeError): b.call('unknown', 'chat.history', params)
        self.assertEqual(len(relays), 2)

    def test_validation_refuses_unknown_and_malformed(self):
        b = bridge([])
        for method, params in [('exec', {}), ('chat.send', {'sessionKey': 'agent:main:x', 'message': '', 'idempotencyKey': 'k'}),
                               ('chat.send', {'sessionKey': 'evil', 'message': 'm', 'idempotencyKey': 'k'}),
                               ('chat.history', {'sessionKey': 'agent:other:x'}), ('sessions.create', {'label': 'a b'})]:
            with self.assertRaises(BridgeError): b.call('acct', method, params)
        with self.assertRaises(BridgeError): b.call('nobody', 'hello', {})

    def test_full_flow_through_native_gateway(self):
        relays = []; b = bridge(relays)
        gw = NativeGateway(lambda m, p: b.call('acct', m, p))
        caps = gw.capabilities()
        self.assertTrue(caps.send and caps.wait and caps.goals)
        key, _, _ = gw.open_session('op1', 'chat-1')
        self.assertEqual(key, 'agent:main:dashboard:abc')
        self.assertEqual(gw.send(key, 'op1', 'hi')['run_id'], 'r1')
        done = gw.wait('r1', 2000)
        self.assertEqual((done['status'], done['text']), ('ok', 'pong'))
        page = gw.history(key)
        self.assertEqual([m['content'] for m in page['messages']], ['hi', 'pong']); self.assertFalse(page['active_run'])
        gw.abort(key, 'r1')
        self.assertEqual(gw.session_goal(key)['status'], 'active')
        self.assertEqual(len(relays), 1)                       # one relay reused across calls
        self.assertEqual(relays[0].sent[0]['params']['agentId'], 'main')
        self.assertEqual(b.call('acct', 'usage.snapshot', {}), {'spend_microusd': 12345})

    def test_pending_input_counts_only_when_nonempty(self):
        gw = NativeGateway(lambda m, p: {'messages': [], 'sessionInfo': {}, 'pendingInputs': {'items': [1], 'total': 1}})
        gw._caps = gw.capabilities.__self__._caps = None
        gw.capabilities = lambda: type('C', (), {'send': True, 'history': True, 'abort': True})()
        self.assertTrue(gw.history('agent:main:x', None)['active_run'])

    def test_idle_sweep_and_dead_relay_respawn(self):
        relays = []; t = [0]
        b = bridge(relays); b.clock = lambda: t[0]; b.idle_seconds = 10
        b.call('acct', 'hello', {}); t[0] = 11; b.sweep()
        self.assertTrue(relays[0].closed)
        b.call('acct', 'hello', {}); self.assertEqual(len(relays), 2)

    def test_socket_roundtrip_and_peer_check(self):
        b = bridge([]); d = tempfile.mkdtemp(); path = os.path.join(d, 's')
        server = serve(b, path, allowed_uids={os.getuid()}, peer_uid=lambda sock: os.getuid())
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            from pathlib import Path
            self.assertEqual(BridgeRpc('acct', Path(path))('hello', {})['protocol'], 4)     # Path objects are accepted
            rpc = BridgeRpc('acct', path)
            self.assertEqual(rpc('hello', {})['protocol'], 4)
            with self.assertRaises(CapabilityUnavailable): BridgeRpc('acct', path)('exec', {})
        finally:
            server.shutdown(); server.server_close()
        with self.assertRaises(CapabilityUnavailable): BridgeRpc('acct', path)('hello', {})


class NativeMethodChecks(unittest.TestCase):
    SESSION = 'agent:main:dashboard:abc'

    def test_new_methods_are_validated_to_the_exact_shape(self):
        b = bridge([])
        bad = [('agent.wait', {'runId': 'r1', 'timeoutMs': 99999}), ('agent.wait', {'runId': 'a b'}), ('agent.wait', {'runId': 'r1', 'timeoutMs': '5'}),
               ('chat.send', {'sessionKey': self.SESSION, 'message': 'm', 'idempotencyKey': 'k', 'queueMode': 'shout'}),
               ('chat.send', {'sessionKey': self.SESSION, 'message': 'm', 'idempotencyKey': 'k', 'intent': {'kind': 'run-anything', 'version': 1, 'issuedAtMs': 1}}),
               ('chat.abort', {'sessionKey': self.SESSION, 'runId': 'bad id'}),
               ('sessions.goal.update', {'sessionKey': self.SESSION, 'goalId': 'g1', 'operationId': 'o1', 'issuedAtMs': 1, 'action': 'delete'}),
               ('sessions.goal.update', {'sessionKey': self.SESSION, 'goalId': 'g1', 'operationId': 'o1', 'issuedAtMs': 1, 'action': 'edit'}),
               ('sessions.goal.clear', {'sessionKey': self.SESSION, 'goalId': 'g1', 'operationId': 'o1'}),
               ('sessions.describe', {'key': 'agent:other:x'}), ('cell.identify', {'credential': 'x'})]
        for method, params in bad:
            with self.assertRaises(BridgeError, msg=method + str(params)): b.call('acct', method, params)

    def test_native_calls_pass_through_with_only_the_allowed_fields(self):
        relays = []; b = bridge(relays)
        self.assertEqual(b.call('acct', 'agent.wait', {'runId': 'r1', 'timeoutMs': 2000, 'extra': 1})['status'], 'ok')
        b.call('acct', 'chat.send', {'sessionKey': self.SESSION, 'message': 'm', 'idempotencyKey': 'k', 'queueMode': 'steer', 'model': 'evil', 'thinking': 'high',
                                     'intent': {'kind': 'session-goal-start', 'version': 1, 'issuedAtMs': 5, 'x': 1}})
        b.call('acct', 'chat.abort', {'sessionKey': self.SESSION, 'runId': 'r1', 'x': 1})
        b.call('acct', 'sessions.goal.update', {'sessionKey': self.SESSION, 'goalId': 'g1', 'operationId': 'o1', 'issuedAtMs': 5, 'action': 'pause', 'note': 'stop', 'x': 1})
        self.assertEqual(b.call('acct', 'sessions.describe', {'sessionKey': self.SESSION})['session']['goal']['status'], 'active')
        sent = {m['method']: m['params'] for m in relays[0].sent}
        self.assertEqual(sent['agent.wait'], {'runId': 'r1', 'timeoutMs': 2000})
        self.assertEqual(sent['chat.send'], {'sessionKey': self.SESSION, 'message': 'm', 'idempotencyKey': 'k', 'queueMode': 'steer',
                                             'intent': {'kind': 'session-goal-start', 'version': 1, 'issuedAtMs': 5}})
        self.assertEqual(sent['chat.abort'], {'sessionKey': self.SESSION, 'runId': 'r1'})
        self.assertEqual(sent['sessions.goal.update'], {'sessionKey': self.SESSION, 'goalId': 'g1', 'operationId': 'o1', 'issuedAtMs': 5, 'action': 'pause', 'note': 'stop'})
        self.assertEqual(sent['sessions.describe'], {'key': self.SESSION})

    def test_a_long_wait_never_holds_up_stop(self):
        relays = []; b = bridge(relays, hold=('agent.wait',))
        b.call('acct', 'hello', {})
        out = {}
        waiter = threading.Thread(target=lambda: out.update(b.call('acct', 'agent.wait', {'runId': 'r1', 'timeoutMs': 5000})))
        waiter.start()
        deadline = time.time() + 5
        while not relays[0].held and time.time() < deadline:
            time.sleep(0.01)
        self.assertTrue(relays[0].held)                                     # the wait is in flight
        started = time.time()
        self.assertTrue(b.call('acct', 'chat.abort', {'sessionKey': self.SESSION, 'runId': 'r1'})['aborted'])
        self.assertLess(time.time() - started, 2)                           # Stop answered while the wait is still pending
        self.assertTrue(waiter.is_alive())
        relays[0].release(); waiter.join(5)
        self.assertEqual(out['status'], 'ok')

    def test_a_relay_that_dies_fails_every_waiting_call_instead_of_hanging(self):
        relays = []; b = bridge(relays, hold=('agent.wait',))
        b.call('acct', 'hello', {})
        errors = []
        def wait():
            try:
                b.call('acct', 'agent.wait', {'runId': 'r1', 'timeoutMs': 5000})
            except BridgeError as exc:
                errors.append(str(exc))
        t = threading.Thread(target=wait); t.start()
        while not relays[0].held:
            time.sleep(0.01)
        relays[0].close()
        t.join(5)
        self.assertEqual(errors, ['relay closed'])
        b.call('acct', 'hello', {})
        self.assertEqual(len(relays), 2)                                     # the next call reconnects

    def test_identify_names_the_account_for_a_cells_own_credential_only(self):
        b = bridge([])
        self.assertEqual(b.call('-', 'cell.identify', {'credential': 'cell-model-key'}), {'account': 'acct'})
        with self.assertRaises(BridgeError): b.call('-', 'cell.identify', {'credential': 'someone-elses-key'})
        with self.assertRaises(BridgeError): CellBridge(lambda a: None, None, None).call('-', 'cell.identify', {'credential': 'cell-model-key'})



if __name__ == '__main__':
    unittest.main()


class BrowserMethodChecks(unittest.TestCase):
    ACT = {'method': 'POST', 'path': '/act'}

    def test_only_the_named_caller_may_use_the_browser_and_the_app_never_can(self):
        b = bridge([])
        for caller in (None, 1000):
            with self.assertRaises(BridgeError): b.call('acct', 'browser.request', {'method': 'GET', 'path': '/tabs'}, caller=caller)
            with self.assertRaises(BridgeError): b.call('acct', 'browser.shot', {}, caller=caller)

    def test_browser_requests_are_validated_to_the_exact_shape(self):
        b = bridge([])
        bad = [{'method': 'GET', 'path': '/cookies'}, {'method': 'POST', 'path': '/storage/local'}, {'method': 'DELETE', 'path': '/tabs'}, {'method': 'POST', 'path': '/download'},
               {'method': 'POST', 'path': '/navigate', 'body': {'url': 'file:///etc/passwd'}}, {'method': 'POST', 'path': '/navigate', 'body': {'url': 'javascript:alert(1)'}},
               {'method': 'POST', 'path': '/navigate', 'body': {'url': 'https://a.com/' + 'x' * 3000}}, {'method': 'POST', 'path': '/tabs/open', 'body': {'url': 'https://a b.com'}},
               {'method': 'POST', 'path': '/tabs/close', 'body': {'targetId': 'bad id'}},
               {**self.ACT, 'body': {'kind': 'evaluate', 'fn': '() => document.cookie'}}, {**self.ACT, 'body': {'kind': 'evaluate', 'script': 'steal'}},
               {**self.ACT, 'body': {'kind': 'evaluate', 'script': 'describe', 'args': 'x'}}, {**self.ACT, 'body': {'kind': 'evaluate', 'script': 'describe', 'args': {'x': 'y' * 9000}}},
               {**self.ACT, 'body': {'kind': 'clickCoords', 'x': -1, 'y': 5}}, {**self.ACT, 'body': {'kind': 'clickCoords', 'x': True, 'y': 5}}, {**self.ACT, 'body': {'kind': 'clickCoords', 'x': 5, 'y': 9999}},
               {**self.ACT, 'body': {'kind': 'press', 'key': 'Control+A'}}, {**self.ACT, 'body': {'kind': 'press', 'key': 'F12'}},
               {**self.ACT, 'body': {'kind': 'type', 'ref': 'e1', 'text': 'x'}}, {**self.ACT, 'body': {'kind': 'upload', 'paths': ['/etc/passwd']}}, {**self.ACT, 'body': {'kind': 'batch', 'actions': []}},
               {**self.ACT, 'body': {'kind': 'resize', 'width': 10, 'height': 10}}, {**self.ACT}, {'method': 'GET', 'path': '/tabs', 'body': 'x'}]
        for params in bad:
            with self.assertRaises(BridgeError, msg=str(params)): b.call('acct', 'browser.request', params, caller=0)
        for method, params in (('browser.live', {'on': 'yes'}), ('browser.frame', {'after': -1}), ('browser.frame', {'waitMs': 99999}), ('browser.frame', {'after': '1'})):
            with self.assertRaises(BridgeError, msg=method + str(params)): b.call('acct', method, params, caller=0)

    def test_allowed_requests_reach_the_cell_with_the_cells_own_profile_and_our_scripts_only(self):
        relays = []; b = bridge(relays)
        b.call('acct', 'browser.request', {'method': 'POST', 'path': '/navigate', 'body': {'url': 'https://example.com/a?b=1', 'targetId': 'x', 'profile': 'user'}, 'query': {'profile': 'user'}}, caller=0)
        b.call('acct', 'browser.request', {**self.ACT, 'body': {'kind': 'evaluate', 'script': 'describe', 'args': {'sel': 'a', 'max': 5}, 'fn': '() => document.cookie'}}, caller=0)
        b.call('acct', 'browser.request', {**self.ACT, 'body': {'kind': 'clickCoords', 'x': 10, 'y': 20.5, 'button': 'right'}}, caller=0)
        b.call('acct', 'browser.request', {**self.ACT, 'body': {'kind': 'press', 'key': 'Enter'}}, caller=0)
        b.call('acct', 'browser.shot', {'path': '/etc/passwd'}, caller=0)
        b.call('acct', 'browser.live', {'on': True, 'profile': 'user'}, caller=0)
        b.call('acct', 'browser.frame', {'after': 3, 'waitMs': 1000, 'x': 1}, caller=0)
        sent = [m for r in relays for m in r.sent]
        self.assertEqual(sent[0]['params'], {'method': 'POST', 'path': '/navigate', 'body': {'url': 'https://example.com/a?b=1'}, 'query': {'profile': 'openclaw'}})
        self.assertIn('document.querySelectorAll(sel)', sent[1]['params']['body']['fn'])
        self.assertNotIn('document.cookie', sent[1]['params']['body']['fn'])
        self.assertIn('"max": 5', sent[1]['params']['body']['fn'])
        self.assertEqual(sent[2]['params']['body'], {'kind': 'clickCoords', 'x': 10, 'y': 20.5})
        self.assertEqual(sent[3]['params']['body'], {'kind': 'press', 'key': 'Enter'})
        self.assertEqual(sent[4]['params'], {'body': {'type': 'jpeg'}, 'query': {'profile': 'openclaw'}})
        self.assertEqual(sent[5]['params'], {'on': True, 'profile': 'openclaw'})
        self.assertEqual(sent[6]['params'], {'after': 3, 'waitMs': 1000})

    def test_the_browser_has_its_own_admin_connection_and_the_main_one_never_gets_admin(self):
        relays = []; b = bridge(relays)
        b.call('acct', 'hello', {})
        b.call('acct', 'browser.request', {'method': 'GET', 'path': '/tabs'}, caller=0)
        b.call('acct', 'browser.request', {'method': 'GET', 'path': '/tabs'}, caller=0)
        self.assertEqual([r.scopes for r in relays], [None, ['operator.read', 'operator.write', 'operator.admin']])
        self.assertEqual([m['method'] for m in relays[0].sent], [])
        self.assertEqual(len(relays[1].sent), 2)
        self.assertNotIn('browser.request', b.call('acct', 'hello', {})['methods'])
        b.close_all()
        self.assertTrue(all(r.closed for r in relays))


class StatusChecks(unittest.TestCase):
    def test_cell_status_uses_the_probe_not_the_running_lookup(self):
        b = CellBridge(lambda a: None, lambda t, k: None, lambda t: 0, binding=lambda a: 'aa-' + 'a' * 32 if a == 'acct' else None,
                       probe=lambda tenant: False)
        self.assertEqual(b.call('acct', 'cell.status', {}), {'running': False})
        with self.assertRaises(BridgeError): b.call('nobody', 'cell.status', {})


class WorkspaceCollectChecks(unittest.TestCase):
    def test_bridge_collects_only_from_the_accounts_own_workspace(self):
        import tempfile, base64, time
        from pathlib import Path
        from agentai_platform.lifecycle.cell_bridge import CellBridge, BridgeError
        with tempfile.TemporaryDirectory() as tmp:
            for tenant in ('tnt-a', 'tnt-b'):
                (Path(tmp) / tenant / 'workspace').mkdir(parents=True)
                (Path(tmp) / tenant / 'workspace' / 'x.txt').write_text(tenant)
            b = CellBridge(lambda a: None, None, None, binding=lambda a: {'acct': 'tnt-a'}.get(a), workspace_root=tmp)
            got = b.call('acct', 'workspace.collect', {'since': 0})
            self.assertEqual([(f['path'], base64.b64decode(f['data_b64'])) for f in got['files']], [('x.txt', b'tnt-a')])
            with self.assertRaises(BridgeError): b.call('nobody', 'workspace.collect', {'since': 0})
            with self.assertRaises(BridgeError): b.call('acct', 'workspace.collect', {'since': '0'})
            with self.assertRaises(BridgeError): b.call('acct', 'workspace.collect', {'since': -1})
