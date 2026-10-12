"""Tenant-aware monitoring with explicit stale/unknown states.

Each check reads facts through a probe and returns ok / warn / crit / unknown. A probe that fails or
returns nothing yields `unknown`, never `ok`. Output carries a correlation id, counts and hashed tenant
labels only: no tenant content, references, tokens or paths. Alerts go through the authorized router;
a recovery is announced once.
"""
import json
import os
from pathlib import Path
import time
import uuid

from . import exposure, pins
from .inventory import gaps

OK, WARN, CRIT, UNKNOWN = 'ok', 'warn', 'crit', 'unknown'
RANK = {OK: 0, UNKNOWN: 1, WARN: 2, CRIT: 3}
REQUIRED_UNITS = ('agentai-platform-app', 'openclaw-dashboard', 'caddy', 'agentai-cells-docker', 'agentai-cells-firewall',
                  'agentai-supervisor-native', 'agentai-lifecycle-worker', 'agentai-cell-bridge', 'agentai-request-worker', 'agentai-model-proxy',
                  'fail2ban', 'docker')
REQUIRED_CONTAINERS = ('openclaw-production-openclaw-gateway-1', 'openclaw-production-litellm-1', 'openclaw-production-postgres-1')
TIMERS = {'agentai-billing-worker.timer': 300, 'agentai-platform-mail.timer': 600, 'openclaw-ops-backup.timer': 2 * 86400,
          'agentai-ops-backup.timer': 2 * 86400, 'agentai-ops-monitor.timer': 1800}
PUBLIC_PORTS = {22, 80, 443}
LOOPBACK_PORTS = {53, 2019, 3978, 4000, 18789, 18790, 18795, 18800, 18801} | set(range(19101, 19141))   # 19101-19140: customer cell Gateways (loopback only)

DEFAULTS = {'backup_max_age_h': 26, 'tenant_backup_max_age_h': 36, 'disk_warn_pct': 85, 'disk_crit_pct': 93, 'mem_warn_mb': 800, 'mem_crit_mb': 300,
            'queue_pending_warn_s': 900, 'inbox_lag_warn_s': 900, 'cert_warn_days': 14, 'cert_crit_days': 7, 'monitor_stale_s': 1800,
            'quarantine_max_days': 7, 'max_running_cells': 1}


def result(check, status, summary, **counts):
    return {'check': check, 'status': status, 'summary': summary, 'counts': counts}


