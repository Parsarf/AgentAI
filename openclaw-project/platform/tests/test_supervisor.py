"""Host orchestration assertions, not native container isolation acceptance."""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import socket
import sqlite3
import tempfile
import threading
import unittest

from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.lifecycle.fleet_plan import FleetBinding
from agentai_platform.lifecycle.types import Claim, Conflict, DisabledDriver, Receipt
from agentai_platform.lifecycle.supervisor import HostSupervisor, OutcomeUncertain, SupervisorBusy, decode_claim
from agentai_platform.lifecycle.supervisor_transport import SocketDriver, dispatch, encode, handle_connection, read_message


class Backend:
    def __init__(self):
        self.calls=[];self.receipts={};self.fail=False;self.reject=False;self.bad=False
    def check(self,kind): pass
    def execute(self,binding,claim):
        self.calls.append(claim)
        target={'create':'stopped','start':'running','stop':'stopped','backup':'stopped',
                'restore':'stopped','upgrade':'running','delete':'absent'}[claim.kind]
        if self.reject: target='absent'
        receipt=Receipt(claim.account_id,claim.deployment_id,claim.operation_id,claim.generation,
            target,not self.reject,target!='running',
            claim.operation_id if claim.kind=='backup' and not self.reject else None,fence=claim.fence)
        self.receipts[claim.operation_id]=receipt
        if self.fail: raise TimeoutError('secret-bearing output must not escape')
        return replace(receipt,fence=claim.fence+1) if self.bad else receipt
    def reconcile(self,binding,claim): return self.receipts.get(claim.operation_id)


class SupervisorChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.backend=Backend()
        self.s=HostSupervisor(self.root/'custody',self.backend)
        self.bindings={}
        for i,a in enumerate(('a','b'),1):
            binding=FleetBinding(a,str(i)*32,'aa-'+str(i)*32,'trial-v1',
                'ghcr.io/openclaw/openclaw@sha256:'+'a'*64,19100+i,512*1024**2,500,64,
                128*1024**2,self.root/a)
            self.s.enroll(binding);self.bindings[a]=binding
        self.seq=0

    def claim(self,kind='create',account='a',**kw):
        self.seq+=1;b=self.bindings[account]
        c=Claim(account,b.deployment_id,b.tenant_ref,format(self.seq,'032x'),kind,1,'trial-v1',None,1,'controller')
        return replace(c,**kw)

    def test_enrollment_is_independent_and_cannot_overwrite(self):
        with self.assertRaises(sqlite3.IntegrityError): self.s.enroll(self.bindings['a'])
        c=self.claim()
        for changed in (replace(c,account_id='b'),replace(c,tenant_ref=self.bindings['b'].tenant_ref),
                        replace(c,deployment_id=self.bindings['b'].deployment_id),replace(c,target_profile='injected')):
            with self.assertRaises(Conflict): self.s.execute(changed)
        self.assertEqual(self.backend.calls,[])

    def test_replay_returns_durable_receipt_without_another_effect(self):
        c=self.claim();r=self.s.execute(c)
        other=HostSupervisor(self.root/'custody',self.backend)
        self.assertEqual(other.execute(c),r);self.assertEqual(len(self.backend.calls),1)
        with self.assertRaises(Conflict): other.execute(replace(c,kind='delete'))
        with self.assertRaises(Conflict): other.execute(replace(c,fence=2))

    def test_failure_holds_every_account_until_receipt_reconciliation(self):
        c=self.claim();self.backend.fail=True
        with self.assertRaises(TimeoutError): self.s.execute(c)
        self.backend.fail=False
        with self.assertRaises(OutcomeUncertain): self.s.execute(c)
        with self.assertRaises(OutcomeUncertain): self.s.execute(self.claim(account='b'))
        self.assertIsNotNone(self.s.reconcile(c));self.s.execute(self.claim(account='b'))
        self.assertEqual(len(self.backend.calls),2)

    def test_missing_reconciliation_never_dispatches(self):
        c=self.claim();self.backend.fail=True
        with self.assertRaises(TimeoutError): self.s.execute(c)
        self.backend.receipts.clear()
        self.assertIsNone(self.s.reconcile(c));self.assertEqual(len(self.backend.calls),1)
        with self.assertRaises(Conflict): self.s.reconcile(replace(c,fence=2))

    def test_crash_left_running_intent_blocks_new_effects(self):
        c=self.claim();self.s.execute(c)
        with self.s.connect() as con:
            con.execute("UPDATE journal SET status='running',receipt=NULL WHERE operation=?",(c.operation_id,))
        restarted=HostSupervisor(self.root/'custody',self.backend)
        with self.assertRaises(OutcomeUncertain): restarted.execute(self.claim(account='b'))
        restarted.reconcile(c);self.assertEqual(len(self.backend.calls),1)

    def test_retry_requires_definitive_quiescence_and_higher_attempt_fence(self):
        c=self.claim();self.backend.reject=True;r=self.s.execute(c)
        self.assertFalse(r.applied);self.assertTrue(r.quiesced)
        with self.assertRaises(Conflict): self.s.execute(replace(c,owner='another'))
        self.backend.reject=False
        r=self.s.execute(replace(c,fence=2,owner='another'))
        self.assertTrue(r.applied);self.assertEqual(r.fence,2)
        with self.assertRaises(Conflict): self.s.execute(c)

    def test_bad_fence_receipt_is_uncertain_and_cannot_release(self):
        self.backend.bad=True;c=self.claim()
        with self.assertRaises(Conflict): self.s.execute(c)
        with self.assertRaises(OutcomeUncertain): self.s.execute(self.claim(account='b'))

    def test_only_one_active_cell_and_new_operations_have_own_fences(self):
        self.s.execute(self.claim());self.s.execute(self.claim(account='b'))
        self.s.execute(self.claim('start'))
        with self.assertRaises(SupervisorBusy): self.s.execute(self.claim('start','b'))
        self.s.execute(self.claim('stop'));self.s.execute(self.claim('start','b'))

    def test_multiple_instances_cannot_dispatch_under_same_lock(self):
        other=HostSupervisor(self.root/'custody',self.backend)
        with self.s.serialized():
            with self.assertRaises(SupervisorBusy): other.execute(self.claim())
        self.assertEqual(self.backend.calls,[])

    def test_host_state_and_generation_checked_before_dispatch(self):
        with self.assertRaises(Conflict): self.s.execute(self.claim('start'))
        self.s.execute(self.claim())
        with self.assertRaises(Conflict): self.s.execute(self.claim(generation=2))
        with self.assertRaises(Conflict): self.s.execute(self.claim())
        with self.assertRaises(Conflict): self.s.execute(self.claim('upgrade'))

    def test_foreign_and_stale_backups_denied(self):
        self.s.execute(self.claim());self.s.execute(self.claim(account='b'))
        c=self.claim('backup');self.s.execute(c)
        with self.assertRaises(Conflict): self.s.execute(self.claim('restore','b',backup_ref=c.operation_id))
        r=self.s.execute(self.claim('restore',backup_ref=c.operation_id))
        self.assertEqual(r.generation,1)
        with self.assertRaises(Conflict): self.s.execute(self.claim('restore',generation=2,backup_ref=c.operation_id))

    def test_custody_modes_and_links_rejected(self):
        self.assertEqual(self.s.db.stat().st_mode&0o777,0o600)
        self.s.db.chmod(0o644)
        with self.assertRaises(PermissionError): HostSupervisor(self.root/'custody',self.backend)
        self.s.db.chmod(0o600)
        root=self.root/'linked';root.mkdir(mode=0o700)
        (root/'custody.sqlite3').symlink_to(self.s.db)
        with self.assertRaises(OSError): HostSupervisor(root,self.backend)

    def test_claim_schema_denies_commands_unknown_fields_and_boolean_revisions(self):
        payload=asdict(self.claim())
        for bad in ({**payload,'command':'rm -rf /'},{**payload,'fence':True},
                    {**payload,'kind':'shell'},{**payload,'tenant_ref':'../owner'},
                    {**payload,'operation_id':'x'*33},{**payload,'backup_ref':'a'*32}):
            with self.assertRaises(Conflict): decode_claim(bad)
        with self.assertRaises(Conflict): dispatch(self.s,{'action':'enroll','claim':payload})

    def test_newer_custody_schema_is_rejected(self):
        with self.s.connect() as con: con.execute('PRAGMA user_version=2')
        with self.assertRaises(Conflict): HostSupervisor(self.root/'custody',self.backend)

    def test_client_refuses_extra_fields_and_wrong_receipt_fence(self):
        from unittest.mock import patch
        c=self.claim();r=self.s.execute(c)
        driver=SocketDriver(self.root/'unused')
        for bad in ({**asdict(r),'token':'private'},asdict(replace(r,fence=2))):
            with patch.object(driver,'_call',return_value={'ok':True,'receipt':bad}):
                with self.assertRaises(Conflict): driver.execute(c)

    def test_disabled_native_backend_cannot_write_an_intent(self):
        self.s.backend=DisabledDriver()
        with self.assertRaises(CapabilityUnavailable): self.s.execute(self.claim())
        with self.s.connect() as con: self.assertEqual(con.execute('SELECT count(*) FROM journal').fetchone()[0],0)

    def test_ipc_parser_bounds_and_duplicate_fields(self):
        for data in (b'{"action":"check","action":"execute"}\n',b'{}\n{}\n',b'[]\n',b'x'*8192):
            a,b=socket.socketpair()
            with a,b:
                a.sendall(data)
                with self.assertRaises(Conflict): read_message(b)
        with self.assertRaises(Conflict): encode({'x':'a'*8192})

    @unittest.skipUnless(hasattr(socket,'SO_PEERCRED'),'Linux authenticated peer test')
    def test_linux_peer_denied_before_claim_and_errors_are_sanitized(self):
        a,b=socket.socketpair()
        with a,b:
            a.sendall(encode({'action':'execute','claim':asdict(self.claim())}))
            handle_connection(b,self.s,controller_uid=os.getuid()+1)
            self.assertEqual(read_message(a),{'ok':False,'error':'request_denied'})
        self.assertEqual(self.backend.calls,[])
        self.backend.fail=True
        a,b=socket.socketpair()
        with a,b:
            a.sendall(encode({'action':'execute','claim':asdict(self.claim())}))
            handle_connection(b,self.s,controller_uid=os.getuid())
            self.assertEqual(read_message(a),{'ok':False,'error':'outcome_uncertain'})

    @unittest.skipUnless(hasattr(socket,'SO_PEERCRED'),'Linux authenticated socket integration')
    def test_socket_driver_uses_authenticated_host_registry_and_receipt(self):
        path=self.root/'control.sock'
        server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.addCleanup(server.close);server.bind(str(path));path.chmod(0o600);server.listen(1)
        failures=[]
        def serve():
            try:
                for _ in range(3):
                    conn,_=server.accept()
                    with conn:
                        conn.settimeout(2);handle_connection(conn,self.s,controller_uid=os.getuid())
            except Exception as error: failures.append(type(error).__name__)
        thread=threading.Thread(target=serve,daemon=True);thread.start()
        driver=SocketDriver(path,server_uid=os.getuid(),timeout_seconds=2)
        driver.check('create');c=self.claim();r=driver.execute(c)
        self.assertEqual(r.fence,c.fence);self.assertEqual(driver.reconcile(c),r)
        thread.join(3);self.assertFalse(thread.is_alive());self.assertEqual(failures,[])
        self.assertEqual(len(self.backend.calls),1)
        path.chmod(0o666)
        with self.assertRaises(PermissionError): driver.execute(c)


if __name__=='__main__': unittest.main()
