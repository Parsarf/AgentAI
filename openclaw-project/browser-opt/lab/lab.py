"""Local browsing lab: the real browse service, the real runner in a real Chrome, the live JEV model, and a Sonnet stand-in for the customer's assistant.

Nothing here is deployed and nothing here touches the server. It exists to reproduce browsing failures, compare changes on the same tasks and measure speed, cost and
completion together.

    python3 browser-opt/lab/lab.py run --tasks browser-opt/lab/tasks.json --out <dir> [--only id,id] [--parallel 3] [--no-jev] [--repeat 1]
    python3 browser-opt/lab/lab.py report <dir> [<dir> ...]

What is real: BrowseService, BrowseRunner, Ladder, JevChooser, candidates, modes, Session, browse/runner.mjs, Chrome, TypeSafe's JEV, the task wording (adapter.build_goal).
What is a stand-in: the assistant. In production it is the customer's OpenClaw assistant answering `lumina_browser_step`; here it is the same model family called through
the `claude` command with the same tool description and the same observation text (adapter.asking_text), keeping the conversation so far as the runtime would.
The customer is a stand-in too: a question is answered from the task's `customer` entry, or the job is stopped and the question recorded.

Keys: TYPESAFE_API_KEY from the environment, or --jev-key-js pointing at a JS file that holds it in a quoted string (read in this process only; never printed or stored).
"""
from __future__ import annotations
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import uuid

HERE = Path(__file__).resolve().parent
PROJECT = Path(os.environ.get('LAB_PROJECT') or HERE.parent.parent)      # LAB_PROJECT: another checkout of openclaw-project to measure (the code before a change), with this lab
sys.path.insert(0, str(PROJECT / 'platform'))

from agentai_platform.browse import adapter  # noqa: E402
from agentai_platform.browse.ladder import JevChooser  # noqa: E402
from agentai_platform.browse.service import BrowseService  # noqa: E402
from agentai_platform.browse.session import ProcessTransport  # noqa: E402
from agentai_platform.browse import trace as trace_mod  # noqa: E402
from agentai_platform.routing.classifier import http_post  # noqa: E402

JEV_ENDPOINT = 'https://api.typesafe.ai/v1/systemone'
JEV_MODEL = 'jev-1.14.0'
CHROME = os.environ.get('BROWSE_CHROME') or '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
ASSISTANT_MODEL = os.environ.get('LAB_ASSISTANT_MODEL', 'claude-sonnet-5-5')
ACCOUNT = 'lab'

ASSISTANT_SYSTEM = (
    "You are a customer's assistant. You called the tool lumina_browser to do a task on a website, and it handed the page back to you because it needs your next step. "
    'You answer by calling the tool lumina_browser_step. Tool description:\n' + adapter.STEP['description'] + '\n\nInput schema:\n' + json.dumps(adapter.STEP['inputSchema']) +
    '\n\nReply with ONLY the JSON object of the arguments for lumina_browser_step (no prose, no code fence).')


def load_key(args):
    key = os.environ.get('TYPESAFE_API_KEY', '').strip()
    if not key and args.jev_key_js:
        found = re.search(r'["\']([A-Za-z0-9_\-.]{20,})["\']', Path(args.jev_key_js).read_text())
        key = found.group(1) if found else ''
    return key


class Meter:
    """Counts what the stand-in assistant cost: calls, tokens, dollars as the CLI reports them, and seconds."""
    def __init__(self):
        self.calls, self.input, self.cached, self.output, self.usd, self.seconds = 0, 0, 0, 0, 0.0, 0.0


def ask_model(system, prompt, meter, model=ASSISTANT_MODEL, timeout=120):
    started = time.monotonic()
    proc = subprocess.run(['claude', '-p', '--model', model, '--output-format', 'json', '--system-prompt', system, '--tools', '', '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
                           '--setting-sources', '', '--disable-slash-commands'], input=prompt, capture_output=True, text=True, timeout=timeout, cwd='/tmp')
    meter.seconds += time.monotonic() - started
    meter.calls += 1
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return ''
    usage = data.get('usage') or {}
    meter.input += int(usage.get('input_tokens') or 0) + int(usage.get('cache_creation_input_tokens') or 0)
    meter.cached += int(usage.get('cache_read_input_tokens') or 0)
    meter.output += int(usage.get('output_tokens') or 0)
    meter.usd += float(data.get('total_cost_usd') or 0)
    return str(data.get('result') or '')


def parse_step(text):
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```[a-z]*\n?|\n?```$', '', text).strip()
    try:
        return json.loads(text)
    except ValueError:
        found = re.search(r'\{.*\}', text, re.S)
        if found:
            try:
                return json.loads(found.group(0))
            except ValueError:
                pass
    return None


