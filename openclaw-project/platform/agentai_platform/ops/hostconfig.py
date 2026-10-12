"""Builds the real backup job, monitor and alert router from /etc/agentai-ops/config.json.

Everything host-specific is data in the config file; defaults describe the current single-server layout.
"""
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

from .alerts import AlertRouter, EmailSender, TelegramSender
from .backup import BackupJob, Source, files_source, latest_file_source, sqlite_source
from .crypto import AgeCrypto
from .destinations import CommandDestination, LocalDir
from .hostprobe import HostProbe, sh
from .inventory import BACKED_UP

DEFAULTS = {
    'app_db': '/var/lib/agentai-platform/platform.sqlite3', 'custody_db': '/var/lib/agentai-supervisor/custody.sqlite3',
    'tenant_secrets_dir': '/var/lib/agentai-supervisor-secrets', 'cell_backup_root': '/var/lib/agentai-cells/backups',
    'owner_backup_dir': '/opt/openclaw-production/backups/ops', 'state_dir': '/var/lib/agentai-ops',
    'backup_status': '/var/lib/agentai-ops/backup-status.json', 'monitor_status': '/var/lib/agentai-ops/monitor-status.json',
    'alert_state': '/var/lib/agentai-ops/alert-state.json', 'work_root': '/var/lib/agentai-ops/work', 'age_recipients': [],
    'destinations': [{'type': 'local', 'path': '/var/backups/agentai', 'offsite': False}], 'alerts': {}, 'hostname': 'backend.getlumina.pro',
    'config_paths': ['/etc/agentai-platform/accounts.env', '/etc/agentai-supervisor', '/etc/agentai-cells', '/etc/agentai-ops/config.json', '/etc/caddy/Caddyfile',
                     '/etc/docker/daemon.json', '/etc/systemd/system', '/opt/openclaw-production/docker-compose.yml', '/opt/openclaw-production/secrets',
                     '/opt/openclaw-production/config', '/opt/openclaw-production/feature-switches', '/var/lib/agentai-platform/billing', '/opt/agentai-platform/billing-plan.json'],
    'private_paths': [['/etc/agentai-platform/accounts.env', 0o600, 0], ['/var/lib/agentai-platform/platform.sqlite3', 0o600, None],
                      ['/var/lib/agentai-supervisor-secrets', 0o700, 0], ['/etc/agentai-supervisor/fleet-custody.json', 0o600, 0],
                      ['/opt/openclaw-production/secrets', 0o700, None], ['/var/backups/agentai', 0o700, 0], ['/var/lib/agentai-ops', 0o750, 0]],
}


def load(path='/etc/agentai-ops/config.json'):
    cfg = dict(DEFAULTS)
    try: cfg.update(json.loads(Path(path).read_text()))
    except FileNotFoundError: pass
    return cfg


def destinations(cfg):
    out = []
    for d in cfg['destinations']:
        if d['type'] == 'local': out.append(LocalDir(d['path'], offsite=bool(d.get('offsite', False))))
        elif d['type'] == 'command': out.append(CommandDestination(d['put'], d['list'], d['remove'], offsite=bool(d.get('offsite', True))))
        else: raise ValueError('unknown destination type')
    return out


def env_file(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k, _, v = line.partition('='); values[k.strip()] = v.strip().strip('"\'')
    return values


def router(cfg):
    senders, a = [], cfg.get('alerts') or {}
    if a.get('email', {}).get('enabled'):
        e = env_file(a['email']['smtp_env_file'])
        senders.append(EmailSender(e['AGENTAI_SMTP_HOST'], e['AGENTAI_SMTP_USER'], lambda: env_file(a['email']['smtp_env_file'])['AGENTAI_SMTP_PASSWORD'],
                                   e.get('AGENTAI_FROM_EMAIL', e['AGENTAI_SMTP_USER']), a['email']['to']))
    if a.get('telegram', {}).get('enabled'):
        t = a['telegram']; senders.append(TelegramSender(lambda: Path(t['token_file']).read_text().strip(), t['chat_id']))
    return AlertRouter(senders, cfg['alert_state'])


def versions_source(cfg, release):
    def produce(work):
        facts = {'generated_epoch': int(time.time()), 'release': release, 'kernel': platform.release(), 'python': sys.version.split()[0],
                 'age': sh(['age', '--version'])[1].strip(), 'runsc': sh(['runsc', '--version'])[1].splitlines()[:1],
                 'docker': sh(['docker', '--version'])[1].strip(), 'images': sorted(l for l in sh(['docker', 'images', '--digests', '--format', '{{.Repository}}:{{.Tag}} {{.Digest}}'])[1].splitlines() if l),
                 'cell_images': sorted(l for l in sh(['docker', 'images', '--digests', '--format', '{{.Repository}}:{{.Tag}} {{.Digest}}'], {'DOCKER_HOST': 'unix:///run/agentai-cells/docker.sock'})[1].splitlines() if l),
                 'packages': {p: sh(['dpkg-query', '-W', '-f', '${Version}', p])[1] for p in ('caddy', 'docker-ce', 'fail2ban', 'nftables', 'age', 'sqlite3')},
                 'lock_sha256': sh(['sha256sum', f'/opt/agentai-platform/current/requirements.lock'])[1].split()[:1]}
        out = work / 'versions.json'; out.write_text(json.dumps(facts, indent=2)); return out
    return Source('versions', 'json', produce, asset='versions')


def tenants(cfg):
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{cfg['custody_db']}?mode=ro", uri=True)
        try: return [(a, t) for a, t in con.execute('SELECT account, tenant FROM bindings')]
        finally: con.close()
    except Exception: return []


def sources(cfg, clock=time.time):
    day = 26 * 3600
    release = os.path.basename(os.path.realpath('/opt/agentai-platform/current'))
    out = [sqlite_source('app-db', cfg['app_db'], asset='app-db'), sqlite_source('custody-db', cfg['custody_db'], asset='custody-db'),
           files_source('config', cfg['config_paths'], asset='config'), files_source('tenant-secrets', [cfg['tenant_secrets_dir']], asset='tenant-secrets'),
           latest_file_source('owner-state', cfg['owner_backup_dir'], 'oc-ops-*.tar.gz', 'tar', day, clock, asset='owner-state'),
           latest_file_source('litellm', cfg['owner_backup_dir'], 'litellm-2*.sql', 'pgdump', day, clock, asset='litellm'),
           versions_source(cfg, release)]
    for account, tenant in tenants(cfg):
        out.append(latest_file_source(f'cell-{tenant[3:11]}', Path(cfg['cell_backup_root']) / account, '*.tgz', 'tar', 36 * 3600, clock,
                                      asset='tenant-cells', tenant=tenant))
        out[-1].optional = True   # a running cell cannot be archived; the monitor flags a stale tenant instead of failing the set
    return out, release


def backup_job(cfg):
    srcs, release = sources(cfg)
    expected = [a for a in BACKED_UP if a != 'tenant-cells']
    return BackupJob(srcs, AgeCrypto(cfg['age_recipients']), destinations(cfg), work_root=cfg['work_root'], status_path=cfg['backup_status'],
                     alert=lambda kind, report: router(cfg).send(kind, 'crit', f"backup set {report['set_id']} incomplete: " + ', '.join(f['source'] for f in report['failures']) + ' ' + ', '.join(report['missing_assets']),
                                                               correlation_id=report['set_id']),
                     release=release, expected_assets=expected)


def probe(cfg):
    return HostProbe(cfg, destinations(cfg)[0])
