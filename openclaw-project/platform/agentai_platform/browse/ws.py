"""The server side of a WebSocket (RFC 6455), standard library only, and strict on purpose: the one client is our own extension.

Text frames only, no extensions or compression, every client frame masked, messages up to MAX_MESSAGE bytes, valid UTF-8. Anything else ends the connection.
"""
from __future__ import annotations
import base64
import hashlib
import socket
import struct
import threading

GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
MAX_MESSAGE = 8 * 1024 * 1024          # a 1280x800 picture is a few hundred KB as base64; this leaves room and stops anything absurd


class WsClosed(Exception):
    """The connection is over (the peer left, was too slow, or broke the rules)."""


def accept_key(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()


def valid_key(key) -> bool:
    try:
        return isinstance(key, str) and len(base64.b64decode(key, validate=True)) == 16
    except ValueError:
        return False


def unmask(data: bytes, mask: bytes) -> bytes:
    if not data:
        return b''
    key = (mask * (len(data) // 4 + 1))[:len(data)]
    return (int.from_bytes(data, 'big') ^ int.from_bytes(key, 'big')).to_bytes(len(data), 'big')


def frame(opcode: int, payload: bytes) -> bytes:
    n = len(payload)
    head = bytes([0x80 | opcode, n]) if n < 126 else bytes([0x80 | opcode, 126]) + struct.pack('>H', n) if n < 65536 else bytes([0x80 | opcode, 127]) + struct.pack('>Q', n)
    return head + payload


class Connection:
    """After the HTTP upgrade. `rfile` is the handler's buffered reader (it may already hold bytes), `sock` the connection."""

    def __init__(self, sock, rfile, *, max_message=MAX_MESSAGE):
        self.sock, self.rfile, self.max_message = sock, rfile, max_message
        self._send_lock, self.closed = threading.Lock(), False

    def set_timeout(self, seconds):
        self.sock.settimeout(seconds)

    def _read(self, n):
        try:
            data = self.rfile.read(n)
        except (OSError, ValueError) as exc:               # timeout, reset, closed under us
            raise WsClosed(type(exc).__name__) from exc
        if data is None or len(data) < n:
            raise WsClosed('eof')
        return data

    def recv(self) -> str:
        """The next whole text message. Pings are answered here; the peer's close is answered and raised as WsClosed."""
        parts, size, open_message = [], 0, False
        while True:
            b0, b1 = self._read(2)
            fin, rsv, op = bool(b0 & 0x80), b0 & 0x70, b0 & 0x0F
            if rsv:
                self.close(1002, 'extensions not negotiated'); raise WsClosed('rsv')
            if not b1 & 0x80:
                self.close(1002, 'client frames must be masked'); raise WsClosed('unmasked')
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack('>H', self._read(2))[0]
            elif n == 127:
                n = struct.unpack('>Q', self._read(8))[0]
            if op & 8 and (n > 125 or not fin):
                self.close(1002, 'bad control frame'); raise WsClosed('control')
            if size + n > self.max_message:
                self.close(1009, 'message too big'); raise WsClosed('too big')
            mask = self._read(4)
            data = unmask(self._read(n), mask)
            if op == 8:
                self.close(1000, ''); raise WsClosed('peer closed')
            if op == 9:
                self._send(0xA, data); continue
            if op == 0xA:
                continue
            if op in (1, 0):
                if (op == 1) == open_message:                       # a new text frame inside a message, or a continuation with nothing to continue
                    self.close(1002, 'bad fragmentation'); raise WsClosed('fragments')
                open_message = True
                parts.append(data); size += n
                if fin:
                    try:
                        return b''.join(parts).decode('utf-8')
                    except UnicodeDecodeError:
                        self.close(1007, 'not utf-8'); raise WsClosed('utf8')
                continue
            self.close(1003, 'text only'); raise WsClosed('opcode')

    def _send(self, opcode, payload):
        with self._send_lock:
            if self.closed and opcode != 8:
                raise WsClosed('closed')
            try:
                self.sock.sendall(frame(opcode, payload))
            except OSError as exc:
                self.closed = True
                raise WsClosed(type(exc).__name__) from exc

    def send_text(self, text: str):
        self._send(1, text.encode())

    def close(self, code=1000, reason=''):
        if self.closed:
            return
        try:
            self._send(8, struct.pack('>H', code) + reason.encode()[:100])
        except WsClosed:
            pass
        self.closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