class Lab:
    def __init__(self, out, jev_key, *, use_jev=True, headless=True, runner=None, service_kwargs=None):
        self.out, self.jev_key, self.use_jev, self.headless = Path(out), jev_key, use_jev, headless
        self.runner = Path(runner) if runner else PROJECT / 'browse'
        # The lab measures the behaviour with the owner's switch `browser_press_approval` on (its stand-in customer answers the question); pass press_approval to change that.
        self.service_kwargs = {'press_approval': lambda: True, **(service_kwargs or {})}

    def spawn(self, job_id, out_dir):
        env = {**os.environ, 'BROWSE_CHROME': CHROME, 'BROWSE_OUT': str(out_dir)}
        if os.environ.get('LAB_ALLOW_LOOPBACK') == '1':
            env['BROWSE_ALLOW_LOOPBACK'] = '1'
        return ProcessTransport(['node', 'runner.mjs'], env=env, cwd=str(self.runner))

    def jev_for(self, account):
        if not self.use_jev or not self.jev_key:
            return None
        return JevChooser(JEV_ENDPOINT, JEV_MODEL, self.jev_key, http_post)

    def run_task(self, task, repeat=0):
        """One `lumina_browser` call, from the assistant's arguments to the text it would get back. -> a result row."""
        job_id = uuid.uuid4().hex
        root = self.out / 'jobs'
        root.mkdir(parents=True, exist_ok=True)
        service = BrowseService(spawn=self.spawn, jev_for=self.jev_for, root=root, jev_mode='live' if self.use_jev else 'off', **self.service_kwargs)
        meter, transcript, asked, needs = Meter(), [], [], []
        row = {'id': task['id'], 'repeat': repeat, 'job': job_id, 'kind': task.get('kind', ''), 'expect': task.get('expect')}
        started = time.monotonic()
        try:
            cleaned = adapter.clean_task(task['args'])
            goal = adapter.build_goal(cleaned)
            service.start(ACCOUNT, job_id, goal, start_url=cleaned['start_url'], max_cost_microusd=task.get('max_cost_microusd', 500_000),
                          max_steps=task.get('max_steps', 25), max_seconds=task.get('max_seconds', 600))
        except Exception as exc:
            row.update(state='lab_error', reason=f'{type(exc).__name__}: {exc}', seconds=0)
            return row
        since, final, handed = 0, None, 0
        deadline = started + task.get('lab_seconds', 900)
        while time.monotonic() < deadline:
            polled = service.poll(ACCOUNT, job_id, since)
            for event in polled['events']:
                since = max(since, event['n'])
            if polled['state'] in adapter.FINALS:
                final = polled
                break
            if polled['state'] == 'asking' and polled.get('question'):
                q = polled['question']
                asked.append({'title': q['title'], 'options': [o['label'] for o in q['options']], 'kind': q.get('kind')})
                want = (task.get('customer') or {}).get('answer')
                option = next((o for o in q['options'] if want and want.lower() in o['label'].lower()), None)
                if q.get('use') == 'approval':                         # "may Lumina press this button?": the lab's customer says yes unless the task says otherwise
                    option = q['options'][0 if (task.get('customer') or {}).get('approve', True) else 1]
                try:
                    if option is not None:
                        service.answer(ACCOUNT, job_id, q['id'], option=option['id'])
                    else:
                        service.cancel(ACCOUNT, job_id)
                except Exception:
                    pass
            elif polled['state'] == 'paused' and polled.get('needs_you'):
                needs.append(polled['needs_you'])
                service.cancel(ACCOUNT, job_id)                        # the lab has no customer at the wheel: record that one was needed and end the job
            elif polled.get('observation'):
                handed += 1
                shown = adapter.asking_text(polled['observation'])
                transcript.append(shown)
                prompt = ('Your tool call was lumina_browser with these arguments:\n' + json.dumps(task['args'], ensure_ascii=False) + '\n\n'
                          + '\n\n'.join(f'--- tool result {i} ---\n{text}' for i, text in enumerate(transcript, 1)) + '\n\nSend the next lumina_browser_step arguments now.')
                step = parse_step(ask_model(ASSISTANT_SYSTEM, prompt, meter))
                if not isinstance(step, dict):                         # the command itself failed (a timeout, an empty reply): that is the lab's fault, not the browser's, so ask once more
                    step = parse_step(ask_model(ASSISTANT_SYSTEM, prompt, meter))
                transcript.append('(you answered) ' + json.dumps(step))
                for _ in range(2):                                     # a step that cannot be read comes back to the assistant with the reason, as the tool does in production
                    try:
                        service.agent_step(ACCOUNT, job_id, adapter.clean_step(step))
                        break
                    except adapter.BadTask as exc:
                        transcript.append(f'--- tool result ---\nThat step could not be read ({exc}). Send an action and, for click, type or select, the number of a control from the list.')
                        step = parse_step(ask_model(ASSISTANT_SYSTEM, prompt + '\n\n' + '\n\n'.join(transcript[-2:]), meter))
                        transcript.append('(you answered) ' + json.dumps(step))
                    except Exception as exc:
                        transcript.append(f'(refused: {exc})')
                        break
                else:
                    try:
                        service.agent_step(ACCOUNT, job_id, {'action': 'stop', 'reason': 'the stand-in assistant gave no usable step'})
                    except Exception:
                        pass
            time.sleep(0.25)
        if final is None:
            service.cancel(ACCOUNT, job_id)
            time.sleep(1)
            final = service.poll(ACCOUNT, job_id, 0)
            final['state'] = final['state'] if final['state'] in adapter.FINALS else 'lab_timeout'
        seconds = time.monotonic() - started
        everything = service.poll(ACCOUNT, job_id, 0)['events']
        steps = [e for e in everything if e['kind'] == 'step']
        trace_path = root / job_id / 'trace.jsonl'
        rows = trace_mod.read(trace_path) if trace_path.exists() else []
        jev_rows = [r for r in rows if r.get('kind') == 'jev']
        runner_rows = [r for r in rows if r.get('kind') == 'runner']
        answer = final.get('answer') or ''
        expect = task.get('expect')
        passed = None
        if expect:
            passed = final['state'] == expect.get('state', 'done') and all(re.search(p, answer, re.I | re.S) for p in expect.get('answer', [])) and \
                all(re.search(p, final.get('url') or '', re.I) for p in expect.get('url', []))
        if task.get('needs_ok') and needs:
            passed = True                                              # the site put a human check in the way and the customer was asked: a right ending, though not the answer
        if task.get('refusal_ok') and getattr(adapter, 'is_refused', lambda f: False)(final):
            passed = True                                              # the site refuses this browser outright; saying so at once, with what to do instead, is the right ending
        if task.get('expect_needs'):
            passed = bool(needs)                                       # the right ending here is that the customer was asked to do their part
        row.update(state=final['state'], reason=final.get('reason') or '', answer=answer, url=final.get('url') or '', seconds=round(seconds, 1), passed=passed,
                   steps=len(steps), by={who: sum(1 for s in steps if s.get('by') == who) for who in ('jev', 'agent', 'rule')},
                   failed_steps=sum(1 for s in steps if s.get('result') != 'ok'), unchanged_steps=sum(1 for s in steps if s.get('changed') is False),
                   sequence=' '.join(f"{(s.get('by') or '?')[0]}:{s.get('action')}{'' if s.get('result') == 'ok' else '!' + str(s.get('result'))}{'=' if s.get('changed') is False else ''}" for s in steps),
                   jev=dict(final.get('jev') or {}), jev_cost_microusd=final.get('cost_microusd') or 0,
                   jev_ms=sorted(r.get('ms', 0) for r in jev_rows), jev_outcomes=_count(r.get('outcome') for r in jev_rows), jev_modes=_count(r.get('mode') for r in jev_rows),
                   runner_ms=sum(r.get('ms', 0) for r in runner_rows), runner_calls=_count(r.get('cmd') for r in runner_rows),
                   runner_ms_by_cmd={cmd: sum(r.get('ms', 0) for r in runner_rows if r.get('cmd') == cmd) for cmd in {r.get('cmd') for r in runner_rows}},
                   handovers=[r.get('why') for r in rows if r.get('kind') == 'handover'], handed=handed,
                   assistant={'calls': meter.calls, 'input': meter.input, 'cached': meter.cached, 'output': meter.output, 'usd': round(meter.usd, 4), 'seconds': round(meter.seconds, 1),
                              'list_usd': round(list_price(meter.input + meter.cached, meter.output), 4)},
                   asked=asked, needs=needs, text_for_assistant=adapter.findings(final)[:600], trace=str(trace_path))
        (self.out / 'transcripts').mkdir(exist_ok=True)
        (self.out / 'transcripts' / f'{task["id"]}-{repeat}.txt').write_text('\n\n'.join(transcript))
        return row


