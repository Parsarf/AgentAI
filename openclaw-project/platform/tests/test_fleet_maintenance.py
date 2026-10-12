"""Driver paths for token/volume custody, pinned upgrade+rollback, quarantined restore and purge.

The stub CLI keeps a small registry file and mirrors behaviors observed live on
2026-10-11 (restore refuses a foreign tenant's archive; backup needs a stopped
cell; list is the state source). These are orchestration boundaries, not native
isolation acceptance (Phase 15).
"""
import hashlib,io,json,os,shutil,sys,tarfile,tempfile,unittest
from dataclasses import replace
from pathlib import Path
from agentai_platform.lifecycle.fleet_driver import FleetCustody,FleetCliDriver
from agentai_platform.lifecycle.fleet_plan import FleetBinding
from agentai_platform.lifecycle.maintenance import quarantine_ref
from agentai_platform.lifecycle.secrets_custody import SecretStore,ProviderKeys
from agentai_platform.lifecycle.supervisor import HostSupervisor,OutcomeUncertain
from agentai_platform.lifecycle.types import Claim
from agentai_platform.lifecycle.volumes import VolumeManager
from agentai_platform.adapters import CapabilityUnavailable

T='aa-'+'1'*32
OLD='ghcr.io/openclaw/openclaw@sha256:'+'a'*64
NEW='ghcr.io/openclaw/openclaw@sha256:'+'b'*64
STUB='''import json,os,sys,tarfile,io
args=sys.argv[1:];reg=os.environ['AA_REG']
state=json.load(open(reg)) if os.path.exists(reg) else {'cells':{},'log':[]}
def save():
    json.dump(state,open(reg,'w'))
def emit(body='',code=0):
    sys.stdout.write(body if isinstance(body,str) else json.dumps(body));save();sys.exit(code)
state['log'].append(args[1:])
cmd=args[1];cells=state['cells']
opt=lambda n:args[args.index(n)+1] if n in args else None
if cmd=='list':
    emit({'cells':[{'tenant':t,'state':c['state'],'port':c['port'],'image':c['image'],'created':'2026-10-11T00:00:00.000Z'} for t,c in cells.items()]})
t=args[2] if len(args)>2 else None
if cmd=='create':
    cells[t]={'state':'created','port':int(opt('--port')),'image':opt('--image'),'token':opt('--gateway-token')}
    emit({'tenant':t,'port':int(opt('--port')),'token':'shown-once'})
if cmd in ('start','stop'):
    if os.environ.get('AA_FAIL')==cmd: emit('no',3)
    cells[t]['state']='running' if cmd=='start' else 'exited';emit('ok')
if cmd=='rm': cells.pop(t,None);emit('removed')
if cmd=='backup':
    if cells[t]['state']=='running': emit('running',2)
    out=opt('--out');os.makedirs(os.path.dirname(out),exist_ok=True)
    buf=io.BytesIO()
    with tarfile.open(fileobj=buf,mode='w:gz') as z:
        body=json.dumps({'schemaVersion':1,'kind':'openclaw-fleet-cell-backup','tenant':t}).encode()
        i=tarfile.TarInfo('manifest.json');i.size=len(body);z.addfile(i,io.BytesIO(body))
        d=tarfile.TarInfo('data');d.type=tarfile.DIRTYPE;z.addfile(d)
    open(out,'wb').write(buf.getvalue());emit({'tenant':t,'archivePath':out})
if cmd=='upgrade':
    mode=os.environ.get('AA_UPGRADE','ok')
    if mode=='fail' and opt('--image')==os.environ.get('AA_NEW'): emit('refused',3)
    if mode=='failall': emit('refused',3)
    cells[t]['image']=opt('--image');cells[t]['state']='running';emit('upgraded')
if cmd=='restore':
    with tarfile.open(opt('--from')) as z: m=json.load(z.extractfile('manifest.json'))
    if m['tenant']!=t: emit('Backup archive belongs to another tenant',2)
    if os.environ.get('AA_RESTORE')=='fail': emit('bad',3)
    cells[t]['restored']=True;emit({'ok':True})
emit('unknown',9)
'''
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

