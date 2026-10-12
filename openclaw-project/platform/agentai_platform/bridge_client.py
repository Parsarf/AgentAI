"""App-side client for the host cell bridge (a private unix socket; no secrets, no docker)."""
import json
import socket

from .adapters import CapabilityUnavailable


class BridgeRpc:
    """``rpc(method, params)`` for one account; plugs into NativeGateway."""

    def __init__(self, account_id, socket_path, *, timeout=180, connect=socket.socket):
        self.account_id, self.path, self.timeout, self._connect = account_id, socket_path, timeout, connect

    def __call__(self, method, params):
        sock = self._connect(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(self.timeout)
            sock.connect(self.path)
            sock.sendall((json.dumps({'account_id': self.account_id, 'method': method, 'params': params}) + '\n').encode())
            data = b''
            while not data.endswith(b'\n'):
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data += chunk
        except OSError as exc:
            raise CapabilityUnavailable('cell bridge unavailable') from exc
        finally:
            sock.close()
        try:
            reply = json.loads(data)
        except ValueError as exc:
            raise CapabilityUnavailable('cell bridge reply invalid') from exc
        if not isinstance(reply, dict) or not reply.get('ok'):
            raise CapabilityUnavailable('cell bridge refused')
        return reply.get('result') or {}
