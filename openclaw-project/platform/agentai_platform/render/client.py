"""App-side client for the host render service (private unix socket; the app starts no container and parses no document)."""
from __future__ import annotations
import json
import socket

from ..adapters import CapabilityUnavailable

MAX_REPLY_BYTES = 110 * 1024 * 1024


class RenderRefused(Exception):
    """The service answered with a reason (a format it does not write, a file it could not read). The text is safe to pass on."""


class RenderRpc:
    def __init__(self, socket_path, *, timeout=300, connect=socket.socket):
        self.path, self.timeout, self._connect = str(socket_path), timeout, connect

    def convert(self, source, target, files, *, preview=True):
        """files: {workspace-relative path: bytes}; target None = preview only. -> {'data': bytes | None, 'preview': bytes | None, 'pages': int | None}.
        Raises RenderRefused (with a reason) or CapabilityUnavailable (the service is not there)."""
        header = {'op': 'convert', 'source': source, 'target': target, 'preview': bool(preview), 'files': [{'path': path, 'size': len(data)} for path, data in files.items()]}
        sock = self._connect(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(self.timeout)
            sock.connect(self.path)
            sock.sendall((json.dumps(header) + '\n').encode())
            for data in files.values():
                sock.sendall(data)
            sock.shutdown(socket.SHUT_WR)
            chunks, size = [], 0
            while True:
                chunk = sock.recv(1 << 20)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_REPLY_BYTES:
                    raise CapabilityUnavailable('render service reply too large')
                chunks.append(chunk)
        except OSError as exc:
            raise CapabilityUnavailable('render service unavailable') from exc
        finally:
            sock.close()
        raw = b''.join(chunks)
        line, _, body = raw.partition(b'\n')
        try:
            reply = json.loads(line)
        except ValueError as exc:
            raise CapabilityUnavailable('render service reply invalid') from exc
        if not isinstance(reply, dict):
            raise CapabilityUnavailable('render service reply invalid')
        if not reply.get('ok'):
            raise RenderRefused(str(reply.get('error') or 'The conversion failed')[:160])
        size, shot = reply.get('size'), reply.get('preview_size')
        if type(size) is not int or type(shot) is not int or size < 0 or shot < 0 or size + shot != len(body):
            raise CapabilityUnavailable('render service reply invalid')
        return {'data': body[:size] or None, 'preview': body[size:] or None, 'pages': reply.get('pages') if type(reply.get('pages')) is int else None}
