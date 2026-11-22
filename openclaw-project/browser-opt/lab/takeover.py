"""Take-over, live: the customer does their part in the same browser and the task carries on. Real service, real Chrome, live JEV, the Sonnet stand-in for the assistant.

  1. A sign-in page: the task waits for the customer; "the customer" signs in through the same control calls the Live view sends (click, type, key); the service notices the
     page is no longer a sign-in page and carries on by itself; the task ends with what the signed-in page says. The password is typed by the customer's control call, never by a model.
  2. The customer takes the wheel in the middle of an ordinary task (pause), scrolls, and gives it back (resume); the task finishes.

    python3 browser-opt/lab/takeover.py --out <dir> --jev-key-js <file>
"""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lab import ACCOUNT, ASSISTANT_SYSTEM, Lab, Meter, adapter, ask_model, load_key, parse_step       # noqa: E402
from agentai_platform.browse.service import BrowseService       # noqa: E402


def drive(service, job, args, meter, on_paused=None, on_running=None, seconds=240):
    """Follow a job to its end, answering for the assistant; `on_paused(polled)` is the customer at the wheel, `on_running(polled)` may ask for it."""
    since, transcript, log, end = 0, [], [], time.monotonic() + seconds
    while time.monotonic() < end:
        p = service.poll(ACCOUNT, job, since)
        for e in p['events']:
            since = max(since, e['n'])
            if e['kind'] in ('status', 'control'):
                log.append((e['kind'], e.get('state') or e.get('action'), (e.get('reason') or '')[:70]))
        if p['state'] in adapter.FINALS:
            return p, log
        if p['state'] == 'paused' and on_paused:
            on_paused(p)
        elif p['state'] == 'running' and on_running:
            on_running(p)
        if p.get('observation') and p['state'] == 'running':
            transcript.append(adapter.asking_text(p['observation']))
            prompt = ('Your tool call was lumina_browser with these arguments:\n' + json.dumps(args) + '\n\n' + '\n\n'.join(f'--- tool result {i} ---\n{t}' for i, t in enumerate(transcript, 1))
                      + '\n\nSend the next lumina_browser_step arguments now.')
            step = parse_step(ask_model(ASSISTANT_SYSTEM, prompt, meter)) or {'action': 'stop', 'reason': 'no step'}
            transcript.append('(you answered) ' + json.dumps(step))
            try:
                service.agent_step(ACCOUNT, job, adapter.clean_step(step))
            except Exception:
                pass
        time.sleep(0.25)
    service.cancel(ACCOUNT, job)
    return service.poll(ACCOUNT, job, 0), log


def start(lab, service, args):
    job = uuid.uuid4().hex
    task = adapter.clean_task(args)
    service.start(ACCOUNT, job, adapter.build_goal(task), start_url=task['start_url'], max_steps=20, max_seconds=300)
    return job


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--jev-key-js', default='')
    opts = parser.parse_args()
    lab = Lab(opts.out, load_key(opts))
    root = Path(opts.out) / 'jobs'
    root.mkdir(parents=True, exist_ok=True)
    meter, results = Meter(), []

    # 1. sign-in: the customer signs in, the task carries on by itself
    service = BrowseService(spawn=lab.spawn, jev_for=lab.jev_for, root=root, takeover_seconds=120)
    args = {'task': 'Open the secure area of this site and report the message the page shows after signing in.', 'site': 'https://the-internet.herokuapp.com/login',
            'done_when': 'The message shown in the secure area is reported.'}
    job = start(lab, service, args)
    did = []

    def customer_signs_in(p):
        if did:
            return
        did.append(p.get('needs_you'))
        j = service.jobs[job]
        with j.lock:
            snap = j.session.snapshot()                        # only to find where the two fields are on screen, as a person would by looking
        user = next(e for e in snap['elements'] if e['label'].lower().startswith('username'))
        password = next(e for e in snap['elements'] if e['type'] == 'password')
        for call in (('click', {'x': user['x'], 'y': user['y']}), ('type', {'text': 'tomsmith'}), ('click', {'x': password['x'], 'y': password['y']}),
                     ('type', {'text': 'SuperSecretPassword!'}), ('key', {'text': 'Enter'})):       # the demo site's own published test login
            did.append((call[0], service.control(ACCOUNT, job, call[0], **call[1])['ok']))
    final, log = drive(service, job, args, meter, on_paused=customer_signs_in)
    results.append({'case': 'sign-in take-over', 'state': final['state'], 'answer': final.get('answer'), 'url': final.get('url'), 'asked_for': did[:1], 'controls': did[1:], 'log': log,
                    'passed': final['state'] == 'done' and 'secure' in (final.get('url') or '') and all(ok for _a, ok in did[1:]) and any('Lumina continues' in r for _k, _s, r in log)})

    # 2. the customer takes the wheel mid-task and gives it back
    service = BrowseService(spawn=lab.spawn, jev_for=lab.jev_for, root=root, takeover_seconds=120)
    args = {'task': 'Go to the second page of quotes and report the author of the first quote on that page.', 'site': 'https://quotes.toscrape.com/',
            'done_when': 'The author of the first quote on page 2 is reported.'}
    job = start(lab, service, args)
    wheel = []

    def ask_for_wheel(p):
        if not wheel:
            wheel.append('asked'); service.pause(ACCOUNT, job)

    def customer_scrolls(p):
        if 'scrolled' not in wheel:
            wheel.append('scrolled')
            wheel.append(('scroll', service.control(ACCOUNT, job, 'scroll', text='down')['ok']))
            reply = service.control(ACCOUNT, job, 'goto', text='http://127.0.0.1:1/')      # the address bar keeps the browser's own address rules during a take-over
            wheel.append(('private address', 'refused' if not reply['ok'] and reply.get('error') == 'url_blocked' else f'NOT refused: {reply}'))
            service.resume(ACCOUNT, job)
    final, log = drive(service, job, args, meter, on_paused=customer_scrolls, on_running=ask_for_wheel)
    results.append({'case': 'pause and give back', 'state': final['state'], 'answer': final.get('answer'), 'wheel': wheel, 'log': log,
                    'passed': final['state'] == 'done' and 'Marilyn Monroe' in (final.get('answer') or '') and ('scroll', True) in wheel and ('private address', 'refused') in wheel and any(s == 'paused' for _k, s, _r in log)})
    for r in results:
        print(('PASS ' if r['passed'] else 'FAIL ') + r['case'], '|', r['state'], '|', (r.get('answer') or '')[:120])
        print('     ', {k: v for k, v in r.items() if k in ('asked_for', 'controls', 'wheel')})
        print('     ', r['log'])
    (Path(opts.out) / 'takeover.json').write_text(json.dumps(results, indent=1))


if __name__ == '__main__':
    main()
