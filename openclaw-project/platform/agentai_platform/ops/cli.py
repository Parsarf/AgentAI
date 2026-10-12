"""Operator entry point: python3 -m agentai_platform.ops.cli <command> [--config PATH]

backup | monitor | watchdog | check | inventory | diagnostics     (run on the host)
fetch | restore-account                                           (owner/drill side; needs the private identity file)
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

from . import diagnostics, hostconfig, inventory, restore, sets
from .backup import SET_ID
from .monitor import Monitor


def main(argv=None):
    p = argparse.ArgumentParser(prog='ops')
    p.add_argument('command', choices=['backup', 'monitor', 'watchdog', 'check', 'inventory', 'diagnostics', 'verify', 'fetch', 'restore-account'])
    p.add_argument('--config', default='/etc/agentai-ops/config.json'); p.add_argument('--set'); p.add_argument('--identity'); p.add_argument('--out')
    p.add_argument('--account'); p.add_argument('--live-db'); p.add_argument('--no-alert', action='store_true')
    a = p.parse_args(argv)
    cfg = hostconfig.load(a.config)
    if a.command == 'inventory':
        for x in inventory.ASSETS: print(f'{x.id:16} owner={x.owner:7} backed_up_by={x.backed_up_by or "-":14} {x.what}')
        return 0
    if a.command == 'check':
        problems = []
        if not cfg['age_recipients']: problems.append('no age recipient configured (generate a key pair on your own computer and add the public key)')
        try: hostconfig.destinations(cfg)
        except Exception as exc: problems.append(f'destination: {type(exc).__name__}')
        if not any(d.get('offsite') for d in cfg['destinations']): problems.append('LAUNCH BLOCKER: no off-server destination configured')
        if not (cfg.get('alerts') or {}).get('email', {}).get('enabled') and not (cfg.get('alerts') or {}).get('telegram', {}).get('enabled'): problems.append('no alert destination enabled')
        print('\n'.join(problems) or 'setup checks passed'); return 1 if any(not x.startswith('LAUNCH') for x in problems) else 0
    if a.command == 'backup':
        report = hostconfig.backup_job(cfg).run(); print(json.dumps({k: report[k] for k in ('set_id', 'complete', 'offsite_copy', 'artifacts')} | {'failures': len(report['failures']), 'warnings': len(report['warnings'])}))
        return 0 if report['complete'] else 1
    if a.command in ('monitor', 'watchdog'):
        mon = Monitor(hostconfig.probe(cfg), cfg['monitor_status'], None if a.no_alert else hostconfig.router(cfg))
        if a.command == 'watchdog':
            ok = mon.watchdog(cfg['monitor_status'], 'monitor', 1800) & mon.watchdog(cfg['backup_status'], 'backup', 2 * 86400); return 0 if ok else 1
        status = mon.run(); print(json.dumps({'overall': status['overall'], 'counts': status['counts'], 'correlation_id': status['correlation_id']})); return 0 if status['overall'] in ('ok', 'unknown') else 1
    if a.command == 'diagnostics':
        print(json.dumps(diagnostics.collect(cfg['app_db'], monitor_status=_json(cfg['monitor_status']), backup_status=_json(cfg['backup_status'])), indent=2)); return 0
    dest = hostconfig.destinations(cfg)[0]
    if a.command == 'verify':
        sid = a.set or sets.newest_complete(dest)
        if not sid: print('no complete set'); return 1
        manifest = sets.load_manifest(dest, sid); bad = []
        for art in manifest['artifacts']:
            if dest.size(f"sets/{sid}/{art['name']}") != art['bytes']: bad.append(art['source'])
        print(json.dumps({'set': sid, 'complete': manifest['complete'], 'artifacts': len(manifest['artifacts']), 'size_mismatch': bad, 'note': 'structure only; decrypt checks need the private key'})); return 1 if bad else 0
    if not a.identity: print('--identity is required'); return 2
    out = Path(a.out or tempfile.mkdtemp(prefix='restore-'))
    if a.command == 'fetch':
        manifest, got = sets.fetch(dest, a.set or sets.newest_complete(dest), a.identity, out); print(json.dumps({'set': manifest['set_id'], 'files': {k: str(v) for k, v in got.items()}})); return 0
    if a.command == 'restore-account':
        manifest, got = sets.fetch(dest, a.set or sets.newest_complete(dest), a.identity, out, only={'app-db'})
        report = restore.restore_account(got['app-db'], a.live_db or cfg['app_db'], a.account, out / f'restored-{int(time.time())}.sqlite3'); print(json.dumps(report, indent=2)); return 0
    return 2


def _json(path):
    try: return json.loads(Path(path).read_text())
    except (OSError, ValueError): return None


if __name__ == '__main__':
    sys.exit(main())
