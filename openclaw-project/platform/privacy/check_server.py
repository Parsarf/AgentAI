#!/usr/bin/env python3
"""Compares the LIVE server with privacy/facts.json: the things the policy promises that live in server config, not in the repo.

    python3 platform/privacy/check_server.py

Read-only (it runs `bin/ssh-server`, the same door the release scripts use). Run it before and after changing server settings, and whenever the policy's
retention table might have gone out of date. Exit code 1 means a promise in the policy is not true on the server right now.
"""
from __future__ import annotations
import json
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
FACTS = json.loads((HERE / 'facts.json').read_text())

REMOTE = r'''python3 - <<'PY'
import glob, json, os, re, subprocess, time
now = time.time(); out = {}
def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout
conf = sh("grep -h -E '^MaxRetentionSec' /etc/systemd/journald.conf /etc/systemd/journald.conf.d/*.conf 2>/dev/null").strip().splitlines()
out['journald_max_retention'] = conf[-1].split('=', 1)[1].strip() if conf else None
out['timers'] = sorted(set(re.findall(r'(agentai[\w.-]*\.timer)', sh('systemctl list-timers --all --no-legend'))))
snaps = [p for p in glob.glob('/var/lib/agentai-platform/backup-*.sqlite3')]
out['plaintext_snapshots'] = {'count': len(snaps), 'oldest_days': round(max(((now - os.stat(p).st_mtime) / 86400 for p in snaps), default=0), 1)}
sets = glob.glob('/var/backups/agentai/sets/*')
out['encrypted_backups'] = {'count': len(sets), 'oldest_days': round(max(((now - os.stat(p).st_mtime) / 86400 for p in sets), default=0), 1)}
env = ''.join(open(p).read() for p in glob.glob('/etc/agentai-platform/*.env') if os.path.isfile(p))
out['uploads_on'] = bool(re.search(r'^AGENTAI_UPLOADS_ENABLED=1\s*$', env, re.M))
out['telegram_configured'] = bool(re.search(r'^AGENTAI_TELEGRAM_BOT_USERNAME=\S+', env, re.M))
try: sw = json.load(open('/opt/openclaw-production/feature-switches/switches.json')); sw = sw.get('switches', sw)
except Exception: sw = {}
out['connectors_on'] = bool((sw.get('connectors_linking') or {}).get('on'))
try: out['local_browser_off_for_everyone'] = json.load(open('/etc/agentai-supervisor/browse-engine.json')).get('local') is False
except Exception: out['local_browser_off_for_everyone'] = False
try: out['retention_job_scheduled'] = bool(re.search(r'retention_accounts|prune_expired', sh('grep -rl "retention_accounts\|prune_expired" /etc/systemd/system /etc/cron.d 2>/dev/null')))
except Exception: out['retention_job_scheduled'] = False
try:
    out['model_providers'] = sorted(set(re.findall(r'^\s+model:\s*([\w.-]+)/', open('/opt/openclaw-production/config/litellm.yaml').read(), re.M)))
except Exception:
    out['model_providers'] = None
print(json.dumps(out))
PY'''


def collect():
    done = subprocess.run([sys.executable, str(PROJECT / 'bin' / 'ssh-server'), REMOTE], capture_output=True, text=True, timeout=120)
    lines = [l for l in done.stdout.splitlines() if l.startswith('{')]
    if done.returncode or not lines:
        raise SystemExit('could not read the server:\n' + (done.stdout + done.stderr)[-800:])
    return json.loads(lines[-1])


def evaluate(state, facts=FACTS, today=None):
    """-> [(level, message)] with level PASS | WARN | FAIL. Pure: tests feed it sample states."""
    today = today or date.today()
    r, s, results = facts['derived']['retention'], facts['server'], []
    def check(level_if_bad, ok, good, bad):
        results.append(('PASS' if ok else level_if_bad, good if ok else bad))
    journald = {'7day': 7}.get(s['journald_max_retention'])
    check('FAIL', state.get('journald_max_retention') == s['journald_max_retention'], f'server logs are capped at {s["journald_max_retention"]} (the policy says 7 days)',
          f'server logs: journald MaxRetentionSec is {state.get("journald_max_retention")!r}, the policy says {s["journald_max_retention"]!r} (7 days)')
    check('FAIL', s['daily_encrypted_backup_timer'] in state.get('timers', []), 'the daily encrypted backup timer is scheduled', f'{s["daily_encrypted_backup_timer"]} is not scheduled: backups (and their 30-day expiry) are not running')
    enc = state.get('encrypted_backups', {})
    check('FAIL', enc.get('oldest_days', 0) <= r['encrypted_backups_max_days'], f'encrypted backups: {enc.get("count")} sets, oldest {enc.get("oldest_days")} days (limit {r["encrypted_backups_max_days"]})',
          f'an encrypted backup is {enc.get("oldest_days")} days old: the policy says up to {r["encrypted_backups_max_days"]} days')
    snaps = state.get('plaintext_snapshots', {})
    check('FAIL', snaps.get('oldest_days', 0) <= r['plaintext_snapshots_max_days'], f'pre-update database copies: oldest {snaps.get("oldest_days")} days (limit {r["plaintext_snapshots_max_days"]})',
          f'a pre-update database copy is {snaps.get("oldest_days")} days old: the policy says at most {r["plaintext_snapshots_max_days"]} days. Deploy the cleanup fix and let the daily backup run')
    check('WARN', snaps.get('count', 0) <= r['plaintext_snapshots_keep_newest'], f'pre-update database copies: {snaps.get("count")} kept',
          f'{snaps.get("count")} pre-update database copies exist but the cleanup keeps only the newest {r["plaintext_snapshots_keep_newest"]}: the nightly backup removes the extras (the fix was deployed 2026-10-31); if this is still showing after the 03:40 UTC run on 2026-11-01, the cleanup is not working'
          + (f' (the 30-day promise runs out {s["known_gap"].split("until ")[-1].strip(".")})' if 'until ' in s['known_gap'] else ''))
    check('FAIL', state.get('model_providers') == s['model_providers'], f'every model goes to {", ".join(s["model_providers"])} (the policy names it)',
          f'the models now route to {state.get("model_providers")!r} but the policy and record say {s["model_providers"]!r}: a new company would receive chat content, so update the policy first')
    for key, label in (('uploads_on', 'file uploads'), ('telegram_configured', 'Telegram linking'), ('connectors_on', 'Google connectors')):
        check('FAIL', not state.get(key), f'{label} is off, so the policy rightly says nothing about it', f'{label} is ON but the policy does not cover it: update the policy first')
    check('WARN', bool(state.get('retention_job_scheduled')) == bool(r['scheduled_retention_jobs']), 'the retention job schedule matches the record',
          'the retention job (accounts/.../retention_accounts.py) is ' + ('scheduled' if state.get('retention_job_scheduled') else 'not scheduled') + ' on the server but the record says otherwise: the retention table in the policy may need to change')
    return results


def main():
    results = evaluate(collect())
    for level, message in results:
        print(f'{level:5} {message}')
    bad = [m for l, m in results if l == 'FAIL']
    print('\n' + (f'{len(bad)} promise(s) in the policy are not true on the server right now.' if bad else 'Every promise the policy makes about the server holds right now.'))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