class Monitor:
    def __init__(self, probe, status_path, router=None, *, clock=time.time, thresholds=None):
        self.probe, self.status_path, self.router, self.clock = probe, Path(status_path), router, clock
        self.t = {**DEFAULTS, **(thresholds or {})}

    # -- individual checks: each takes the probe and returns one or more results
    def services(self):
        states = self.probe.service_states(REQUIRED_UNITS)
        bad = [u for u in REQUIRED_UNITS if states.get(u) != 'active']
        return [result('services', CRIT if bad else OK, f'{len(bad)} required service(s) not active: ' + ', '.join(bad) if bad else 'all required services active', inactive=len(bad))]

    def containers(self):
        states = self.probe.container_health(REQUIRED_CONTAINERS)
        bad = [c.split('-')[2] for c, s in states.items() if s not in ('healthy', 'running')] + [c.split('-')[2] for c in REQUIRED_CONTAINERS if c not in states]
        return [result('owner_containers', CRIT if bad else OK, 'owner stack unhealthy: ' + ', '.join(bad) if bad else 'gateway, model proxy and database healthy', unhealthy=len(bad))]

    def capacity(self):
        disk, mem = self.probe.disk_used_percent(), self.probe.mem_available_mb()
        out = []
        out.append(result('disk', CRIT if disk >= self.t['disk_crit_pct'] else WARN if disk >= self.t['disk_warn_pct'] else OK, f'disk {disk:.0f}% used', percent=int(disk)))
        out.append(result('memory', CRIT if mem <= self.t['mem_crit_mb'] else WARN if mem <= self.t['mem_warn_mb'] else OK, f'{mem:.0f} MB memory available', available_mb=int(mem)))
        return out

    def database(self):
        ok = self.probe.app_db_quick_check()
        return [result('app_database', OK if ok else CRIT, 'application database passes its integrity check' if ok else 'application database FAILED its integrity check')]

    def queues(self):
        q, now = self.probe.queue_facts(), self.clock()
        out = []
        stuck = q['oldest_pending_age_s'] > self.t['queue_pending_warn_s'] if q['pending'] else False
        out.append(result('lifecycle_queue', WARN if stuck else OK, 'oldest pending lifecycle operation is stale' if stuck else 'lifecycle queue moving', pending=q['pending']))
        out.append(result('unresolved_holds', CRIT if q['uncertain'] else OK, 'uncertain operations hold the global slot; reconcile them' if q['uncertain'] else 'no uncertain operations', uncertain=q['uncertain']))
        waiting = q['waiting_requests']
        out.append(result('request_queue', WARN if q['oldest_request_age_s'] > 1800 and waiting else OK, 'customer requests waiting too long' if q['oldest_request_age_s'] > 1800 and waiting else 'request queue ok', waiting=waiting))
        lag = q['billing_inbox_lag_s'] > self.t['inbox_lag_warn_s']
        out.append(result('billing_inbox', CRIT if q['billing_dead'] else WARN if lag else OK, 'billing events dead-lettered' if q['billing_dead'] else 'billing events are not being applied' if lag else 'billing inbox current',
                          dead=q['billing_dead'], lag_s=int(q['billing_inbox_lag_s'])))
        return out

    def backups(self):
        status, now = self.probe.backup_status(), self.clock()
        if not status: return [result('backups', UNKNOWN, 'no backup status file; the backup job has never reported')]
        out = []
        success = status.get('last_success_epoch')
        age_h = (now - success) / 3600 if success else None
        if age_h is None: out.append(result('backup_freshness', CRIT, 'no complete backup set exists'))
        else: out.append(result('backup_freshness', CRIT if age_h > self.t['backup_max_age_h'] else OK, f'newest complete backup is {age_h:.1f} h old (target 24 h)', age_h=int(age_h)))
        if status.get('last_complete') is False: out.append(result('backup_last_run', CRIT, 'the last backup run was incomplete: ' + ', '.join(f['source'] for f in status.get('failures', [])) , failures=len(status.get('failures', []))))
        else: out.append(result('backup_last_run', OK, 'last backup run complete'))
        off = status.get('offsite_copy')
        pulled = self.probe.last_pull_epoch() if hasattr(self.probe, 'last_pull_epoch') else None
        recent_pull = bool(pulled) and now - pulled < 7 * 86400
        if off: out.append(result('backup_offsite', OK, 'an automatic off-server copy exists'))
        elif recent_pull: out.append(result('backup_offsite', OK, f'copied to the owner computer {(now - pulled) / 86400:.1f} days ago (manual pull; no automatic off-server destination)'))
        else: out.append(result('backup_offsite', WARN, 'NO off-server copy: backups survive mistakes but not losing this server'))
        manifest = self.probe.latest_manifest()
        if manifest:
            missing = gaps(manifest)
            out.append(result('backup_coverage', CRIT if missing else OK, 'assets without a verified copy: ' + ', '.join(missing) if missing else 'every inventoried asset is in the newest set', gaps=len(missing)))
            fresh_cut = now - self.t['tenant_backup_max_age_h'] * 3600
            stale = [t for t, ts in self.probe.tenant_backup_times(manifest).items() if ts < fresh_cut]
            out.append(result('tenant_backups', WARN if stale else OK, f'{len(stale)} tenant backup(s) older than {self.t["tenant_backup_max_age_h"]} h: ' + ', '.join(sorted(stale)) if stale else 'tenant backups fresh', stale=len(stale)))
        else: out.append(result('backup_coverage', UNKNOWN, 'cannot read the newest backup manifest'))
        return out

    def timers(self):
        now, stale = self.clock(), []
        ages = self.probe.timer_last_run(tuple(TIMERS))
        for timer, limit in TIMERS.items():
            if timer not in ages: continue
            if ages[timer] is None or now - ages[timer] > 3 * limit: stale.append(timer.split('.')[0])
        return [result('timers', WARN if stale else OK, 'timers have not fired recently: ' + ', '.join(stale) if stale else 'scheduled jobs are firing', stale=len(stale))]

    def certificate(self):
        days = self.probe.cert_days_left()
        return [result('tls_certificate', CRIT if days < self.t['cert_crit_days'] else WARN if days < self.t['cert_warn_days'] else OK, f'certificate valid for {days:.0f} more days', days=int(days))]

    def cells(self):
        c = self.probe.cell_facts()
        out = [result('running_cells', CRIT if c['running'] > self.t['max_running_cells'] else OK,
                      'more than one customer cell is running (trial allows one)' if c['running'] > self.t['max_running_cells'] else 'running cells within the global limit', running=c['running'])]
        old = c['quarantine_age_days'] > self.t['quarantine_max_days']
        out.append(result('quarantine', WARN if old else OK, 'a quarantined restore has been kept longer than the limit' if old else 'no stale quarantines', quarantined=c['quarantined']))
        out.append(result('cell_engine', OK if c['engine_up'] and c['firewall_loaded'] else CRIT, 'cell engine and egress firewall loaded' if c['engine_up'] and c['firewall_loaded'] else 'cell engine or egress firewall is NOT loaded'))
        return out

    def exposure(self):
        findings = exposure.evaluate_listeners(self.probe.listeners(), PUBLIC_PORTS, LOOPBACK_PORTS)
        findings += exposure.evaluate_ufw(self.probe.ufw()) + exposure.evaluate_modes(self.probe.file_modes()) + exposure.evaluate_ssh(self.probe.sshd_config())
        worst = max((RANK[s] for s, _ in findings), default=0)
        status = [OK, UNKNOWN, WARN, CRIT][worst]
        return [result('host_exposure', status, '; '.join(m for _, m in findings)[:300] if findings else 'only expected ports open, firewall active, secrets private', findings=len(findings))]

    def pinning(self):
        findings = pins.evaluate_compose(self.probe.read('/opt/openclaw-production/docker-compose.yml')) + pins.evaluate_lock(self.probe.read('/opt/agentai-platform/current/requirements.lock'))
        worst = max((RANK[s] for s, _ in findings), default=0)
        return [result('pinning', [OK, UNKNOWN, WARN, CRIT][worst], '; '.join(m for _, m in findings)[:300] if findings else 'images and dependencies are pinned by digest/hash', findings=len(findings))]

    CHECKS = ('services', 'containers', 'capacity', 'database', 'queues', 'backups', 'timers', 'certificate', 'cells', 'exposure', 'pinning')

    def run(self):
        correlation = uuid.uuid4().hex[:12]
        results = []
        for name in self.CHECKS:
            try: results += getattr(self, name)()
            except Exception as exc:   # a probe that cannot answer is unknown, never ok
                results.append(result(name, UNKNOWN, f'could not be checked ({type(exc).__name__})'))
        overall = max((r['status'] for r in results), key=lambda s: RANK[s])
        status = {'checked_epoch': int(self.clock()), 'correlation_id': correlation, 'overall': overall, 'checks': results,
                  'counts': {s: sum(r['status'] == s for r in results) for s in (OK, WARN, CRIT, UNKNOWN)}}
        previous = {}
        try: previous = json.loads(self.status_path.read_text())
        except (OSError, ValueError): pass
        tmp = self.status_path.with_suffix('.tmp'); tmp.write_text(json.dumps(status, indent=2)); os.chmod(tmp, 0o640); os.replace(tmp, self.status_path)
        if self.router: self._alert(status, previous, correlation)
        return status

    def _alert(self, status, previous, correlation):
        before = {r['check']: r['status'] for r in previous.get('checks', [])}
        for r in status['checks']:
            if r['status'] in (WARN, CRIT):
                self.router.send('monitor.' + r['check'], 'crit' if r['status'] == CRIT else 'warn', r['summary'], correlation_id=correlation, counts=r['counts'])
            elif r['status'] == OK and before.get(r['check']) in (WARN, CRIT):
                self.router.resolved('monitor.' + r['check'], correlation_id=correlation)

    def watchdog(self, other_status_path, name, max_age):
        """Dead-man's switch: alert if the other job's status file has stopped updating."""
        try: age = self.clock() - json.loads(Path(other_status_path).read_text())['checked_epoch' if name == 'monitor' else 'updated_epoch']
        except (OSError, ValueError, KeyError): age = None
        if age is None: return False   # never reported yet: first-run ordering, not a stall (the timers check covers a job that never starts)
        if age > max_age:
            if self.router: self.router.send(f'watchdog.{name}', 'crit', f'the {name} job has not reported recently', correlation_id='watchdog')
            return False
        if self.router: self.router.resolved(f'watchdog.{name}')
        return True
