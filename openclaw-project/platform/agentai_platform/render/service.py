"""The render service (host side, root): turns one file into another format inside a throwaway container.

The app cannot start containers and must not parse assistant-written documents itself, so it hands the bytes to this service over a private unix socket.
Each job gets its own container from the renderer image (deploy/renderer/Dockerfile): no network, read-only root, no capabilities, bounded memory, CPU,
processes and time. The engine inside (engine.py) reads /job/in and writes /job/out; this side trusts nothing it writes back beyond size and type of file.

Nothing is kept: the job folder is removed when the job ends, whatever happened, and nothing about the content is logged.

Wire format (both directions): one JSON line, then the raw bytes it announces, in order.
    request   {"op": "convert", "source": "report.md", "target": "pdf" | null, "preview": true, "files": [{"path": "report.md", "size": 1234}, ...]}
    reply     {"ok": true, "size": N, "preview_size": M, "pages": 3}      or      {"ok": false, "error": "short reason"}
A null target asks only for the preview picture of the source.
"""
from __future__ import annotations
import json
import os
import shutil
import socketserver
import stat
import struct
import socket
import subprocess
import threading
import uuid
from pathlib import Path

from ..lifecycle.workspace import safe_path
from .engine import TARGETS

MAX_HEADER = 64 * 1024
MAX_INPUT_BYTES = 60 * 1024 * 1024
MAX_OUTPUT_BYTES = 100 * 1024 * 1024
MAX_PREVIEW_BYTES = 2_000_000
MAX_FILES = 25
JOB_SECONDS = 150
CONTAINER_UID = 10001


class RenderError(Exception):
    """A refusal or failure with a short reason that is safe to pass on (never a path, never tool output)."""


def job_argv(job_id: str, folder: Path, image: str, *, uid: int = CONTAINER_UID):
    """The fixed, hardened command for one conversion. Nothing customer-supplied reaches it: the id is hex and the paths are host-made."""
    if not isinstance(job_id, str) or len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
        raise ValueError('invalid job id')
    return ['docker', 'run', '--rm', '-i', '--name', f'lumina-render-{job_id[:12]}', '--network', 'none', '--read-only',
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=768m', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '256',
            '--memory', '1536m', '--memory-swap', '1536m', '--cpus', '1', '--user', f'{uid}:{uid}',
            '-v', f'{folder}/request.json:/job/request.json:ro', '-v', f'{folder}/in:/job/in:ro', '-v', f'{folder}/out:/job/out:rw',
            '-e', 'HOME=/tmp/home', image]


