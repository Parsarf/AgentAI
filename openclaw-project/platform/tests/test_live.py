import http.client
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from agentai_platform.live import ticket
from agentai_platform.live.gateway import FrameGateway, make_server

RID = 'b' * 32
OTHER = 'c' * 32
SECRET = b's' * 40


class TicketTests(unittest.TestCase):
    def test_round_trip_is_bound_to_one_task_and_one_account(self):
        t = ticket.mint(SECRET, 'acct1', RID)
        self.assertEqual(ticket.verify(SECRET, t, RID), 'acct1')
        with self.assertRaises(ticket.TicketError):
            ticket.verify(SECRET, t, OTHER)                         # another task's frames are not covered

    def test_expiry_tamper_and_wrong_secret_are_refused(self):
        now = [1000.0]
        t = ticket.mint(SECRET, 'a', RID, now=lambda: now[0], ttl=60)
        now[0] += 61
        with self.assertRaises(ticket.TicketError):
            ticket.verify(SECRET, t, RID, now=lambda: now[0])
        fresh = ticket.mint(SECRET, 'a', RID)
        head, body, sig = fresh.split('.')
        for bad in (f'{head}.{body}x.{sig}', f'{head}.{body}.{sig[:-2]}AA', fresh + '.x', '', 'v1..', 'v2.' + body + '.' + sig):
            with self.assertRaises(ticket.TicketError):
                ticket.verify(SECRET, bad, RID)
        with self.assertRaises(ticket.TicketError):
            ticket.verify(b'z' * 40, fresh, RID)
        with self.assertRaises(ticket.TicketError):
            ticket.mint(b'', 'a', RID)
        with self.assertRaises(ticket.TicketError):
            ticket.mint(SECRET, 'a', '../etc')


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / RID / 'out'
        self.out.mkdir(parents=True)
        self.gw = FrameGateway(self.tmp.name, SECRET, hold=0.3)
        self.t = ticket.mint(SECRET, 'a', RID)

    def tearDown(self):
        self.tmp.cleanup()

    def frame(self, after=0, t=None, rid=RID):
        return self.gw.frame(rid, self.t if t is None else t, after)

    def test_no_frame_yet_holds_briefly_then_204_and_marks_the_task_as_watched(self):
        status, headers, body = self.frame()
        self.assertEqual((status, body), (204, b''))
        self.assertTrue((self.out / 'watching').exists())             # this is what switches the screencast on

    def test_new_frame_is_returned_once_then_204_until_it_changes(self):
        (self.out / 'live.jpg').write_bytes(b'\xff\xd8one')
        status, headers, body = self.frame()
        self.assertEqual((status, body, headers['Content-Type']), (200, b'\xff\xd8one', 'image/jpeg'))
        seq = int(headers['X-Seq'])
        self.assertEqual(self.frame(after=seq)[0], 204)
        os.utime(self.out / 'live.jpg', ns=(seq + 5_000_000, seq + 5_000_000))
        (self.out / 'live.jpg').write_bytes(b'\xff\xd8two')
        self.assertEqual(self.frame(after=seq)[0], 200)

    def test_waiting_client_gets_the_frame_as_soon_as_it_lands(self):
        gw = FrameGateway(self.tmp.name, SECRET, hold=3)
        threading.Timer(0.15, lambda: (self.out / 'live.jpg').write_bytes(b'\xff\xd8late')).start()
        started = time.monotonic()
        status, _, body = gw.frame(RID, self.t, 0)
        self.assertEqual((status, body), (200, b'\xff\xd8late'))
        self.assertLess(time.monotonic() - started, 1.5)

    def test_bad_ticket_wrong_task_missing_task_and_oversized_frame(self):
        self.assertEqual(self.frame(t='nope')[0], 403)
        self.assertEqual(self.frame(rid=OTHER)[0], 403)                # ticket is for RID only
        other_ticket = ticket.mint(SECRET, 'a', OTHER)
        self.assertEqual(self.frame(t=other_ticket, rid=OTHER)[0], 404)  # signed, but no such running task
        (self.out / 'live.jpg').write_bytes(b'x' * 3_000_001)
        self.assertEqual(self.frame()[0], 204)                          # never serve a runaway file

    def test_a_large_but_plausible_frame_is_served_instead_of_freezing_the_picture(self):
        (self.out / 'live.jpg').write_bytes(b'\xff\xd8' + b'x' * 1_500_000)      # a photo-heavy page at 1280x800
        status, headers, body = self.frame()
        self.assertEqual((status, len(body)), (200, 1_500_002))

    def test_too_many_waiters_are_told_to_retry_instead_of_piling_up(self):
        gw = FrameGateway(self.tmp.name, SECRET, hold=0.6, max_waiters=1)
        results = []
        first = threading.Thread(target=lambda: results.append(gw.frame(RID, self.t, 0)[0]))
        first.start(); time.sleep(0.1)
        self.assertEqual(gw.frame(RID, self.t, 0)[0], 429)
        first.join(); self.assertEqual(results, [204])

    def test_http_layer_routes_methods_and_headers(self):
        (self.out / 'live.jpg').write_bytes(b'\xff\xd8http')
        server = make_server(self.gw, '127.0.0.1', 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            conn = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=5)
            conn.request('GET', f'/v1/live/{RID}/frame?t={self.t}&after=0')
            r = conn.getresponse(); body = r.read()
            self.assertEqual((r.status, body), (200, b'\xff\xd8http'))
            self.assertEqual(r.getheader('Cache-Control'), 'no-store'); self.assertEqual(r.getheader('X-Content-Type-Options'), 'nosniff')
            conn.request('GET', f'/live/{RID}/frame?t={self.t}&after={r.getheader("X-Seq")}')   # same connection: keep-alive works
            r = conn.getresponse(); r.read(); self.assertEqual(r.status, 204)
            for method, path, want in (('GET', '/v1/live/xyz/frame?t=1', 404), ('GET', f'/v1/live/{RID}/other', 404), ('POST', f'/v1/live/{RID}/frame', 405),
                                       ('GET', f'/live/{RID}/frame?t={self.t}&after={r.getheader("X-Seq")}', 204), ('GET', f'/v2/live/{RID}/frame?t={self.t}', 404),
                                       ('GET', f'/v1/live/{RID}/frame?t=bad', 403), ('GET', '/' + 'a' * 700, 414)):
                conn.request(method, path); r = conn.getresponse(); r.read(); self.assertEqual(r.status, want, (method, path))
        finally:
            conn.close(); server.shutdown(); server.server_close()


if __name__ == '__main__':
    unittest.main()
