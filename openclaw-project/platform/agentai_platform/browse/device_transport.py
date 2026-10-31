"""The runner protocol over a paired computer: the same surface as ProcessTransport and NativeTransport (send / recv / close), so Session, the ladder and the loop
are unchanged. The extension (browse/extension/src/executor.js) does the commands; this side only carries them and keeps the pictures.

Pictures: the extension returns them as base64 in `data`. The runner keeps files in the job's folder and answers with the file name, so this side writes
shot-NNN.jpg (`screenshot` always, `view` when asked to save) exactly as the other engines do. Whatever arrives as a picture must really be a small JPEG.
"""
from __future__ import annotations
import base64
import binascii
from collections import deque
from pathlib import Path

MAX_PICTURE = 3_000_000                     # same ceiling as the live frames: a larger file is not a screenshot of a page


class DeviceTransport:
    def __init__(self, link, out_dir):
        self.link, self.out, self.shots, self._pending = link, Path(out_dir), 0, {}
        self.stderr_tail = deque(maxlen=20)
        self.closed, self._told = False, False
        link.begin()

    def send(self, obj):
        if self.closed:
            raise BrokenPipeError('browser closed')
        if obj.get('cmd') == 'close' and obj.get('id') == 0:
            return self._close_remote(obj)
        self._pending[obj.get('id')] = (obj.get('cmd'), bool(obj.get('save')))
        self.link.send(obj)

    def recv(self, timeout):
        reply = self.link.recv(timeout)
        cmd, save = self._pending.pop(reply.get('id'), (None, False))
        if cmd in ('screenshot', 'view') and reply.get('ok'):
            reply = self._picture(reply, keep=cmd == 'screenshot' or save, drop_data=cmd == 'screenshot')
        return reply

    def _picture(self, reply, *, keep, drop_data):
        data = reply.get('data')
        try:
            raw = base64.b64decode(data, validate=True) if isinstance(data, str) and len(data) <= MAX_PICTURE * 4 // 3 + 8 else b''
        except (binascii.Error, ValueError):
            raw = b''
        if not raw or len(raw) > MAX_PICTURE or raw[:3] != b'\xff\xd8\xff':
            self.stderr_tail.append('bad picture')
            return {'ok': False, 'error': 'bad_picture', 'id': reply.get('id')}
        out = dict(reply)
        if keep:
            self.shots += 1
            name = f'shot-{self.shots:03d}.jpg'
            (self.out / name).write_bytes(raw)
            out['file'] = name
        if drop_data:
            out.pop('data', None)
        return out

    def _close_remote(self, obj):
        """Session.close sends the runner's `close` first: the extension shuts the tabs it opened. The link itself stays up for the customer's next task."""
        if self._told:
            return
        self._told = True
        try:
            self.link.send({'cmd': 'close', 'id': 0})
        except Exception:
            pass

    def close(self):
        if self.closed:
            return
        self.closed = True
        self._close_remote(None)