def _read_regular(folder: Path, name: str, limit: int) -> bytes:
    """A file the container wrote: opened without following a link, and only if it is an ordinary file within the bound."""
    fd = os.open(str(folder / name), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
            raise RenderError('The converted file is empty or too large')
        chunks, left = [], info.st_size
        while left > 0:
            chunk = os.read(fd, min(left, 1 << 20))
            if not chunk:
                break
            chunks.append(chunk)
            left -= len(chunk)
        return b''.join(chunks)
    finally:
        os.close(fd)


class RenderService:
    def __init__(self, root, *, image, run=subprocess.run, env=None, uid=CONTAINER_UID, slots=2, own=os.chown):
        """root: a private folder for job folders. run: subprocess.run-compatible. own(path, uid, gid): gives the container its folders (root only; tests pass a no-op)."""
        self.root, self.image, self.run, self.env, self.uid, self.own = Path(root), image, run, env, uid, own
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._slots = threading.BoundedSemaphore(slots)

    def sweep(self):
        """Remove job folders left by a crash. Called once at start: no job survives a restart."""
        for entry in self.root.iterdir():
            shutil.rmtree(entry, ignore_errors=True)

    def convert(self, source, target, files, *, preview=True):
        """files: {relative path: bytes}. -> {'data': bytes | None, 'preview': bytes | None, 'pages': int | None}."""
        if target is not None and target not in TARGETS:
            raise RenderError('That format is not one the converter writes')
        if not isinstance(files, dict) or not 0 < len(files) <= MAX_FILES or source not in files:
            raise RenderError('invalid request')
        if any(safe_path(path) is None or not isinstance(data, bytes) or not data for path, data in files.items()):
            raise RenderError('invalid request')
        if sum(len(data) for data in files.values()) > MAX_INPUT_BYTES:
            raise RenderError('The files are too large to convert')
        if not self._slots.acquire(timeout=60):
            raise RenderError('The converter is busy; try again in a moment')
        job_id = uuid.uuid4().hex
        folder = self.root / job_id
        try:
            (folder / 'in').mkdir(parents=True, mode=0o755)
            (folder / 'out').mkdir(mode=0o700)
            os.chmod(folder, 0o711)                        # the container user must reach in/ and out/ and nothing else
            for path, data in files.items():
                where = folder / 'in' / path
                where.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                with open(where, 'xb') as handle:
                    handle.write(data)
                os.chmod(where, 0o644)
            (folder / 'request.json').write_text(json.dumps({'source': source, 'target': target, 'preview': bool(preview)}))
            os.chmod(folder / 'request.json', 0o644)
            self.own(folder / 'out', self.uid, self.uid)
            argv = job_argv(job_id, folder, self.image, uid=self.uid)
            try:
                self.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=JOB_SECONDS, env=self.env)
            except subprocess.TimeoutExpired:
                try:
                    self.run(['docker', 'kill', f'lumina-render-{job_id[:12]}'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20, env=self.env)
                except (OSError, subprocess.SubprocessError):
                    pass
                raise RenderError('The conversion took too long')
            except OSError:
                raise RenderError('The converter is not available')
            try:
                result = json.loads(_read_regular(folder / 'out', 'result.json', 4096))
            except (OSError, ValueError, RenderError):
                raise RenderError('The conversion failed')
            if not isinstance(result, dict) or result.get('ok') is not True:
                reason = result.get('error') if isinstance(result, dict) else None
                raise RenderError(reason[:160] if isinstance(reason, str) and reason.isprintable() else 'The conversion failed')
            out = {'data': None, 'preview': None, 'pages': result.get('pages') if type(result.get('pages')) is int and 0 < result['pages'] < 100000 else None}
            if target is not None:
                try:
                    out['data'] = _read_regular(folder / 'out', 'result.' + target, MAX_OUTPUT_BYTES)
                except OSError:
                    raise RenderError('The conversion failed')
            if result.get('preview') == 'preview.jpg':
                try:
                    shot = _read_regular(folder / 'out', 'preview.jpg', MAX_PREVIEW_BYTES)
                    out['preview'] = shot if shot.startswith(b'\xff\xd8\xff') else None
                except (OSError, RenderError):
                    pass
            return out
        finally:
            shutil.rmtree(folder, ignore_errors=True)
            self._slots.release()


# ---------------------------------------------------------------------- unix socket server
def linux_peer_uid(sock):
    return struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))[1]


def read_exact(stream, size):
    data = stream.read(size)
    if data is None or len(data) != size:
        raise RenderError('invalid request')
    return data


def serve(service, path, *, allowed_uids, group_gid=None, peer_uid=linux_peer_uid):
    class Handler(socketserver.StreamRequestHandler):
        timeout = JOB_SECONDS + 120

        def handle(self):
            if peer_uid(self.request) not in allowed_uids:
                return
            payload = b''
            try:
                line = self.rfile.readline(MAX_HEADER + 1)
                if len(line) > MAX_HEADER:
                    raise RenderError('invalid request')
                request = json.loads(line)
                listed = request.get('files') if isinstance(request, dict) else None
                if not isinstance(request, dict) or request.get('op') != 'convert' or not isinstance(listed, list) or not 0 < len(listed) <= MAX_FILES:
                    raise RenderError('invalid request')
                files, total = {}, 0
                for item in listed:
                    size = item.get('size') if isinstance(item, dict) else None
                    if not isinstance(item.get('path'), str) or type(size) is not int or size <= 0 or item['path'] in files:
                        raise RenderError('invalid request')
                    total += size
                    if total > MAX_INPUT_BYTES:
                        raise RenderError('The files are too large to convert')
                    files[item['path']] = read_exact(self.rfile, size)
                target = request.get('target')
                if target is not None and not isinstance(target, str):
                    raise RenderError('invalid request')
                out = service.convert(request.get('source'), target, files, preview=request.get('preview') is not False)
                data, shot = out['data'] or b'', out['preview'] or b''
                reply = {'ok': True, 'size': len(data), 'preview_size': len(shot), 'pages': out['pages']}
                payload = data + shot
            except RenderError as exc:
                reply = {'ok': False, 'error': str(exc)}
            except Exception:
                reply = {'ok': False, 'error': 'The conversion failed'}
            try:
                self.wfile.write((json.dumps(reply) + '\n').encode() + payload)
            except OSError:
                pass

    class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

    if os.path.exists(path):
        os.unlink(path)
    server = Server(path, Handler)
    os.chmod(path, 0o660)
    if group_gid is not None:
        os.chown(path, 0, group_gid)
    return server