class Kit(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        b=self.root/'bin';b.mkdir();node=b/'node';shutil.copyfile(sys.executable,node);node.chmod(0o755)
        entry=b/'entry';entry.write_text(STUB);entry.chmod(0o755)
        self.reg=self.root/'reg.json'
        self.env={'PATH':'/usr/bin:/bin','AA_REG':str(self.reg),'AA_NEW':NEW}
        self.healthy=[True];self.health_calls=[]
        self.vol_calls=[];self.iso_calls=[]
        class Iso:
            def quarantine(s,t): kit.iso_calls.append(('quarantine',t))
            def release(s,t): kit.iso_calls.append(('release',t))
        kit=self
        self.secrets=SecretStore(self.root/'secrets')
        def vrun(argv):
            self.vol_calls.append(argv)
            if argv[0]=='findmnt': return (0,argv[-1]+'\n') if any(c[0]=='mount' and c[-1]==argv[-1] for c in self.vol_calls) and not any(c[0]=='umount' and c[-1]==argv[-1] for c in self.vol_calls) else (1,'')
            if argv[0]=='truncate': Path(argv[3]).write_bytes(b'')
            return 0,''
        self.volumes=VolumeManager(self.root/'img',self.root/'cells',run=vrun)
        self.iso=Iso()
    def driver(self,**kw):
        env=dict(self.env);env.update(kw.pop('env',{}))
        manifest={'schema_version':2,'cli':{'node':str(self.root/'bin'/'node'),'entry':str(self.root/'bin'/'entry'),
            'node_sha256':sha(self.root/'bin'/'node'),'entry_sha256':sha(self.root/'bin'/'entry')},'env':env,'cwd':str(self.root),
            'timeout_seconds':10,'output_limit_bytes':65536,'headroom_reserve_bytes':0,
            'list_states':{'running':['running'],'stopped':['created','exited']},
            'verified':['create','start','stop','backup','delete','upgrade','restore']}
        def health(port): self.health_calls.append(port);return self.healthy.pop(0) if len(self.healthy)>1 else self.healthy[0]
        return FleetCliDriver(FleetCustody(manifest),secrets=self.secrets,volumes=self.volumes,isolation=self.iso,health=health)
    def binding(self,**kw):
        base=dict(account_id='a',deployment_id='1'*32,tenant_ref=T,profile_revision='trial-v1',image=OLD,port=19101,
            memory_bytes=512*1024**2,cpu_millis=500,pid_limit=64,archive_limit_bytes=128*1024**2,
            backup_root=self.root/'backups',upgrade_image=NEW,quarantine_port=19151,volume_bytes=128*1024**2)
        base.update(kw);return FleetBinding(**base)
    def claim(self,kind,seq,backup_ref=None,fence=1):
        return Claim('a','1'*32,T,seq*16,kind,1,'trial-v1',backup_ref,fence,'controller')
    def registry(self): return json.loads(self.reg.read_text())

class MaintenanceChecks(Kit):
    def test_create_prepares_volume_and_passes_the_host_held_token_only(self):
        d=self.driver();b=self.binding()
        d.execute(b,self.claim('create','01'))
        cell=self.registry()['cells'][T]
        self.assertEqual(cell['token'],self.secrets.gateway_token(T))
        self.assertTrue(any(c[0]=='mkfs.ext4' for c in self.vol_calls))
        mount=[c for c in self.vol_calls if c[0]=='mount'][0]
        self.assertTrue(mount[-1].endswith(T))
    def test_upgrade_success_promotes_the_staged_image_in_custody(self):
        d=self.driver();b=self.binding();sup=HostSupervisor(self.root/'custody',d,owner_uid=os.geteuid())
        sup.enroll(b)
        for k,s in [('create','01'),('backup','02')]:
            sup.execute(self.claim(k,s))
        r=sup.execute(self.claim('upgrade','03'))
        self.assertTrue(r.applied);self.assertEqual(self.registry()['cells'][T]['image'],NEW)
        with sup.connect() as con:
            spec=json.loads(con.execute('SELECT spec FROM bindings').fetchone()[0])
        self.assertEqual(spec['image'],NEW);self.assertIsNone(spec['upgrade_image'])
    def test_unhealthy_upgrade_rolls_back_and_reports_no_effect(self):
        d=self.driver();b=self.binding();d.execute(b,self.claim('create','01'))
        self.healthy=[False,True]
        r=d.execute(b,self.claim('upgrade','03'))
        self.assertFalse(r.applied);self.assertEqual(r.state,'running')
        self.assertEqual(self.registry()['cells'][T]['image'],OLD)   # rolled back to the recorded image
    def test_failed_upgrade_command_rolls_back_too(self):
        d=self.driver(env={'AA_UPGRADE':'fail'});b=self.binding();d.execute(b,self.claim('create','01'))
        r=d.execute(b,self.claim('upgrade','03'))
        self.assertFalse(r.applied);self.assertEqual(self.registry()['cells'][T]['image'],OLD)
    def test_unproven_rollback_is_uncertain_not_success(self):
        d=self.driver(env={'AA_UPGRADE':'failall'});b=self.binding();d.execute(b,self.claim('create','01'))
        with self.assertRaises(OutcomeUncertain): d.execute(b,self.claim('upgrade','03'))
    def test_upgrade_without_a_staged_image_is_refused(self):
        d=self.driver();b=self.binding(upgrade_image=None);d.execute(b,self.claim('create','01'))
        with self.assertRaises(CapabilityUnavailable): d.execute(b,self.claim('upgrade','03'))

    def backed_up(self,d,b):
        d.execute(b,self.claim('create','01'));d.execute(b,self.claim('backup','02'))
        return '02'*16
    def test_quarantined_restore_is_isolated_before_it_runs_and_leaves_production_alone(self):
        d=self.driver();b=self.binding();ref=self.backed_up(d,b)
        q=quarantine_ref(T)
        r=d.execute(b,self.claim('restore','04',backup_ref=ref))
        self.assertTrue(r.applied);self.assertEqual(r.state,'stopped')
        log=[c[0:2] for c in self.registry()['log']]
        self.assertIn(['create',q],log);self.assertNotIn('restore',[c[0] for c in log])  # host extractor, not native restore
        self.assertTrue((self.root/'cells'/q).is_dir())
        self.assertLess(self.iso_calls.index(('quarantine',q)),0+len(self.iso_calls))
        self.assertEqual(self.iso_calls[0],('quarantine',q))
        cells=self.registry()['cells']
        self.assertEqual(cells[q]['state'],'exited')
        self.assertEqual(cells[q]['port'],19151);self.assertNotEqual(cells[q]['token'],self.secrets.gateway_token(T))
        self.assertEqual(cells[T]['state'],'created')           # production untouched
        self.assertFalse(list((self.root/'backups').glob('q-*.tgz')))  # staged copy removed
    def test_restore_refuses_when_a_quarantine_already_exists(self):
        d=self.driver();b=self.binding();ref=self.backed_up(d,b)
        d.execute(b,self.claim('restore','04',backup_ref=ref))
        with self.assertRaises(OutcomeUncertain): d.execute(b,self.claim('restore','05',backup_ref=ref))
    def test_corrupt_archive_is_uncertain_and_leaves_no_staging(self):
        d=self.driver();b=self.binding();ref=self.backed_up(d,b)
        (self.root/'backups'/f'{ref}.tgz').write_bytes(b'\x1f\x8b'+b'junk')
        with self.assertRaises(OutcomeUncertain): d.execute(b,self.claim('restore','04',backup_ref=ref))
        self.assertFalse(list((self.root/'backups').glob('q-*.tgz')))
    def test_unhealthy_restored_cell_is_uncertain(self):
        d=self.driver();b=self.binding();ref=self.backed_up(d,b);self.healthy=[False]
        with self.assertRaises(OutcomeUncertain): d.execute(b,self.claim('restore','04',backup_ref=ref))
    def test_restore_needs_full_host_custody(self):
        d=self.driver();d.volumes=None;b=self.binding();ref=self.backed_up(self.driver(),b)
        with self.assertRaises(CapabilityUnavailable): d.execute(b,self.claim('restore','04',backup_ref=ref))
    def test_discard_removes_only_the_quarantine(self):
        d=self.driver();b=self.binding();ref=self.backed_up(d,b);q=quarantine_ref(T)
        d.execute(b,self.claim('restore','04',backup_ref=ref));d.discard_quarantine(b)
        cells=self.registry()['cells']
        self.assertNotIn(q,cells);self.assertIn(T,cells)
        self.assertFalse((self.secrets.root/q).exists());self.assertIn(('release',q),self.iso_calls)
        self.assertTrue((self.secrets.root/T).exists())
    def test_purge_revokes_then_removes_after_delete_and_refuses_while_registered(self):
        calls=[]
        keys=ProviderKeys(lambda m,p,body:(calls.append(p) or (200,{'key':'sk-'+'k'*30})),self.secrets)
        d=self.driver();b=self.binding();d.execute(b,self.claim('create','01'))
        keys.issue(T,'a',max_budget_usd=25,duration_days=30,models=['m'])
        with self.assertRaises(OutcomeUncertain): d.purge(b,provider_keys=keys)
        d.execute(b,self.claim('delete','06'))
        self.assertTrue(self.volumes.image(T).exists())          # delete keeps data for retention
        d.purge(b,provider_keys=keys)
        self.assertEqual(calls[-1],'/key/delete')
        self.assertFalse(self.volumes.image(T).exists());self.assertFalse((self.secrets.root/T).exists())
if __name__=='__main__': unittest.main()
