"""Side-panel plumbing below the web app: tickets, the worker's offer, the browse service's relay, and the driver hook."""
import json
import tempfile
import unittest
from pathlib import Path

from agentai_platform.browse import devices as dv
from agentai_platform.browse.devices import DeviceDesk, DeviceError, DeviceHub, DeviceStore, panel_message
from agentai_platform.chat_driver import ChatDriver
from agentai_platform.live import ticket as live_ticket
from agentai_platform.panel import ticket as pt
from agentai_platform.panel.offer import PanelOffer, read_secret
from agentai_platform.request_queue import RequestClaim

SECRET = b's' * 40
DEVICE = 'a1b2c3d4e5f60718'


class Clock:
    def __init__(self, t=1000.0): self.t = t
    def __call__(self): return self.t


class TicketChecks(unittest.TestCase):
    def test_round_trip_carries_exactly_the_four_claims(self):
        t = pt.mint(SECRET, 'acct-1', 'user-9', 'conv_1', DEVICE, now=lambda: 1000)
        self.assertEqual(pt.verify(SECRET, t, now=lambda: 1001), {'account': 'acct-1', 'actor': 'user-9', 'conversation': 'conv_1', 'device': DEVICE})
        self.assertLess(len(t), pt.MAX_TICKET)

    def test_expires_after_its_short_life(self):
        t = pt.mint(SECRET, 'a', 'u', 'c', DEVICE, now=lambda: 1000)
        pt.verify(SECRET, t, now=lambda: 1000 + pt.TTL_SECONDS)
        with self.assertRaises(pt.TicketError):
            pt.verify(SECRET, t, now=lambda: 1000 + pt.TTL_SECONDS + 1)

    def test_tampering_wrong_key_and_garbage_are_all_refused(self):
        t = pt.mint(SECRET, 'a', 'u', 'c', DEVICE)
        prefix, body, sig = t.split('.')
        other = pt.mint(SECRET, 'b', 'u', 'c', DEVICE).split('.')[1]
        for bad in [f'{prefix}.{other}.{sig}', f'{prefix}.{body}.{sig[:-2]}AA', t + 'x', 'p1.a.b', 'nonsense', '', None, 5, 'x' * 2000]:
            with self.assertRaises(pt.TicketError):
                pt.verify(SECRET, bad)
        with self.assertRaises(pt.TicketError):
            pt.verify(b'k' * 40, t)
        with self.assertRaises(pt.TicketError):
            pt.verify(b'', t)

    def test_a_live_view_ticket_is_never_a_panel_ticket_even_with_the_same_key(self):
        live = live_ticket.mint(SECRET, 'a', 'f' * 32)
        with self.assertRaises(pt.TicketError):
            pt.verify(SECRET, live)

    def test_cannot_mint_with_weak_key_or_bad_ids(self):
        for args in [(b'short', 'a', 'u', 'c', DEVICE), (SECRET, '', 'u', 'c', DEVICE), (SECRET, 'a', 'u', 'c d', DEVICE), (SECRET, 'a', 'u', 'c', 'XYZ'), (SECRET, 'a', 'u', 'c', '')]:
            with self.assertRaises(pt.TicketError):
                pt.mint(*args)


class FakeRpc:
    def __init__(self, state=None, pushed=True, fail=False):
        self.calls, self.state, self.pushed, self.fail = [], state, pushed, fail
    def __call__(self, op, **params):
        self.calls.append((op, params))
        if self.fail: raise RuntimeError('down')
        return self.state if op == 'device_list' else {'pushed': self.pushed}


def claim(conversation='conv_1'):
    return RequestClaim('acct-1', 'r' * 32, 'p', 'user-9', 'hi', 1, 'owner', conversation)


GOOD = {'allowed': True, 'use': True, 'connected': True, 'devices': [{'device_id': DEVICE, 'connected': True}]}


