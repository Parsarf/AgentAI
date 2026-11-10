"""Opt-in structured timing marks for one request's lifecycle. Observation only: it changes no scheduling, concurrency, streaming or safety gate.

Off unless AGENTAI_TIMING=1. One JSON line per mark on the `agentai.timing` logger (journald picks it up from the worker / app service). Every line carries:
  rid       the request id (the correlation id across the app, the worker and the driver; the same id keys customer_requests, events, audit_events and chat_deliveries)
  stage     a fixed name from the list in docs (send_received, claim, rpc, send_ack, wait_return, mirror, finish_done ...)
  wall_ms   time.time() in ms: comparable across processes ON THE SAME HOST only (the app, the worker and the SQLite timestamps share one clock)
  mono_ms   time.monotonic() in ms: use only for differences inside one process (pid) - never across processes or restarts
Only ints, floats, bools and short identifier-like strings are accepted as fields: message text, reply text, tokens and secrets can never be logged through here.
"""
from __future__ import annotations
import json
import logging
import os
import re
import time

_log = logging.getLogger('agentai.timing')
_SAFE = re.compile(r'^[A-Za-z0-9_.:\-]{0,64}$')


_current = {'rid': '-'}


def bind(rid):
    """The worker runs one request at a time: layers below the driver (the bridge client) mark against this id."""
    _current['rid'] = str(rid)[:64] if rid else '-'


def enabled() -> bool:
    return os.environ.get('AGENTAI_TIMING') == '1'


def _logger():
    if not _log.handlers:       # Django/worker leave INFO unconfigured: give this logger its own stderr handler (journald) so marks are not dropped
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('%(message)s'))
        _log.addHandler(handler)
        _log.setLevel(logging.INFO)
        _log.propagate = False
    return _log


def mark(rid, stage, **fields):
    """Record one boundary. Never raises, never blocks on anything but a log write."""
    try:
        if not enabled():
            return
        rid = rid or _current['rid']
        row = {'rid': str(rid)[:64], 'stage': stage, 'wall_ms': round(time.time() * 1000, 1), 'mono_ms': round(time.monotonic() * 1000, 1), 'pid': os.getpid()}
        for key, value in fields.items():
            if isinstance(value, bool) or isinstance(value, (int, float)):
                row[key] = value
            elif isinstance(value, str) and _SAFE.match(value):
                row[key] = value
        _logger().info(json.dumps(row, sort_keys=True))
    except Exception:
        return
