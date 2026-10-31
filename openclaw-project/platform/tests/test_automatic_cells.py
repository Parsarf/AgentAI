"""Automatic host enrollment and wake orchestration; no real containers/models."""
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest

from agentai_platform.lifecycle.enrollment import EnrollmentPolicy
from agentai_platform.lifecycle.supervisor import HostSupervisor, SupervisorBusy
from agentai_platform.lifecycle.types import Claim, Conflict
from tests.test_supervisor import Backend
from tests import test_worker as fixtures

IMAGE = 'ghcr.io/openclaw/openclaw@sha256:' + 'a' * 64


class EnrollmentChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.backups = self.root / 'backups'; self.backups.mkdir(mode=0o700)
        self.config = {'image': IMAGE, 'profile': 'trial-unmeasured-v1',
                       'backup_root': str(self.backups), 'max_cells': 2}
        self.backend = Backend()
        self.supervisor = HostSupervisor(self.root / 'host', self.backend, enrollment=EnrollmentPolicy(self.config))

    def claim(self, account='a', digit='1'):
        return Claim(account, digit * 32, 'aa-' + digit * 32, digit * 32,
                     'create', 1, self.config['profile'], None, 1, 'worker')

    def rows(self):
        with self.supervisor.connect() as con:
            return [dict(r) for r in con.execute('SELECT * FROM bindings ORDER BY account')]

    def test_create_enrolls_two_distinct_cells_and_replay_never_rebinds(self):
        a, b = self.claim(), self.claim('b', '2')
        receipt = self.supervisor.execute(a)
        self.supervisor.execute(b)
        self.assertEqual(self.supervisor.execute(a), receipt)
        self.assertEqual(len(self.backend.calls), 2)
        rows = self.rows()
        self.assertEqual([r['state'] for r in rows], ['stopped', 'stopped'])
        specs = [json.loads(r['spec']) for r in rows]
        self.assertEqual([s['port'] for s in specs], [19101, 19102])
        self.assertEqual([s['quarantine_port'] for s in specs], [19151, 19152])
        self.assertEqual([s['image'] for s in specs], [IMAGE, IMAGE])
        self.assertEqual([s['backup_root'] for s in specs], [str(self.backups / 'a'), str(self.backups / 'b')])
        for bad in (replace(a, tenant_ref=b.tenant_ref), replace(a, deployment_id=b.deployment_id), replace(a, target_profile='other')):
            with self.assertRaises(Conflict): self.supervisor.execute(bad)
        self.assertEqual(self.rows(), rows)

    def test_enrollment_refuses_unapproved_profile_non_create_stale_and_duplicate_identity(self):
        claim = self.claim()
        for bad in (replace(claim, target_profile='other'), replace(claim, generation=2)):
            with self.assertRaises(Conflict): self.supervisor.execute(bad)
        with self.assertRaises(SupervisorBusy): self.supervisor.execute(replace(claim, kind='start'))
        self.assertEqual(self.rows(), [])
        self.supervisor.execute(claim)
        with self.assertRaises(Conflict): self.supervisor.execute(replace(self.claim('b', '2'), tenant_ref=claim.tenant_ref))
        self.assertEqual(len(self.rows()), 1)

    def test_host_capacity_is_independent_and_never_overwrites_an_existing_cell(self):
        self.supervisor.execute(self.claim())
        self.supervisor.execute(self.claim('b', '2'))
        with self.assertRaises(SupervisorBusy): self.supervisor.execute(self.claim('c', '3'))
        self.assertEqual(len(self.rows()), 2)

    def test_no_policy_preserves_manual_enrollment_requirement(self):
        host = HostSupervisor(self.root / 'manual', self.backend)
        with self.assertRaises(SupervisorBusy): host.execute(self.claim())
        self.assertEqual(self.backend.calls, [])

    def test_invalid_policy_and_untrusted_policy_files_are_refused(self):
        for change in ({'image': 'openclaw:latest'}, {'max_cells': True}, {'max_cells': 40},
                       {'profile': '../x'}, {'backup_root': '/tmp/../x'}, {'command': 'exec'}):
            with self.assertRaises(ValueError): EnrollmentPolicy({**self.config, **change})
        path = self.root / 'policy.json'; path.write_text(json.dumps(self.config)); path.chmod(0o600)
        self.assertIsInstance(EnrollmentPolicy.load(path, owner_uid=os.geteuid()), EnrollmentPolicy)
        path.chmod(0o666)
        with self.assertRaises(PermissionError): EnrollmentPolicy.load(path, owner_uid=os.geteuid())
        path.chmod(0o600)
        linked = self.root / 'link'; linked.symlink_to(path)
        with self.assertRaises(OSError): EnrollmentPolicy.load(linked, owner_uid=os.geteuid())
        self.backups.chmod(0o755)
        with self.assertRaises(PermissionError): EnrollmentPolicy.load(path, owner_uid=os.geteuid())
        self.backups.chmod(0o700)

    def test_backup_path_cannot_follow_another_accounts_directory(self):
        (self.backups / 'a').symlink_to(self.backups / 'b', target_is_directory=True)
        with self.assertRaises((PermissionError, FileExistsError)): self.supervisor.execute(self.claim())
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.backend.calls, [])


class ApprovalWakeChecks(unittest.TestCase):
    setUp, worker, state = fixtures.WorkerChecks.setUp, fixtures.WorkerChecks.worker, fixtures.WorkerChecks.state
    submit, queue = fixtures.WakeChecks.submit, fixtures.WakeChecks.queue

    def test_approval_create_reaches_host_without_manual_enrollment_then_prompt_wakes_only_its_cell(self):
        backups = self.root / 'backups'; backups.mkdir(mode=0o700)
        backend = Backend()
        policy = EnrollmentPolicy({'image': IMAGE, 'profile': 'trial-unmeasured-v1',
                                   'backup_root': str(backups), 'max_cells': 2})
        host = HostSupervisor(self.root / 'host', backend, enrollment=policy)
        for account in ('a', 'b'):
            self.engine.host_create(account, key='signup-' + account, target_profile='trial-unmeasured-v1')
        worker = self.worker(driver=host, wake=True, idle_after=10**12)
        self.assertEqual(worker.tick()['ran'], 2)
        self.assertEqual((self.state('a'), self.state('b')), ('stopped', 'stopped'))
        self.submit('b')
        self.assertIsNone(self.queue().claim(owner='request-worker', capacity=self.capacity()))
        self.assertEqual(worker.tick()['woken'], 1)
        worker.tick()
        self.assertEqual((self.state('a'), self.state('b')), ('stopped', 'running'))
        claim = self.queue().claim(owner='request-worker', capacity=self.capacity())
        self.assertEqual(claim.account_id, 'b')
        self.assertEqual([(c.account_id, c.kind) for c in backend.calls], [('a', 'create'), ('b', 'create'), ('b', 'start')])
