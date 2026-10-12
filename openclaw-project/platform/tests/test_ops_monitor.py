import json
from pathlib import Path
import tempfile
import unittest
from agentai_platform.ops import exposure
from agentai_platform.ops.alerts import AlertError, AlertRouter, EmailSender, TelegramSender, clean
from agentai_platform.ops.inventory import ASSETS, BACKED_UP, gaps
from agentai_platform.ops.monitor import Monitor, REQUIRED_CONTAINERS, REQUIRED_UNITS, TIMERS, OK, WARN, CRIT, UNKNOWN

NOW = 2_000_000_000


class FakeProbe:
    def __init__(self):
        self.units = {u: 'active' for u in REQUIRED_UNITS}
        self.containers = {c: 'healthy' for c in REQUIRED_CONTAINERS}
        self.disk, self.mem, self.db_ok = 40.0, 5000.0, True
        self.queue = {'pending': 0, 'oldest_pending_age_s': 0, 'uncertain': 0, 'waiting_requests': 0, 'oldest_request_age_s': 0, 'billing_inbox_lag_s': 0, 'billing_dead': 0}
        self.status = {'last_success_epoch': NOW - 3600, 'last_complete': True, 'offsite_copy': True, 'failures': []}
        self.manifest = {'artifacts': [{'asset': a} for a in BACKED_UP]}
        self.tenant_times = {'abc123': NOW - 7200}
        self.timers = {t: NOW - 100 for t in TIMERS}
        self.days = 60.0
        self.cells = {'running': 0, 'engine_up': True, 'firewall_loaded': True, 'quarantined': 0, 'quarantine_age_days': 0}
        self.ports = {('0.0.0.0', 22), ('0.0.0.0', 80), ('0.0.0.0', 443), ('127.0.0.1', 18789)}
        self.files = {'/opt/openclaw-production/docker-compose.yml': 'image: postgres@sha256:' + 'a' * 64 + '\nimage: openclaw-gateway:2026.9.6-sdk-peer\n', '/opt/agentai-platform/current/requirements.lock': 'Django==5.2.17 --hash=sha256:aa\n'}
        self.ufw_text, self.modes, self.ssh = 'Status: active', [], 'PasswordAuthentication no\nPermitRootLogin prohibit-password'
    def service_states(self, units): return dict(self.units)
    def container_health(self, names): return dict(self.containers)
    def disk_used_percent(self): return self.disk
    def mem_available_mb(self): return self.mem
    def app_db_quick_check(self): return self.db_ok
    def queue_facts(self): return dict(self.queue)
    def backup_status(self): return self.status
    def latest_manifest(self): return self.manifest
    def tenant_backup_times(self, m): return dict(self.tenant_times)
    def timer_last_run(self, timers): return dict(self.timers)
    def cert_days_left(self): return self.days
    def cell_facts(self): return dict(self.cells)
    def listeners(self): return set(self.ports)
    def ufw(self): return self.ufw_text
    def file_modes(self): return list(self.modes)
    def sshd_config(self): return self.ssh
    def read(self, path): return self.files.get(path, '')


class Sink:
    name = 'sink'
    def __init__(self): self.sent = []
    def send(self, subject, body): self.sent.append((subject, body))


class MonitorChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root = Path(self.tmp.name)
        self.probe, self.sink, self.now = FakeProbe(), Sink(), NOW
        self.router = AlertRouter([self.sink], self.root / 'alerts.json', clock=lambda: self.now, journal=lambda *_: None)
        self.mon = Monitor(self.probe, self.root / 'status.json', self.router, clock=lambda: self.now)
    def status(self, name, run=None):
        run = run or self.mon.run(); return next(r for r in run['checks'] if r['check'] == name)

    def test_healthy_host_reports_ok_and_sends_nothing(self):
        run = self.mon.run(); self.assertEqual(run['overall'], OK, [r for r in run['checks'] if r['status'] != OK]); self.assertEqual(self.sink.sent, [])
        self.assertRegex(run['correlation_id'], r'^[0-9a-f]{12}$')
    def test_each_failure_is_detected_with_the_right_severity(self):
        self.probe.units['caddy'] = 'failed'; self.assertEqual(self.status('services')['status'], CRIT)
        self.probe.containers.pop(REQUIRED_CONTAINERS[1]); self.assertEqual(self.status('owner_containers')['status'], CRIT)
        self.probe.disk = 88; self.assertEqual(self.status('disk')['status'], WARN); self.probe.disk = 95; self.assertEqual(self.status('disk')['status'], CRIT)
        self.probe.mem = 200; self.assertEqual(self.status('memory')['status'], CRIT)
        self.probe.db_ok = False; self.assertEqual(self.status('app_database')['status'], CRIT)
        self.probe.days = 10; self.assertEqual(self.status('tls_certificate')['status'], WARN); self.probe.days = 3; self.assertEqual(self.status('tls_certificate')['status'], CRIT)
        self.probe.cells['running'] = 2; self.assertEqual(self.status('running_cells')['status'], CRIT)
        self.probe.cells['firewall_loaded'] = False; self.assertEqual(self.status('cell_engine')['status'], CRIT)
        self.probe.cells['quarantine_age_days'] = 9; self.assertEqual(self.status('quarantine')['status'], WARN)
    def test_queue_and_billing_signals(self):
        self.probe.queue.update(pending=2, oldest_pending_age_s=2000); self.assertEqual(self.status('lifecycle_queue')['status'], WARN)
        self.probe.queue['uncertain'] = 1; self.assertEqual(self.status('unresolved_holds')['status'], CRIT)
        self.probe.queue.update(waiting_requests=3, oldest_request_age_s=4000); self.assertEqual(self.status('request_queue')['status'], WARN)
        self.probe.queue['billing_inbox_lag_s'] = 2000; self.assertEqual(self.status('billing_inbox')['status'], WARN)
        self.probe.queue['billing_dead'] = 1; self.assertEqual(self.status('billing_inbox')['status'], CRIT)
    def test_backup_freshness_completeness_offsite_and_per_tenant_staleness(self):
        self.probe.status['last_success_epoch'] = NOW - 27 * 3600; self.assertEqual(self.status('backup_freshness')['status'], CRIT)
        self.probe.status.update(last_success_epoch=NOW - 100, last_complete=False, failures=[{'source': 'app-db'}]); self.assertEqual(self.status('backup_last_run')['status'], CRIT)
        self.probe.status.update(last_complete=True, offsite_copy=False)
        off = self.status('backup_offsite'); self.assertEqual(off['status'], WARN); self.assertIn('NO off-server copy', off['summary'])
        self.probe.manifest = {'artifacts': [{'asset': 'app-db'}]}; cover = self.status('backup_coverage'); self.assertEqual(cover['status'], CRIT); self.assertIn('config', cover['summary'])
        self.probe.manifest = {'artifacts': [{'asset': a} for a in BACKED_UP]}; self.probe.tenant_times = {'abc123': NOW - 40 * 3600, 'def456': 0}
        t = self.status('tenant_backups'); self.assertEqual((t['status'], t['counts']['stale']), (WARN, 2))
        self.assertNotIn('aa-', t['summary'])
    def test_a_recent_manual_pull_counts_as_an_outside_copy_but_an_old_one_does_not(self):
        self.probe.status['offsite_copy'] = False
        self.probe.last_pull_epoch = lambda: NOW - 2 * 86400
        r = self.status('backup_offsite'); self.assertEqual(r['status'], OK); self.assertIn('manual pull', r['summary'])
        self.probe.last_pull_epoch = lambda: NOW - 9 * 86400; self.assertEqual(self.status('backup_offsite')['status'], WARN)
        self.probe.last_pull_epoch = lambda: None; self.assertEqual(self.status('backup_offsite')['status'], WARN)
    def test_missing_backup_status_is_unknown_not_ok(self):
        self.probe.status = None; self.assertEqual(self.status('backups')['status'], UNKNOWN)
    def test_a_probe_that_raises_is_unknown_and_the_rest_still_run(self):
        self.probe.cert_days_left = lambda: (_ for _ in ()).throw(OSError('tls'))
        run = self.mon.run(); self.assertEqual(self.status('certificate', run)['status'], UNKNOWN); self.assertEqual(self.status('services', run)['status'], OK)
        self.assertNotEqual(run['overall'], OK)
    def test_stale_timers_and_exposure(self):
        self.probe.timers['agentai-billing-worker.timer'] = NOW - 3000; self.assertEqual(self.status('timers')['status'], WARN)
        self.probe.timers['agentai-billing-worker.timer'] = None; self.assertEqual(self.status('timers')['status'], WARN)
        self.probe.ports.add(('0.0.0.0', 5432)); self.assertEqual(self.status('host_exposure')['status'], CRIT)
        self.probe.ports.discard(('0.0.0.0', 5432)); self.probe.ssh = 'PasswordAuthentication yes'; self.assertEqual(self.status('host_exposure')['status'], WARN)
    def test_alerts_dedupe_then_resolve_once_and_stay_privacy_safe(self):
        self.probe.units['caddy'] = 'failed'; self.mon.run(); self.mon.run()
        self.assertEqual(len(self.sink.sent), 1); self.assertIn('CRIT', self.sink.sent[0][0])
        self.now += 3601; self.probe.timers = {t: self.now - 100 for t in TIMERS}; self.mon.run(); self.assertEqual(len(self.sink.sent), 2)   # cooldown elapsed
        self.probe.units['caddy'] = 'active'; self.mon.run(); self.mon.run()
        self.assertEqual([s for s, _ in self.sink.sent].count('[AgentAI RESOLVED] monitor.services'), 1)
        for subject, body in self.sink.sent: self.assertNotRegex(subject + body, r'aa-[a-f0-9]{32}|sk_test|whsec_')
    def test_watchdog_notices_a_silent_job(self):
        (self.root / 'other.json').write_text(json.dumps({'checked_epoch': NOW - 100}))
        self.assertTrue(self.mon.watchdog(self.root / 'other.json', 'monitor', 1800))
        self.now += 4000; self.assertFalse(self.mon.watchdog(self.root / 'other.json', 'monitor', 1800)); self.assertTrue(any('watchdog.monitor' in s for s, _ in self.sink.sent))
        before = len(self.sink.sent); self.assertFalse(self.mon.watchdog(self.root / 'missing.json', 'monitor', 1800)); self.assertEqual(len(self.sink.sent), before)   # first run: no false alarm


