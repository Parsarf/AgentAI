"""JEV calls connect over IPv4: the server has no working IPv6, and trying a host's IPv6 addresses first cost 3 to 6 seconds per call."""
import socket
import unittest
from unittest import mock

from agentai_platform.routing import classifier


class Connection(unittest.TestCase):
    def conn(self):
        c = classifier._V4Connection('api.example.test', 443, timeout=7)
        c._context = mock.Mock(); c._context.wrap_socket.side_effect = lambda sock, server_hostname: ('tls', sock, server_hostname)
        return c

    def test_only_ipv4_addresses_are_asked_for_and_the_name_is_kept_for_tls(self):
        sock = mock.Mock()
        with mock.patch.object(socket, 'getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('104.18.1.1', 443))]) as gai, mock.patch.object(socket, 'socket', return_value=sock):
            c = self.conn(); c.connect()
        gai.assert_called_once_with('api.example.test', 443, socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout.assert_called_with(7); sock.connect.assert_called_with(('104.18.1.1', 443)); self.assertEqual(c.sock[2], 'api.example.test')

    def test_the_next_ipv4_address_is_tried_when_one_fails_and_the_last_error_is_raised_when_all_do(self):
        bad, good = mock.Mock(), mock.Mock(); bad.connect.side_effect = OSError('refused')
        entries = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.1.1.1', 443)), (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('2.2.2.2', 443))]
        with mock.patch.object(socket, 'getaddrinfo', return_value=entries), mock.patch.object(socket, 'socket', side_effect=[bad, good]):
            c = self.conn(); c.connect()
        bad.close.assert_called_once(); self.assertIs(c.sock[1], good)
        dead = [mock.Mock(), mock.Mock()]
        for d in dead: d.connect.side_effect = OSError('down')
        with mock.patch.object(socket, 'getaddrinfo', return_value=entries), mock.patch.object(socket, 'socket', side_effect=dead):
            with self.assertRaises(OSError): self.conn().connect()

    def test_a_host_with_no_ipv4_address_uses_the_normal_connection(self):
        with mock.patch.object(socket, 'getaddrinfo', side_effect=socket.gaierror('no A record')), mock.patch.object(classifier.http.client.HTTPSConnection, 'connect') as normal:
            self.conn().connect()
        normal.assert_called_once()


if __name__ == '__main__':
    unittest.main()
