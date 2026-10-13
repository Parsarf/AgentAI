"""App-side client for the host browse service (private unix socket; no secrets, no docker)."""
from __future__ import annotations
import base64
import json
import socket

from agentai_platform.adapters import CapabilityUnavailable


class BrowseRpc:
    def __init__(self, account_id, socket_path, *, timeout=30):
        self.account_id, self.path, self.timeout = account_id, str(socket_path), timeout

    def __call__(self, op, **params):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(self.timeout)
            sock.connect(self.path)
            sock.sendall((json.dumps({'account_id': self.account_id, 'op': op, **params}) + '\n').encode())
            data = b''
            while not data.endswith(b'\n'):
                chunk = sock.recv(1 << 20)
                if not chunk:
                    break
                data += chunk
        except OSError as exc:
            raise CapabilityUnavailable('browse service unavailable') from exc
        finally:
            sock.close()
        try:
            reply = json.loads(data)
        except ValueError as exc:
            raise CapabilityUnavailable('browse service reply invalid') from exc
        if not reply.get('ok'):
            raise CapabilityUnavailable('browse service refused')
        return reply.get('result') or {}

    def shot(self, request_id, name):
        return base64.b64decode(self('shot', request_id=request_id, file=name)['jpeg_b64'])