class OfferChecks(unittest.TestCase):
    def offer(self, rpc, clock=None, secret=SECRET, enabled=lambda: True):
        return PanelOffer(lambda: secret, lambda account: rpc, clock=clock or Clock(), enabled=enabled)

    def test_pushes_a_ticket_bound_to_the_connected_computer_and_this_conversation(self):
        rpc = FakeRpc(GOOD)
        self.assertTrue(self.offer(rpc).tick(claim()))
        op, params = rpc.calls[-1]
        self.assertEqual(op, 'device_push')
        payload = params['payload']
        self.assertEqual(pt.verify(SECRET, payload['ticket'], now=lambda: 1000), {'account': 'acct-1', 'actor': 'user-9', 'conversation': 'conv_1', 'device': DEVICE})
        self.assertEqual((payload['conversation_id'], payload['device_id'], payload['expires_in']), ('conv_1', DEVICE, pt.TTL_SECONDS))
        self.assertIsNotNone(panel_message(payload))

    def test_throttled_then_fresh_again_after_the_interval(self):
        clock, rpc = Clock(), FakeRpc(GOOD)
        offer = self.offer(rpc, clock)
        self.assertTrue(offer.tick(claim()))
        clock.t += 5
        self.assertFalse(offer.tick(claim()))
        clock.t += 30
        self.assertTrue(offer.tick(claim()))

    def test_when_nothing_could_be_handed_over_it_tries_again_in_a_few_seconds_not_half_a_minute(self):
        clock, rpc = Clock(), FakeRpc({**GOOD, 'devices': []})
        offer = self.offer(rpc, clock)
        self.assertFalse(offer.tick(claim()))
        clock.t += 2; self.assertFalse(offer.tick(claim())); self.assertEqual(len(rpc.calls), 1)       # not asked again on every pass of the loop
        rpc.state = GOOD; clock.t += 4
        self.assertTrue(offer.tick(claim()))                                                            # the computer connected: the ticket arrives within seconds
        clock.t += 29; self.assertFalse(offer.tick(claim()))
        clock.t += 2; self.assertTrue(offer.tick(claim()))

    def test_does_nothing_without_key_switch_computer_or_choice(self):
        for state in [{**GOOD, 'use': False}, {**GOOD, 'allowed': False}, {**GOOD, 'devices': [{'device_id': DEVICE, 'connected': False}]}, {**GOOD, 'devices': []}]:
            rpc = FakeRpc(state)
            self.assertFalse(self.offer(rpc).tick(claim()))
            self.assertNotIn('device_push', [c[0] for c in rpc.calls])
        rpc = FakeRpc(GOOD)
        self.assertFalse(self.offer(rpc, secret=b'').tick(claim()))
        self.assertFalse(self.offer(rpc, enabled=lambda: False).tick(claim()))
        self.assertFalse(self.offer(rpc).tick(claim(None)))
        self.assertEqual(rpc.calls, [])

    def test_a_failing_service_never_raises_and_a_refused_push_is_not_success(self):
        self.assertFalse(self.offer(FakeRpc(GOOD, fail=True)).tick(claim()))
        self.assertFalse(self.offer(FakeRpc(GOOD, pushed=False)).tick(claim()))

    def test_read_secret_needs_32_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            ok, short = Path(d, 'ok'), Path(d, 'short')
            ok.write_bytes(b'k' * 32 + b'\n'); short.write_bytes(b'k' * 31)
            self.assertEqual(read_secret(str(ok)), b'k' * 32)
            self.assertEqual((read_secret(str(short)), read_secret(str(Path(d, 'none'))), read_secret('')), (b'', b'', b''))


class Conn:
    def __init__(self): self.sent, self.closed = [], None
    def send_text(self, text): self.sent.append(json.loads(text))
    def close(self, code=1000, reason=''): self.closed = (code, reason)


class RelayChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.hub = DeviceHub()
        self.desk = DeviceDesk(DeviceStore(Path(self.tmp.name) / 'd.json'), self.hub)
        self.ticket = pt.mint(SECRET, 'acct-1', 'user-9', 'conv_1', DEVICE)
        self.payload = {'ticket': self.ticket, 'conversation_id': 'conv_1', 'device_id': DEVICE, 'expires_in': 90}

    def test_relays_the_fixed_message_to_the_named_computer_only(self):
        conn = Conn(); self.hub.attach('acct-1', DEVICE, conn)
        self.assertEqual(self.desk.push_panel('acct-1', self.payload), {'pushed': True})
        self.assertEqual(conn.sent, [{'panel': self.payload}])
        other = Conn(); self.hub.attach('acct-2', 'b' * 16, other)
        self.assertEqual(self.desk.push_panel('acct-2', self.payload), {'pushed': False})      # a ticket naming a different computer
        self.assertEqual(other.sent, [])

    def test_nothing_is_sent_when_no_computer_is_connected_or_it_has_left(self):
        self.assertEqual(self.desk.push_panel('acct-1', self.payload), {'pushed': False})
        conn = Conn(); link = self.hub.attach('acct-1', DEVICE, conn); link.close('gone')
        self.assertEqual(self.desk.push_panel('acct-1', self.payload), {'pushed': False})

    def test_anything_off_the_fixed_shape_is_refused(self):
        conn = Conn(); self.hub.attach('acct-1', DEVICE, conn)
        bad = [None, 'x', {}, {**self.payload, 'extra': 1}, {**self.payload, 'ticket': 'v1.a.b'}, {**self.payload, 'ticket': 'p1.a b.c'}, {**self.payload, 'expires_in': 0},
               {**self.payload, 'expires_in': '90'}, {**self.payload, 'expires_in': 601}, {**self.payload, 'device_id': 'nope'}, {**self.payload, 'conversation_id': '../x'},
               {'clear': True, 'conversation_id': 'conv_1'}, {**self.payload, 'ticket': 5}]
        for payload in bad:
            with self.assertRaises(DeviceError):
                self.desk.push_panel('acct-1', payload)
        self.assertEqual(conn.sent, [])


class DriverHookChecks(unittest.TestCase):
    def driver(self, panel):
        return ChatDriver(None, ledger=None, gateway_factory=lambda c: None, panel=panel)

    def test_driver_asks_the_panel_and_never_fails_because_of_it(self):
        class Boom:
            def tick(self, c): raise RuntimeError('x')
        class Spy:
            def __init__(self): self.seen = []
            def tick(self, c): self.seen.append(c)
        spy = Spy(); self.driver(spy)._panel_tick('c1')
        self.assertEqual(spy.seen, ['c1'])
        self.driver(Boom())._panel_tick('c1')
        self.driver(None)._panel_tick('c1')


if __name__ == '__main__':
    unittest.main()
