"""What the customer's pages can ask the browse service about their computers, over the service's private socket."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest

from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.browse import devices as dv
from agentai_platform.browse import service as svc
from agentai_platform.browse.client import BrowseRpc


class FakeConn:
    def __init__(self): self.closed = None
    def send_text(self, text): pass
    def close(self, code=1000, reason=''): self.closed = (code, reason)


class DeskChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = dv.DeviceStore(Path(self.tmp.name) / 'd.json'); self.hub = dv.DeviceHub(); self.allowed = {'acct'}
        self.desk = dv.DeviceDesk(self.store, self.hub, allowed=lambda a: a in self.allowed)

    def serve(self, desk='default'):
        service = svc.BrowseService(spawn=lambda *a: None, root=self.tmp.name, jev_mode='off', devices=self.desk if desk == 'default' else desk)
        path = os.path.join(self.tmp.name, 'b.sock'); server = svc.serve(service, path, allowed_uids={os.getuid()}, peer_uid=lambda sock: os.getuid())
        threading.Thread(target=server.serve_forever, daemon=True).start(); self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        return path

    def test_pair_list_and_revoke_through_the_socket_are_scoped_to_the_account(self):
        path = self.serve(); rpc, other = BrowseRpc('acct', path), BrowseRpc('someone-else', path)
        self.assertEqual(rpc('device_list'), {'allowed': True, 'use': False, 'connected': False, 'devices': []})
        made = rpc('device_pair'); self.assertTrue(made['allowed']); self.assertEqual(made['expires_in'], dv.PAIR_TTL); self.assertEqual(len(made['code']), dv.CODE_LENGTH)
        device = self.store.redeem(made['code'], 'Mac')
        link = self.hub.attach('acct', device['device_id'], FakeConn())
        listed = rpc('device_list')['devices']; self.assertEqual([(d['label'], d['connected']) for d in listed], [('Mac', True)])
        self.assertNotIn('token', json.dumps(listed))
        self.assertEqual(other('device_list'), {'allowed': False, 'use': False, 'connected': False, 'devices': []})               # another account sees nothing of it, and is not allowed
        self.assertEqual(other('device_revoke', device_id=device['device_id']), {'ok': False}); self.assertTrue(link.alive)
        self.assertEqual(rpc('device_revoke', device_id=device['device_id']), {'ok': True})
        self.assertFalse(link.alive); self.assertEqual(link.conn.closed[0], 4403); self.assertEqual(rpc('device_list')['devices'], [])

    def test_the_switch_is_set_per_account_and_only_true_means_on(self):
        rpc, other = BrowseRpc('acct', self.serve()), BrowseRpc('someone-else', os.path.join(self.tmp.name, 'b.sock'))
        self.assertEqual(rpc('device_use', on=True), {'allowed': True, 'use': True}); self.assertTrue(rpc('device_list')['use'])
        self.assertTrue(self.store.wants_local('acct')); self.assertFalse(self.store.wants_local('someone-else'))
        for not_true in ('true', 1, 'yes', None, [True]): self.assertEqual(rpc('device_use', on=not_true), {'allowed': True, 'use': False}, repr(not_true))
        self.assertEqual(other('device_use', on=True), {'allowed': False}); self.assertFalse(self.store.wants_local('someone-else'))
        self.allowed.clear(); self.assertEqual(rpc('device_use', on=True), {'allowed': False})           # switched off for everyone: nobody can turn it on

    def test_the_list_says_whether_a_computer_is_connected_at_all(self):
        device = self.store.redeem(self.store.pair('acct'), 'Mac')
        self.assertFalse(self.desk.listing('acct')['connected'])
        self.hub.attach('acct', device['device_id'], FakeConn()); self.assertTrue(self.desk.listing('acct')['connected'])

    def test_an_account_that_is_not_let_in_cannot_pair(self):
        rpc = BrowseRpc('nobody', self.serve())
        self.assertEqual(rpc('device_pair'), {'allowed': False}); self.assertEqual(self.store.devices('nobody'), [])

    def test_a_service_without_devices_refuses_the_operations(self):
        rpc = BrowseRpc('acct', self.serve(desk=None))
        for op in ('device_list', 'device_pair', 'device_revoke'):
            with self.assertRaises(CapabilityUnavailable): rpc(op, device_id='0' * 16)

    def test_the_list_shows_which_computer_is_connected_now_and_oldest_first(self):
        old = self.store.redeem(self.store.pair('acct'), 'Old'); new = self.store.redeem(self.store.pair('acct'), 'New')
        self.hub.attach('acct', new['device_id'], FakeConn())
        d = self.desk.listing('acct')['devices']
        self.assertEqual({x['device_id']: x['connected'] for x in d}, {old['device_id']: False, new['device_id']: True})


if __name__ == '__main__':
    unittest.main()
