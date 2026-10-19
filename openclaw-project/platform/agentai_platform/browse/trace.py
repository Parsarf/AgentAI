"""The operator's record of one browser run: one JSON line per thing that happened, with timings, so a failure can be read back step by step.

Written next to the run's screenshots (root-only, deleted with them after a day) and never sent to the customer or the model.
It holds facts, not content: page host and path (no query string), counts, timings, error types and short redacted error text, the tier that decided and
the probabilities JEV gave. It never holds page text, typed values, the user's request, or any key. A trace that cannot be written never fails the run."""
from __future__ import annotations
import json
import logging
from pathlib import Path
import threading
import time

from agentai_platform.privacy import scrub

log = logging.getLogger('agentai.browse.trace')
MAX_BYTES = 2_000_000          # about 5,000 events; past this only the run's end is still recorded
TEXT_LIMIT = 300


def _clean(value):
    if isinstance(value, str):
        return scrub(value, TEXT_LIMIT)
    if isinstance(value, dict):
        return {str(k)[:40]: _clean(v) for k, v in list(value.items())[:30]}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in list(value)[:30]]
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return round(value, 4) if value == value and abs(value) != float('inf') else None
    return scrub(repr(value), TEXT_LIMIT)


class Trace:
    def __init__(self, path=None, clock=time.monotonic, wall=time.time):
        self.path = Path(path) if path else None
        self.clock, self.wall, self.t0 = clock, wall, clock()
        self.step = 0                      # the loop sets this, so events from the ladder and the runner client carry the step they belong to
        self._lock, self._size, self._dropped = threading.Lock(), 0, 0

    def emit(self, kind, **fields):
        if self.path is None:
            return
        try:
            row = {'t': round(self.clock() - self.t0, 3), 'at': round(self.wall(), 3), 'step': self.step, 'kind': kind, **_clean(fields)}
            line = json.dumps(row, separators=(',', ':'), default=str) + '\n'
            with self._lock:
                if self._size + len(line) > MAX_BYTES and kind != 'end':
                    self._dropped += 1
                    return
                if self._dropped and kind == 'end':
                    line = json.dumps({**row, 'dropped_events': self._dropped}, separators=(',', ':'), default=str) + '\n'
                with open(self.path, 'a', encoding='utf-8') as fh:
                    fh.write(line)
                self._size += len(line)
        except Exception as exc:              # logging must never be the reason a customer's task fails
            log.warning('browse trace not written: %s', type(exc).__name__)


NULL = Trace(None)


def read(path):
    rows = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


# Outcomes that mean "something did not go the way it should", for the viewer's summary.
PROBLEMS = {'error', 'low_confidence', 'bad_target', 'invalid', 'timeout', 'no_json', 'rejected', 'failed'}


def first_problem(rows):
    for row in rows:
        if row.get('kind') in ('crash', 'tier_error', 'runner_error') or row.get('outcome') in PROBLEMS or (row.get('kind') == 'runner' and row.get('ok') is False):
            return row
    return None


def render(rows, *, only_problems=False):
    out = []
    for row in rows:
        problem = row is first_problem([row]) or row.get('kind') in ('crash', 'tier_error', 'runner_error')
        if only_problems and not (problem or row.get('kind') in ('start', 'end')):
            continue
        rest = {k: v for k, v in row.items() if k not in ('t', 'at', 'step', 'kind')}
        detail = ' '.join(f'{k}={json.dumps(v, separators=(",", ":")) if isinstance(v, (dict, list)) else v}' for k, v in rest.items())
        out.append(f'{"!" if problem else " "} +{row.get("t", 0):7.2f}s  step {row.get("step", 0):>2}  {row.get("kind", ""):<12} {detail}')
    bad = first_problem(rows)
    if bad is not None:
        out.append(f'\nfirst problem: +{bad.get("t", 0):.2f}s, step {bad.get("step", 0)}, {bad.get("kind")}: ' + ' '.join(f'{k}={v}' for k, v in bad.items() if k not in ('t', 'at', 'step', 'kind')))
    return '\n'.join(out)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Read the trace of a browser run.')
    parser.add_argument('run', help='a request id, or the path to a trace.jsonl')
    parser.add_argument('--jobs', default='/var/lib/agentai-browse/jobs')
    parser.add_argument('--problems', action='store_true', help='show only the start, the end and what went wrong')
    args = parser.parse_args(argv)
    path = Path(args.run) if args.run.endswith('.jsonl') else Path(args.jobs) / args.run / 'trace.jsonl'
    if not path.exists():
        raise SystemExit(f'no trace at {path} (traces are deleted a day after the task)')
    print(render(read(path), only_problems=args.problems))


if __name__ == '__main__':
    main()
