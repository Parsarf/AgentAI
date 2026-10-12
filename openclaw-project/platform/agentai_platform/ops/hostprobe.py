"""The real probe: reads the host with fixed commands and read-only database opens. No writes, no network except localhost TLS."""
import glob
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time

from .backup import tenant_hash
from .sets import SetError, load_manifest

CELL_SOCK = 'unix:///run/agentai-cells/docker.sock'


def sh(argv, env=None, timeout=20):
    """(returncode, stdout); a missing tool or a timeout is a non-zero code, never an exception."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, env={**os.environ, **(env or {})})
    except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
        return 127, ''
    return done.returncode, done.stdout


class HostProbe:
    def __init__(self, cfg, destination, clock=time.time):
        self.cfg, self.dest, self.clock = cfg, destination, clock

    def _db(self, path=None):
        return sqlite3.connect(f"file:{path or self.cfg['app_db']}?mode=ro", uri=True, timeout=5)

    def service_states(self, units):
        return {u: sh(['systemctl', 'is-active', u])[1].strip() for u in units}

    def container_health(self, names):
        out = {}
        for n in names:
            code, text = sh(['docker', 'inspect', '-f', '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}', n])
            if code == 0: out[n] = text.strip()
        return out

    def disk_used_percent(self):
        u = shutil.disk_usage('/'); return 100 * u.used / u.total

    def mem_available_mb(self):
        for line in open('/proc/meminfo'):
            if line.startswith('MemAvailable:'): return int(line.split()[1]) / 1024
        raise OSError('MemAvailable missing')

    def app_db_quick_check(self):
        con = self._db()
        try: return con.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        finally: con.close()

    def queue_facts(self):
        now, con = self.clock(), self._db()
        try:
            one = lambda sql, *a: con.execute(sql, a).fetchone()[0]
            oldest_op = one("SELECT min(strftime('%s',created_at)) FROM operations WHERE state='pending'")
            oldest_req = one("SELECT min(created_epoch) FROM customer_requests WHERE state='waiting'")
            oldest_evt = one("SELECT min(received_epoch) FROM billing_inbox WHERE status='received'") if self._has(con, 'billing_inbox') else None
            return {'pending': one("SELECT count(*) FROM operations WHERE state='pending'"), 'oldest_pending_age_s': now - int(oldest_op) if oldest_op else 0,
                    'uncertain': one("SELECT count(*) FROM operations WHERE state='uncertain'"),
                    'waiting_requests': one("SELECT count(*) FROM customer_requests WHERE state='waiting'"), 'oldest_request_age_s': now - oldest_req if oldest_req else 0,
                    'billing_inbox_lag_s': now - oldest_evt if oldest_evt else 0,
                    'billing_dead': one("SELECT count(*) FROM billing_inbox WHERE status='dead'") if self._has(con, 'billing_inbox') else 0}
        finally: con.close()

    @staticmethod
    def _has(con, table): return con.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone() is not None

    def backup_status(self):
        try: return json.loads(Path(self.cfg['backup_status']).read_text())
        except (OSError, ValueError): return None

    def last_pull_epoch(self):
        try: return json.loads(Path(self.cfg.get('last_pull', '/var/lib/agentai-ops/last-pull.json')).read_text())['epoch']
        except (OSError, ValueError, KeyError): return None

    def latest_manifest(self):
        from .sets import newest_complete
        sid = newest_complete(self.dest)
        return load_manifest(self.dest, sid) if sid else None

    def enrolled_tenants(self):
        try:
            con = self._db(self.cfg['custody_db'])
            try: return [r[0] for r in con.execute('SELECT tenant FROM bindings')]
            finally: con.close()
        except sqlite3.Error: return []

    def tenant_backup_times(self, manifest):
        newest = {tenant_hash(t): 0 for t in self.enrolled_tenants()}
        for name, _, _ in sorted(self.dest.list('sets/'), reverse=True):
            if not name.endswith('/manifest.json'): continue
            try: m = load_manifest(self.dest, name.split('/')[1])
            except SetError: continue
            if not m.get('complete'): continue
            for art in m['artifacts']:
                if art.get('tenant') in newest and newest[art['tenant']] < m['created_epoch']: newest[art['tenant']] = m['created_epoch']
        return newest

    def timer_last_run(self, timers):
        out = {}
        for t in timers:
            code, text = sh(['systemctl', 'show', t, '-p', 'LastTriggerUSec', '--value'])
            if code != 0 or sh(['systemctl', 'cat', t])[0] != 0: continue
            text = text.strip()
            try: out[t] = time.mktime(time.strptime(text.rsplit(' ', 1)[0], '%a %Y-%m-%d %H:%M:%S')) - time.timezone if text and text != 'n/a' else None
            except ValueError: out[t] = None
        return out

    def cert_days_left(self):
        p1 = subprocess.run(['openssl', 's_client', '-connect', '127.0.0.1:443', '-servername', self.cfg.get('hostname', 'backend.getlumina.pro')],
                            input=b'', capture_output=True, timeout=15)
        p2 = subprocess.run(['openssl', 'x509', '-noout', '-enddate'], input=p1.stdout, capture_output=True, timeout=10)
        text = p2.stdout.decode().strip().partition('=')[2]
        return (time.mktime(time.strptime(text, '%b %d %H:%M:%S %Y %Z')) - time.timezone - self.clock()) / 86400

    def cell_facts(self):
        env = {'DOCKER_HOST': CELL_SOCK}
        code, running = sh(['docker', 'ps', '-q'], env)
        quarantine = Path(self.cfg.get('quarantine_state', '/var/lib/agentai-cells/quarantine.json'))
        try: quarantined = len(json.loads(quarantine.read_text())); age = (self.clock() - quarantine.stat().st_mtime) / 86400 if quarantined else 0
        except (OSError, ValueError): quarantined, age = 0, 0
        return {'running': len(running.split()) if code == 0 else 0, 'engine_up': code == 0, 'firewall_loaded': sh(['nft', 'list', 'table', 'inet', 'agentai_cells'])[0] == 0,
                'quarantined': quarantined, 'quarantine_age_days': age}

    def listeners(self):
        from .exposure import parse_listeners
        return parse_listeners(sh(['ss', '-ltn'])[1])

    def ufw(self): return sh(['ufw', 'status'])[1]

    def file_modes(self):
        rows = []
        for path, max_mode, owner in self.cfg.get('private_paths', []):
            try: st = os.lstat(path); rows.append((path, st.st_mode, st.st_uid, max_mode, owner))
            except OSError: continue
        return rows

    def read(self, path): return Path(path).read_text()

    def sshd_config(self):
        text = ''
        for p in ['/etc/ssh/sshd_config'] + sorted(glob.glob('/etc/ssh/sshd_config.d/*.conf')):
            try: text += Path(p).read_text() + '\n'
            except OSError: pass
        return text
