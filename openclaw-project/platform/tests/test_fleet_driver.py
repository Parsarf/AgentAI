"""Boundary tests for the native Fleet backend. No native cell is ever started.

The stub CLI exercises the driver's fixed-argv execution, custody validation,
drain kills, receipt schema gating and host headroom admission. These are
orchestration boundaries, not OS isolation or native acceptance (Phase 15).
"""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest

from agentai_platform.adapters import CapabilityUnavailable
from agentai_platform.capacity import CapacityResult
from agentai_platform.lifecycle.coordinator import Coordinator
from agentai_platform.lifecycle.fleet_driver import FleetCustody, FleetCliDriver, HeadroomAdmission
from agentai_platform.lifecycle.fleet_plan import FleetBinding
from agentai_platform.lifecycle.supervisor import HostSupervisor, OutcomeUncertain, SupervisorBusy
from agentai_platform.lifecycle.types import Claim, Conflict, Receipt
from agentai_platform.security import Principal
from agentai_platform.store import Store
from tests.lifecycle_fixture import FixtureDriver

FIELDS={'status':'str','applied':'bool','drained':'bool'}
def schema(states):
    return {'fields':FIELDS,'map':{'state':'status','applied':'applied','quiesced':'drained'},
            'state_values':states}
FULL_SCHEMAS={
    'create':schema({'running':[],'stopped':['created'],'absent':['gone']}),
    'start':schema({'running':['running'],'stopped':[],'absent':[]}),
    'stop':schema({'running':[],'stopped':['stopped'],'absent':[]}),
    'backup':schema({'running':[],'stopped':['stopped'],'absent':[]}),
    'delete':schema({'running':[],'stopped':[],'absent':['gone']}),
}
STUB='''import json,os,subprocess,sys,time
mode=os.environ.get('AA_MODE','ok')
args=sys.argv[1:]
calls=os.environ.get('AA_CALLS')
if calls:
    with open(calls,'a') as h: h.write(json.dumps(args[:6])+'\\n')
def emit(body,code=0):
    sys.stdout.write(body if isinstance(body,str) else json.dumps(body))
    sys.stdout.flush();sys.exit(code)
if args[:2]==['fleet','list']:
    if os.environ.get('AA_REGISTRY_MODE')=='present':
        emit({'cells':[{'id':os.environ['AA_TENANT']}]})
    emit({'cells':[]})
raw=args[1] if len(args)>1 else ''
kind={'rm':'delete'}.get(raw,raw)
if mode=='sleep':
    child=subprocess.Popen(['sleep','30'])
    with open(os.environ['AA_CHILD'],'w') as h: h.write(str(child.pid))
    time.sleep(30);emit({'status':'stopped','applied':True,'drained':True})
if mode=='envdump':
    with open(os.environ['AA_DUMP'],'w') as h: json.dump(dict(os.environ),h)
if mode=='bad_json': emit('not-json')
if mode=='dup_field': emit('{"status":"stopped","status":"stopped","applied":true,"drained":true}')
if mode=='big': emit('x'*(2*1024*1024))
if mode=='nonzero': emit({'status':'stopped','applied':True,'drained':True},3)
status={'create':'created','start':'running','stop':'stopped','backup':'stopped','delete':'gone'}[kind]
if mode=='reject':
    if kind=='stop': emit({'status':'running','applied':False,'drained':False})
    emit({'status':'gone' if kind in ('create','delete') else 'stopped','applied':False,'drained':True})
if kind=='backup' and os.environ.get('AA_ARCHIVE','1')!='0':
    out=args[args.index('--out')+1]
    os.makedirs(os.path.dirname(out),exist_ok=True)
    body=b'\\x1f\\x8b' if os.environ.get('AA_ARCHIVE_HEAD','gzip')=='gzip' else b'ZZ'
    with open(out,'wb') as h:
        h.write(body+b'a'*int(os.environ.get('AA_ARCHIVE_BYTES','64')))
emit({'status':status,'applied':True,'drained':kind!='start'})
'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def manifest_dict(root,*,schemas=FULL_SCHEMAS,mode='ok',registry='absent',timeout=5,
                  output_limit=65536,reserve=0,env_extra=None):
    import shutil
    bin_dir=root/'bin';bin_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
    node=bin_dir/'node';shutil.copyfile(sys.executable,node);node.chmod(0o755)
    entry=bin_dir/'entry';entry.write_text(STUB);entry.chmod(0o755)
    env={'PATH':'/usr/bin:/bin','AA_MODE':mode,'AA_REGISTRY_MODE':registry,
         'AA_TENANT':'aa-'+'1'*32,'AA_CHILD':str(bin_dir/'child.pid'),
         'AA_DUMP':str(bin_dir/'env.json'),'AA_CALLS':str(bin_dir/'calls.jsonl')}
    if env_extra: env.update(env_extra)
    return {'schema_version':1,'cli':{'node':str(node),'entry':str(entry),
        'node_sha256':sha(node),'entry_sha256':sha(entry)},'env':env,'cwd':str(root),
        'timeout_seconds':timeout,'output_limit_bytes':output_limit,
        'headroom_reserve_bytes':reserve,'schemas':schemas}


def binding(root,account='a',i=1):
    return FleetBinding(account,'1'*32,'aa-'+'1'*32,'trial-v1',
        'ghcr.io/openclaw/openclaw@sha256:'+'a'*64,19100+i,512*1024**2,500,64,
        128*1024**2,root/'backups'/account)


class DriverChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        os.environ['SENTINEL_DO_NOT_INHERIT']='1';self.addCleanup(os.environ.pop,'SENTINEL_DO_NOT_INHERIT')

    def custody(self,**kw):
        return FleetCustody(manifest_dict(self.root/'custody-build',**kw))

    def claim(self,kind='create',b=None,fence=1,seq='02'):
        b=b or binding(self.root)
        return Claim(b.account_id,b.deployment_id,b.tenant_ref,seq*16,kind,1,'trial-v1',None,fence,'controller')

    def calls(self):
        path=self.root/'custody-build'/'bin'/'calls.jsonl'
        if not path.exists(): return []
        return [json.loads(l)[1] for l in path.read_text().splitlines()]

    def test_missing_schema_refuses_without_intent_or_effect(self):
        driver=FleetCliDriver(self.custody(schemas={}))
        for kind in ('create','start','upgrade'):
            with self.assertRaises(CapabilityUnavailable): driver.check(kind)
        supervisor=HostSupervisor(self.root/'custody',driver)
        supervisor.enroll(binding(self.root))
        with self.assertRaises(CapabilityUnavailable): supervisor.execute(self.claim())
        with supervisor.connect() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM journal').fetchone()[0],0)
        self.assertEqual(self.calls(),[])

    def test_manifest_validation(self):
        good=manifest_dict(self.root/'m1')
        with self.assertRaises(ValueError): FleetCustody({**good,'schema_version':2})
        with self.assertRaises(ValueError): FleetCustody({**good,'timeout_seconds':4})
        with self.assertRaises(ValueError): FleetCustody({**good,'output_limit_bytes':1024**3})
        with self.assertRaises(ValueError): FleetCustody({**good,'schemas':{'upgrade':FULL_SCHEMAS['start']}})
        cli=dict(good['cli']);cli['node_sha256']='0'*64
        with self.assertRaises(ValueError): FleetCustody({**good,'cli':cli})
        env=dict(good['env']);del env['PATH']
        with self.assertRaises(ValueError): FleetCustody({**good,'env':env})
        with self.assertRaises(ValueError): FleetCustody({**good,'env':{**good['env'],'lower':'x'}})
        node=Path(good['cli']['node']);link=self.root/'m1'/'bin'/'link'
        link.symlink_to(node)
        linked=dict(good);linked['cli']={**cli,'node_sha256':sha(node),'node':str(link)}
        with self.assertRaises(ValueError): FleetCustody(linked)
        broken=json.loads(json.dumps(good))
        broken['schemas']={'start':{'fields':{'status':'str'},'map':{'state':'status','applied':'status'},
                                    'state_values':{'running':[],'stopped':['x'],'absent':[]}}}
        with self.assertRaises(ValueError): FleetCustody(broken)

    def test_create_completion_through_supervisor(self):
        driver=FleetCliDriver(self.custody())
        supervisor=HostSupervisor(self.root/'custody',driver)
        b=binding(self.root);supervisor.enroll(b)
        receipt=supervisor.execute(self.claim(b=b))
        self.assertEqual((receipt.state,receipt.applied,receipt.quiesced,receipt.fence),
                         ('stopped',True,True,1))
        with supervisor.connect() as con:
            self.assertEqual(con.execute('SELECT state FROM bindings').fetchone()[0],'stopped')
        self.assertEqual(self.calls()[0],'create')
        replay=HostSupervisor(self.root/'custody',driver).execute(self.claim(b=b))
        self.assertEqual(replay,receipt);self.assertEqual(len(self.calls()),1)

    def test_timeout_kills_whole_group_and_holds_uncertain(self):
        driver=FleetCliDriver(self.custody(mode='sleep',timeout=5))
        supervisor=HostSupervisor(self.root/'custody',driver)
        supervisor.enroll(binding(self.root))
        with self.assertRaises(OutcomeUncertain): supervisor.execute(self.claim())
        pid=int((self.root/'custody-build'/'bin'/'child.pid').read_text())
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            try: os.kill(pid,0)
            except ProcessLookupError: break
            time.sleep(0.05)
        else: self.fail('stub grandchild survived the group kill')
        with self.assertRaises(OutcomeUncertain): supervisor.execute(self.claim())
        with supervisor.connect() as con:
            self.assertEqual(con.execute("SELECT status FROM journal").fetchone()[0],'uncertain')

    def test_unverifiable_outputs_stay_uncertain(self):
        for mode in ('bad_json','dup_field','big','nonzero'):
            with self.subTest(mode=mode):
                root=Path(self.tmp.name)/f'u-{mode}'
                driver=FleetCliDriver(FleetCustody(manifest_dict(root/'custody-build',mode=mode)))
                supervisor=HostSupervisor(root/'custody',driver)
                supervisor.enroll(binding(root))
                with self.assertRaises(OutcomeUncertain): supervisor.execute(self.claim(b=binding(root)))
                with supervisor.connect() as con:
                    self.assertEqual(con.execute("SELECT status FROM journal").fetchone()[0],'uncertain')

    def test_definitive_rejection_is_completed_and_not_applied(self):
        driver=FleetCliDriver(self.custody(mode='reject'))
        supervisor=HostSupervisor(self.root/'custody',driver)
        supervisor.enroll(binding(self.root))
        receipt=supervisor.execute(self.claim())
        self.assertFalse(receipt.applied);self.assertTrue(receipt.quiesced)
        with supervisor.connect() as con:
            row=con.execute('SELECT status,receipt FROM journal').fetchone()
            self.assertEqual(row['status'],'completed')
            self.assertEqual(con.execute('SELECT state FROM bindings').fetchone()[0],'absent')
        retry=supervisor.execute(replace(self.claim(),fence=2,operation_id='f'*32))
        self.assertFalse(retry.applied);self.assertEqual(len(self.calls()),2)

    def test_backup_archive_verification(self):
        b=binding(self.root);(self.root/'backups'/'a').mkdir(mode=0o700,parents=True)
        receipt=FleetCliDriver(self.custody(mode='backup_file')).execute(b,self.claim('backup',b=b))
        self.assertEqual(receipt.backup_ref,receipt.operation_id)
        driver=FleetCliDriver(FleetCustody(manifest_dict(self.root/'m2',mode='ok',
                                                         env_extra={'AA_ARCHIVE':'0'})))
        with self.assertRaises(OutcomeUncertain): driver.execute(b,self.claim('backup',b=b,seq='03'))
        symlink=b.backup_root/('0'*32+'.tgz')
        symlink.symlink_to(self.root/'elsewhere')
        with self.assertRaises(OutcomeUncertain): driver.execute(b,self.claim('backup',b=b,seq='00'))
        symlink.unlink()
        big=FleetCustody(manifest_dict(self.root/'m3',mode='backup_file',env_extra={'AA_ARCHIVE_BYTES':'2048'}))
        small=replace(b,archive_limit_bytes=1024)
        with self.assertRaises(OutcomeUncertain): FleetCliDriver(big).execute(small,self.claim('backup',b=small,seq='04'))
        plain=FleetCustody(manifest_dict(self.root/'m4',mode='backup_file',
                                         env_extra={'AA_ARCHIVE_HEAD':'plain'}))
        with self.assertRaises(OutcomeUncertain): FleetCliDriver(plain).execute(b,self.claim('backup',b=b,seq='05'))

    def test_delete_and_reconcile_use_absence_probe_only(self):
        present=FleetCliDriver(self.custody(mode='ok',registry='present'))
        b=binding(self.root)
        with self.assertRaises(OutcomeUncertain): present.execute(b,self.claim('delete',b=b,seq='0a'))
        self.assertIsNone(present.reconcile(b,self.claim('stop',b=b)))
        self.assertIsNone(present.reconcile(b,self.claim('create',b=b)))
        absent=FleetCliDriver(self.custody(mode='ok',registry='absent'))
        receipt=absent.execute(b,self.claim('delete',b=b,seq='0b'))
        self.assertEqual((receipt.state,receipt.applied),('absent',True))
        retry=absent.reconcile(b,self.claim(b=b))
        self.assertEqual((retry.state,retry.applied,retry.quiesced),('absent',False,True))

    def test_environment_is_exactly_custody(self):
        env={'PATH':'/usr/bin:/bin','AA_SENTINELED':'from-custody'}
        custody=FleetCustody(manifest_dict(self.root/'m5',mode='envdump',env_extra=env))
        FleetCliDriver(custody).execute(binding(self.root),self.claim())
        dumped=json.loads((self.root/'m5'/'bin'/'env.json').read_text())
        # Nothing from the operator environment may leak in; the executor's own
        # CPython runtime injects locale/CF keys at startup on both platforms.
        injected={'LC_CTYPE','__CF_USER_TEXT_ENCODING'}
        self.assertTrue(set(dumped)-set(custody.env)<=injected, sorted(set(dumped)-set(custody.env)))
        for key,value in custody.env.items():
            self.assertEqual(dumped.get(key),value)
        self.assertNotIn('SENTINEL_DO_NOT_INHERIT',dumped)
        self.assertEqual(dumped['AA_SENTINELED'],'from-custody')

    def test_headroom_admission_gates_runnable_kinds_at_dispatch(self):
        calls=[]
        def low():
            calls.append('read');return 100*1024**2
        admission=HeadroomAdmission(low,64*1024**2)
        driver=FleetCliDriver(self.custody())
        supervisor=HostSupervisor(self.root/'custody',driver,admission=admission)
        b=binding(self.root);supervisor.enroll(b)
        supervisor.execute(self.claim(b=b))
        with self.assertRaises(SupervisorBusy): supervisor.execute(self.claim('start',b=b,seq='03'))
        with supervisor.connect() as con:
            rows=[(json.loads(r['claim'])['kind'],r['status'])
                  for r in con.execute('SELECT claim,status FROM journal').fetchall()]
        self.assertEqual(rows,[('create','completed')])
        self.assertNotIn('start',self.calls())
        supervisor.admission=HeadroomAdmission(lambda:2*1024**3,64*1024**2)
        supervisor.execute(self.claim('start',b=b,seq='03'))
        self.assertIn('start',self.calls())
        with supervisor.connect() as con:
            rows=[(json.loads(r['claim'])['kind'],r['status'])
                  for r in con.execute('SELECT claim,status FROM journal').fetchall()]
        self.assertIn(('start','completed'),rows)

    def test_admission_never_runs_for_non_runnable_kinds(self):
        def forbidden():
            raise AssertionError('admission must not consult the host for create')
        supervisor=HostSupervisor(self.root/'custody',FleetCliDriver(self.custody()),
                                  admission=HeadroomAdmission(forbidden,0))
        supervisor.enroll(binding(self.root))
        supervisor.execute(self.claim())


class BusyDriver:
    def __init__(self,inner): self.inner=inner
    def check(self,kind): self.inner.check(kind)
    def execute(self,claim): raise SupervisorBusy('host headroom exhausted')
    def reconcile(self,claim): return self.inner.reconcile(claim)


class CoordinatorRescindChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.store=Store(self.root/'state'/'db.sqlite3');self.store.initialize()
        self.engine=Coordinator(self.store,clock=lambda:2000000000)
        self.driver=FixtureDriver(self.root/'fixture')
        with self.store.connect() as con:
            con.execute('CREATE TABLE auth_user(id INTEGER PRIMARY KEY,is_active INTEGER)')
            con.execute('CREATE TABLE accounts_identity(user_id INTEGER,role TEXT,verified INTEGER)')
            con.execute('CREATE TABLE accounts_operatorgrant(user_id INTEGER,account_id TEXT,action TEXT,expires_at TEXT)')
            con.execute("INSERT INTO auth_user VALUES (1,1)")
            con.execute("INSERT INTO accounts_identity VALUES (1,'operator',1)")
            con.execute("INSERT INTO accounts(id,status) VALUES ('a','active')")
            con.execute("INSERT INTO memberships VALUES ('a','customer-a','customer','active')")
            for kind in ('create','start'):
                con.execute("INSERT INTO accounts_operatorgrant VALUES (1,'a',?,datetime(2000003600,'unixepoch'))",
                            ('lifecycle_'+kind,))

    def create(self):
        op=self.engine.request(Principal('a','1','operator'),kind='create',key='c1')
        self.assertTrue(self.engine.run(self.driver,'a',op['id'],capacity=CapacityResult(1,1,1,1,1,())))
        return op

    def test_busy_dispatch_rescinds_to_pending_without_uncertainty(self):
        self.create()
        op=self.engine.request(Principal('a','1','operator'),kind='start',key='s1',generation=1)
        with self.assertRaises(SupervisorBusy):
            self.engine.run(BusyDriver(self.driver),'a',op['id'],capacity=CapacityResult(1,1,1,1,1,()))
        with self.store.connect() as con:
            row=dict(con.execute('''SELECT o.state,d.error_code,d.lease_owner,d.lease_until
                FROM operations o JOIN lifecycle_details d ON d.account_id=o.account_id
                AND d.operation_id=o.id WHERE o.id=?''',(op['id'],)).fetchone())
            self.assertEqual(row['state'],'pending');self.assertEqual(row['error_code'],'host_headroom')
            self.assertIsNone(row['lease_owner']);self.assertIsNone(row['lease_until'])
            cell=con.execute("SELECT observed_state FROM lifecycle_cells WHERE account_id='a'").fetchone()[0]
            self.assertEqual(cell,'stopped')
            slot=con.execute('SELECT account_id,state FROM lifecycle_slot WHERE id=1').fetchone()
            self.assertEqual(tuple(slot),('a','reserved'))
        self.assertTrue(self.engine.run(self.driver,'a',op['id'],capacity=CapacityResult(1,1,1,1,1,())))
        with self.store.connect() as con:
            self.assertEqual(con.execute("SELECT observed_state FROM lifecycle_cells WHERE account_id='a'").fetchone()[0],'running')


if __name__=='__main__':unittest.main()