IN_PER_TOKEN, OUT_PER_TOKEN = 2e-6, 10e-6      # what the `claude` command charged per token in this lab with nothing cached (worked out from its own cost figures)


def list_price(tokens_in, tokens_out):
    """What the assistant's calls cost with no prompt caching at all. The dollars the command reports depend on what happened to be cached (a write costs double, a read a tenth),
    so two runs of the same task differ; this figure does not, and it is the one runs are compared on. Production may cache; then it pays less than this."""
    return tokens_in * IN_PER_TOKEN + tokens_out * OUT_PER_TOKEN


def _count(items):
    out = {}
    for item in items:
        if item is not None:
            out[str(item)] = out.get(str(item), 0) + 1
    return out


def cmd_run(args):
    tasks = json.loads(Path(args.tasks).read_text())
    if args.only:
        wanted = set(args.only.split(','))
        tasks = [t for t in tasks if t['id'] in wanted or t.get('kind') in wanted]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    key = load_key(args)
    if not key and not args.no_jev:
        raise SystemExit('no JEV key (set TYPESAFE_API_KEY, pass --jev-key-js, or use --no-jev)')
    lab = Lab(out, key, use_jev=not args.no_jev, runner=args.runner)
    lock, results = threading.Lock(), []
    jobs = [(t, r) for r in range(args.repeat) for t in tasks]

    def one(job):
        task, repeat = job
        try:
            row = lab.run_task(task, repeat)
        except Exception as exc:
            row = {'id': task['id'], 'repeat': repeat, 'state': 'lab_error', 'reason': f'{type(exc).__name__}: {exc}', 'seconds': 0}
        with lock:
            results.append(row)
            (out / 'results.jsonl').open('a').write(json.dumps(row, ensure_ascii=False) + '\n')
            print(line(row), flush=True)
        return row

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as pool:
        list(pool.map(one, jobs))
    print(summary(results))