class PinningChecks(unittest.TestCase):
    def test_unpinned_images_and_dependencies_are_flagged(self):
        from agentai_platform.ops import pins
        self.assertEqual(pins.evaluate_compose('image: x@sha256:' + 'a' * 64), [])
        self.assertEqual(pins.evaluate_compose('image: nginx:latest')[0][0], 'crit'); self.assertEqual(pins.evaluate_compose('image: nginx:1.27')[0][0], 'warn')
        self.assertEqual(pins.evaluate_lock('Django==5.2 --hash=sha256:ab \\\n    --hash=sha256:cd\n'), []); self.assertEqual(pins.evaluate_lock('Django>=5\n')[0][0], 'crit')
        self.assertEqual(pins.evaluate_custody({'cli': {}})[0][0], 'crit')
    def test_monitor_reports_pinning(self):
        probe = FakeProbe(); probe.files['/opt/openclaw-production/docker-compose.yml'] = 'image: nginx:latest\n'
        with tempfile.TemporaryDirectory() as d:
            run = Monitor(probe, Path(d) / 's.json', None, clock=lambda: NOW).run()
        self.assertEqual(next(r for r in run['checks'] if r['check'] == 'pinning')['status'], CRIT)


class AlertChecks(unittest.TestCase):
    def test_clean_strips_secrets_references_and_control_characters(self):
        dirty = 'token sk_test_abcdefghij ref aa-' + 'a1' * 16 + ' whsec_abc password=hunter2 \x1b[31mred'
        out = clean(dirty)
        for bad in ('sk_test_', 'aa-a1', 'whsec_', 'hunter2', '\x1b'): self.assertNotIn(bad, out)
    def test_only_valid_alerts_and_cooldown_per_severity(self):
        with tempfile.TemporaryDirectory() as d:
            sink, t = Sink(), [NOW]
            router = AlertRouter([sink], Path(d) / 's.json', clock=lambda: t[0], journal=lambda *_: None)
            for bad in (('Bad Kind', 'warn'), ('ok', 'fatal')):
                with self.assertRaises(AlertError): router.send(bad[0], bad[1], 'x')
            self.assertTrue(router.send('k', 'warn', 'one')); self.assertFalse(router.send('k', 'warn', 'again')); self.assertTrue(router.send('k', 'crit', 'worse'))
            t[0] += 7 * 3600; self.assertTrue(router.send('k', 'crit', 'still'))
    def test_a_failing_sender_does_not_block_the_others_or_crash(self):
        class Boom:
            name = 'boom'
            def send(self, *a): raise OSError('down')
        with tempfile.TemporaryDirectory() as d:
            ok = Sink(); router = AlertRouter([Boom(), ok], Path(d) / 's.json', journal=lambda *_: None); self.assertTrue(router.send('k', 'crit', 'x')); self.assertEqual(len(ok.sent), 1)
            self.assertFalse(AlertRouter([Boom()], Path(d) / 't.json', journal=lambda *_: None).send('k', 'crit', 'x'))
    def test_senders_validate_destinations(self):
        with self.assertRaises(AlertError): EmailSender('h', 'u', lambda: 'p', 'a@b.c', [])
        with self.assertRaises(AlertError): TelegramSender(lambda: 't', 'not-a-number')
        calls = []
        class FakeSMTP:
            def __init__(s, *a, **k): pass
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def starttls(s): calls.append('tls')
            def login(s, u, p): calls.append(('login', u))
            def send_message(s, m): calls.append(('to', m['To']))
        EmailSender('h', 'u', lambda: 'p', 'from@x.y', ['owner@x.y'], smtp=FakeSMTP).send('s', 'b'); self.assertEqual(calls, ['tls', ('login', 'u'), ('to', 'owner@x.y')])


