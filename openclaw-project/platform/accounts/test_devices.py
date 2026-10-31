import json
from unittest import mock
from django.test import TestCase
from agentai_platform.adapters import CapabilityUnavailable
from .models import Audit
from .tests import AccountBoundaryTests

DEVICE = {'device_id': 'a1b2c3d4e5f60718', 'label': 'Chrome (mac)', 'created': 1.0, 'last_seen': 2.0, 'connected': True}


class FakeRpc:
    def __init__(self, replies=None, down=False):
        self.calls, self.replies, self.down = [], replies or {}, down

    def __call__(self, op, **params):
        self.calls.append((op, params))
        if self.down: raise CapabilityUnavailable('browse service unavailable')
        return self.replies[op]


class DeviceEndpointChecks(TestCase):
    new_client = AccountBoundaryTests.new_client
    post = AccountBoundaryTests.post
    signed = AccountBoundaryTests.signed
    setUp = AccountBoundaryTests.setUp

    def patched(self, rpc): return mock.patch('accounts.devices._rpc', lambda request: rpc)

    def test_every_route_needs_a_signed_in_customer(self):
        c = self.new_client()
        self.assertEqual(c.get('/v1/devices', secure=True).status_code, 401)
        self.assertEqual(self.post(c, '/v1/devices/pair').status_code, 401)
        self.assertEqual(self.post(c, '/v1/devices/a1b2c3d4e5f60718/revoke').status_code, 401)

    def test_the_list_passes_through_and_degrades_to_unavailable_when_the_service_is_down(self):
        a = self.signed()
        with self.patched(FakeRpc({'device_list': {'allowed': True, 'use': True, 'connected': True, 'devices': [DEVICE]}})):
            r = a.get('/v1/devices', secure=True); self.assertEqual(r.status_code, 200); self.assertEqual(r.json(), {'available': True, 'use': True, 'connected': True, 'devices': [DEVICE]})
        with self.patched(FakeRpc({'device_list': {'allowed': False, 'devices': []}})):
            self.assertEqual(a.get('/v1/devices', secure=True).json(), {'available': False, 'use': False, 'connected': False, 'devices': []})
        with self.patched(FakeRpc(down=True)):
            self.assertEqual(a.get('/v1/devices', secure=True).json(), {'available': False, 'use': False, 'connected': False, 'devices': []})

    def test_pairing_returns_a_readable_code_and_is_refused_where_it_is_not_allowed(self):
        a = self.signed()
        rpc = FakeRpc({'device_pair': {'allowed': True, 'code': 'ABCD2345', 'expires_in': 600}})
        with self.patched(rpc):
            r = self.post(a, '/v1/devices/pair'); self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json(), {'code': 'ABCD2345', 'display': 'ABCD-2345', 'expires_in': 600})
        self.assertEqual(rpc.calls, [('device_pair', {})])
        self.assertEqual(Audit.objects.filter(action='devices.pair', outcome='completed').count(), 1)
        self.assertNotIn('ABCD2345', ''.join(str(vars(a)) for a in Audit.objects.all()), 'the code itself is never written to the audit trail')
        with self.patched(FakeRpc({'device_pair': {'allowed': False}})):
            r = self.post(a, '/v1/devices/pair'); self.assertEqual((r.status_code, r.json()['error']), (409, 'not_available'))
        with self.patched(FakeRpc(down=True)):
            self.assertEqual(self.post(a, '/v1/devices/pair').status_code, 503)

    def test_pairing_is_rate_limited(self):
        a = self.signed()
        with self.patched(FakeRpc({'device_pair': {'allowed': True, 'code': 'ABCD2345', 'expires_in': 600}})):
            codes = [self.post(a, '/v1/devices/pair').status_code for _ in range(12)]
        self.assertEqual(codes[:10], [200] * 10); self.assertEqual(codes[10:], [429, 429])

    def test_revoking_checks_the_id_and_hides_other_accounts_devices(self):
        a = self.signed()
        rpc = FakeRpc({'device_revoke': {'ok': True}})
        with self.patched(rpc):
            self.assertEqual(self.post(a, '/v1/devices/a1b2c3d4e5f60718/revoke').json(), {'ok': True})
            self.assertEqual(rpc.calls, [('device_revoke', {'device_id': 'a1b2c3d4e5f60718'})])
            self.assertEqual(Audit.objects.filter(action='devices.revoke', object_id='a1b2c3d4e5f60718').count(), 1)
            for bad in ('../etc', 'ZZZZZZZZZZZZZZZZ', 'a1b2', 'a1b2c3d4e5f60718a'):
                self.assertEqual(self.post(a, f'/v1/devices/{bad}/revoke').status_code, 404, bad)
            self.assertEqual(len(rpc.calls), 1, 'a malformed id never reaches the service')
        with self.patched(FakeRpc({'device_revoke': {'ok': False}})):
            self.assertEqual(self.post(a, '/v1/devices/a1b2c3d4e5f60718/revoke').status_code, 404)       # not yours or already gone: the same answer
        with self.patched(FakeRpc(down=True)):
            self.assertEqual(self.post(a, '/v1/devices/a1b2c3d4e5f60718/revoke').status_code, 503)

    def test_the_switch_takes_a_real_true_or_false_and_is_audited(self):
        a = self.signed(); rpc = FakeRpc({'device_use': {'allowed': True, 'use': True}})
        with self.patched(rpc):
            self.assertEqual(self.post(a, '/v1/devices/use', {'on': True}).json(), {'use': True})
            self.assertEqual(rpc.calls, [('device_use', {'on': True})])
            for bad in ({'on': 'true'}, {'on': 1}, {'on': None}, {}, {'on': True, 'extra': 1}):
                self.assertEqual(self.post(a, '/v1/devices/use', bad).status_code, 400, bad)
            self.assertEqual(len(rpc.calls), 1, 'a malformed request never reaches the service')
        self.assertEqual(Audit.objects.filter(action='devices.use.on', outcome='completed').count(), 1)
        with self.patched(FakeRpc({'device_use': {'allowed': True, 'use': False}})):
            self.assertEqual(self.post(a, '/v1/devices/use', {'on': False}).json(), {'use': False})
        self.assertEqual(Audit.objects.filter(action='devices.use.off').count(), 1)
        with self.patched(FakeRpc({'device_use': {'allowed': False}})):
            self.assertEqual(self.post(a, '/v1/devices/use', {'on': True}).status_code, 409)
        with self.patched(FakeRpc(down=True)):
            self.assertEqual(self.post(a, '/v1/devices/use', {'on': True}).status_code, 503)
        self.assertEqual(self.post(self.new_client(), '/v1/devices/use', {'on': True}).status_code, 401)

    def test_the_service_is_asked_as_the_signed_in_account_only(self):
        a = self.signed('a'); seen = []
        def make(request): seen.append(request.account_id); return FakeRpc({'device_list': {'allowed': True, 'devices': []}})
        with mock.patch('accounts.devices._rpc', make):
            a.get('/v1/devices', secure=True)
        self.assertEqual(seen, ['a'])
