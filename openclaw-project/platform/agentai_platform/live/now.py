"""Who is deciding right now, as a tiny file next to the live frames (`now.json`), so the live view can show it at the same rate as the picture.

Written by the browse service (root), read by the frame gateway. It holds only whitelisted codes, never page text or free text: the gateway sends them as
response headers and the screen turns the codes into words, so nothing a website says can reach the customer's screen through this channel.
"""
from __future__ import annotations
import json
import os
from pathlib import Path

FILE = 'now.json'
BY = ('jev', 'claude')
MODE = ('controls', 'picture')
NOTE = ('', 'took', 'back', 'help', 'picture')     # took: Claude took the page; back: JEV is back; help: Claude helped with one step; picture: JEV is looking at a picture
MAX_BYTES = 300


def write(out_dir, seq: int, by: str, mode: str, note: str = '') -> bool:
    """Replace now.json atomically. A value outside the whitelist is refused (nothing is written)."""
    if by not in BY or mode not in MODE or note not in NOTE or isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
        return False
    out = Path(out_dir)
    tmp = out / (FILE + '.tmp')
    try:
        tmp.write_text(json.dumps({'seq': seq, 'by': by, 'mode': mode, 'note': note}, separators=(',', ':')), encoding='utf-8')
        os.chmod(tmp, 0o644)
        os.replace(tmp, out / FILE)
        return True
    except OSError:
        return False


def read(out_dir) -> dict | None:
    """-> {'seq', 'by', 'mode', 'note'} or None when there is none, or it is not exactly what write() makes."""
    try:
        with open(Path(out_dir) / FILE, 'rb') as fh:
            raw = fh.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return None
        data = json.loads(raw)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or set(data) != {'seq', 'by', 'mode', 'note'}:
        return None
    seq = data['seq']
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1 or data['by'] not in BY or data['mode'] not in MODE or data['note'] not in NOTE:
        return None
    return data