class ExposureAndInventoryChecks(unittest.TestCase):
    SS = 'LISTEN 0 4096 0.0.0.0:22 0.0.0.0:*\nLISTEN 0 4096 127.0.0.1:18789 0.0.0.0:*\nLISTEN 0 4096 [::]:22 [::]:*\nLISTEN 0 4096 *:443 *:*\n'
    def test_listener_evaluation(self):
        ls = exposure.parse_listeners(self.SS); self.assertEqual(ls, {('0.0.0.0', 22), ('127.0.0.1', 18789), ('::', 22), ('*', 443)})
        self.assertEqual(exposure.evaluate_listeners(ls, {22, 80, 443}, {18789}), [])
        self.assertEqual(exposure.evaluate_listeners(ls | {('0.0.0.0', 3306)}, {22, 443}, {18789})[0][0], 'crit')
        self.assertEqual(exposure.evaluate_listeners({('127.0.0.1', 9999)}, set(), set())[0][0], 'warn')
        self.assertEqual(exposure.evaluate_listeners({('127.0.0.1', 32771)}, set(), set()), [])   # docker published loopback range
    def test_permission_ufw_and_ssh_rules(self):
        self.assertEqual(exposure.evaluate_modes([('/s', 0o100600, 0, 0o600, 0)]), []); self.assertEqual(exposure.evaluate_modes([('/s', 0o100644, 0, 0o600, 0)])[0][0], 'crit')
        self.assertEqual(exposure.evaluate_ufw('Status: inactive')[0][0], 'crit'); self.assertEqual(exposure.evaluate_ufw('Status: active'), [])
        self.assertEqual(len(exposure.evaluate_ssh('')), 2); self.assertEqual(exposure.evaluate_ssh('PasswordAuthentication no\nPermitRootLogin prohibit-password'), [])
    def test_inventory_is_complete_and_gaps_are_named(self):
        ids = {a.id for a in ASSETS}
        for needed in ('app-db', 'custody-db', 'tenant-cells', 'tenant-secrets', 'litellm-spend', 'owner-state', 'config', 'encryption-keys'): self.assertIn(needed, ids)
        self.assertTrue(all(a.owner and a.restore and a.method for a in ASSETS))
        self.assertEqual(gaps({'artifacts': [{'asset': a} for a in BACKED_UP]}), [])
        self.assertIn('app-db', gaps({'artifacts': []})); self.assertNotIn('tenant-cells', gaps({'artifacts': [{'asset': 'app-db'}]}))   # no tenants yet is not a gap
        keys = next(a for a in ASSETS if a.id == 'encryption-keys'); self.assertIn('NEVER on the host', keys.where)
if __name__ == '__main__': unittest.main()
