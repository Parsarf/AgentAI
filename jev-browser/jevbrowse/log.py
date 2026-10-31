"""One log file per run, in jev-browser/logs/: every event as a JSON line, with timings. It is the full story of a run: what JEV was sent and answered,
what the browser was told to do and said back, and every failure. It stays on this computer (logs/ is git-ignored) and holds page text and what was typed,
so do not share it without looking at it first.

Read one:   .venv/bin/python -m jevbrowse.log            (the latest run)
            .venv/bin/python -m jevbrowse.log logs/<file>.jsonl [--problems]
"""
import json
import sys
import threading
import time
from pathlib import Path

LOGS = Path(__file__).resolve().parent.parent / 'logs'


class NullLog:
    path, step, shots_dir = None, 0, None

    def emit(self, kind, **fields):
        pass


NULL = NullLog()


class RunLog:
    def __init__(self, folder=LOGS):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime('%Y%m%d-%H%M%S')
        self.path = folder / f'{stamp}.jsonl'
        n = 1
        while self.path.exists():
            n += 1
            self.path = folder / f'{stamp}-{n}.jsonl'
        self.path.touch()                                          # exists from the first moment, so a dashboard can follow the run before its first event
        self.shots_dir = self.path.parent / self.path.stem        # logs/<run>/step-001.jpg ... one picture per page JEV was shown
        self.t0, self.step, self._lock = time.monotonic(), 0, threading.Lock()
        latest = folder / 'latest.jsonl'
        try:
            latest.unlink(missing_ok=True)
            latest.symlink_to(self.path.name)
        except OSError:
            pass

    def emit(self, kind, **fields):
        row = {'t': round(time.monotonic() - self.t0, 3), 'step': self.step, 'kind': kind, **fields}
        try:
            with self._lock, open(self.path, 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
        except OSError:
            pass                                    # a log that cannot be written never stops the run


# ---------------------------------------------------------------- reading a log
def read(path):
    rows = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _problem(r):
    k = r['kind']
    return (k in ('crash', 'jev_error', 'runner_stderr', 'runner_error', 'safety_stop') or (k == 'runner_event' and ('CLOSED' in r['text'] or 'CRASHED' in r['text'] or 'DISCONNECTED' in r['text'])) or (k == 'runner' and not r.get('ok'))
            or (k == 'act' and (not r.get('ok') or r.get('changed') is False)) or (k == 'decision' and r.get('action') is None)
            or (k == 'end' and r.get('status') not in ('done',)))


def _spot(box):
    return f'{box["left"]:.2f}-{box["right"]:.2f} x {box["top"]:.2f}-{box["bottom"]:.2f} (sure {box["confidence"]:.0%})'


def line(r):
    k, t, s = r['kind'], r['t'], r['step']
    head = f'{t:8.2f}s  step {s:>2}  '
    if k == 'run_start':
        return f'{head}RUN      goal={r["goal"]!r}  start={r["url"]}  may type={r["texts"]}  max steps={r["steps"]}'
    if k == 'page':
        labels = ', '.join(f'{c["ref"]}:{c["label"]}' for c in r['controls'][:14])
        return f'{head}PAGE     {r["url"]}  "{r["title"]}"  {len(r["controls"])} controls, {r["text_chars"]} chars of text  [{r.get("mode", "controls")} mode{": " + r["why"] if r.get("why") else ""}]\n{" " * 22}controls: {labels}{" ..." if len(r["controls"]) > 14 else ""}'
    if k == 'jev_call':
        return f'{head}JEV      sent {len(r["questions"])} questions in {r["ms"]} ms' + ('' if not r.get('error') else f'  ERROR {r["error"]}')
    if k == 'jev_answer':
        more = f'  found={r["found"]:.0%} spot={_spot(r.get("target"))}' if r.get('target') else ''
        return f'{head}JEV SAID {", ".join(f"{n}={c} ({p:.0%})" for n, (c, p) in r["answers"].items())}{more}'
    if k == 'jev_error':
        return f'{head}JEV ERR  {r["error"]}'
    if k == 'decision':
        if r.get('action') is None:
            return f'{head}DECIDE   nothing to do: {r["note"]}'
        extra = (f' value={r["value"]!r}' if r.get('value') else '') + (f' at {r["x"]},{r["y"]}' if r.get('x') is not None else '')
        return f'{head}DECIDE   {r["action"]} {r.get("label") or ""!r}{extra}'
    if k == 'runner':
        return f'{head}BROWSER  {r["cmd"]} {r.get("action") or r.get("url") or ""} -> {"ok" if r["ok"] else "FAILED " + str(r.get("error"))} ({r["ms"]} ms)'
    if k == 'act':
        verdict = ('page changed' if r['changed'] else 'page did NOT change') if r['ok'] else f'FAILED: {r.get("error")}'
        return f'{head}ACT      {r["action"]} {r.get("label") or ""!r} -> {verdict}   now at {r.get("url")}'
    if k == 'safety_stop':
        return f'{head}STOP     {r["why"]}'
    if k == 'runner_event':
        return f'{head}TAB      {r["text"]}'
    if k == 'runner_stderr':
        return f'{head}BROWSER SAID  {r["text"]}'
    if k == 'crash':
        return f'{head}CRASH    {r["error"]}\n{r.get("traceback", "")}'
    if k == 'end':
        return f'{head}END      {r["status"]}: {r["detail"]}'
    return f'{head}{k}'


def show(path, only_problems=False, out=print):
    rows = read(path)
    for r in rows:
        if only_problems and not (_problem(r) or r['kind'] in ('run_start', 'end')):
            continue
        out(('! ' if _problem(r) else '  ') + line(r))
    acts = [r for r in rows if r['kind'] == 'act']
    out('\nsummary: {} steps, {} JEV calls ({} errors), {} actions ({} failed, {} left the page unchanged), {} browser errors; ended {}'.format(
        len({r['step'] for r in rows if r['kind'] == 'page'}), sum(r['kind'] == 'jev_call' for r in rows), sum(r['kind'] == 'jev_error' for r in rows), len(acts),
        sum(not r['ok'] for r in acts), sum(r['ok'] and r['changed'] is False for r in acts), sum(r['kind'] in ('runner_stderr', 'runner_error') for r in rows),
        next((r['status'] for r in reversed(rows) if r['kind'] == 'end'), 'without an end (crashed or killed)')))


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    show(args[0] if args else LOGS / 'latest.jsonl', only_problems='--problems' in sys.argv)