def line(r):
    a = r.get('assistant') or {}
    mark = {True: 'PASS', False: 'FAIL', None: '----'}[r.get('passed')]
    return (f"{mark} {r['id']:<26} {r.get('state', ''):<10} {r.get('seconds', 0):>6}s steps {r.get('steps', 0):>2} jev/agent {(r.get('by') or {}).get('jev', 0)}/{(r.get('by') or {}).get('agent', 0)} "
            f"asst {a.get('calls', 0)} calls ${cost_of(r):.3f} jev ${r.get('jev_cost_microusd', 0) / 1e6:.4f} | {(r.get('answer') or r.get('reason') or '')[:110]!r}")


def cost_of(r):
    a = r.get('assistant') or {}
    return a['list_usd'] if 'list_usd' in a else list_price(a.get('input', 0) + a.get('cached', 0), a.get('output', 0))


def summary(rows):
    judged = [r for r in rows if r.get('passed') is not None]
    done = sum(1 for r in rows if r.get('state') == 'done')
    secs = sorted(r.get('seconds', 0) for r in rows)
    usd = sum(cost_of(r) for r in rows) + sum(r.get('jev_cost_microusd', 0) for r in rows) / 1e6
    jev_ms = sorted(ms for r in rows for ms in r.get('jev_ms') or [])
    med = lambda xs: xs[len(xs) // 2] if xs else 0       # noqa: E731
    return (f"\n{len(rows)} runs: {sum(1 for r in judged if r['passed'])}/{len(judged)} judged passed, {done} ended done; median {med(secs)}s, total {sum(secs):.0f}s; "
            f"total cost ${usd:.3f} at list price, nothing cached (assistant ${sum(cost_of(r) for r in rows):.3f} in {sum((r.get('assistant') or {}).get('calls', 0) for r in rows)} calls, JEV ${sum(r.get('jev_cost_microusd', 0) for r in rows) / 1e6:.3f}); steps {sum(r.get('steps', 0) for r in rows)} "
            f"(jev {sum((r.get('by') or {}).get('jev', 0) for r in rows)}, assistant {sum((r.get('by') or {}).get('agent', 0) for r in rows)}); "
            f"JEV median {med(jev_ms)} ms, p90 {jev_ms[int(len(jev_ms) * 0.9)] if jev_ms else 0} ms; states {_count(r.get('state') for r in rows)}")


def cmd_report(args):
    for folder in args.dirs:
        rows = [json.loads(x) for x in (Path(folder) / 'results.jsonl').read_text().splitlines() if x.strip()]
        print(f'== {folder}')
        for r in sorted(rows, key=lambda r: (r['id'], r.get('repeat', 0))):
            print(line(r))
            if args.verbose:
                print(f"       {r.get('sequence', '')[:400]}\n       handovers: {r.get('handovers')} jev: {r.get('jev_outcomes')} modes: {r.get('jev_modes')} asked: {len(r.get('asked') or [])} needs: {r.get('needs')}")
        print(summary(rows))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='cmd', required=True)
    run = sub.add_parser('run')
    run.add_argument('--tasks', default=str(HERE / 'tasks.json'))
    run.add_argument('--out', required=True)
    run.add_argument('--only', default='')
    run.add_argument('--parallel', type=int, default=3)
    run.add_argument('--repeat', type=int, default=1)
    run.add_argument('--no-jev', action='store_true')
    run.add_argument('--runner', default='')
    run.add_argument('--jev-key-js', default='')
    run.set_defaults(func=cmd_run)
    report = sub.add_parser('report')
    report.add_argument('dirs', nargs='+')
    report.add_argument('-v', '--verbose', action='store_true')
    report.set_defaults(func=cmd_report)
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
