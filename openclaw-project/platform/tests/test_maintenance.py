import io,json,os,tarfile,tempfile,unittest
from pathlib import Path
from agentai_platform.lifecycle.maintenance import (extract_archive,quarantine_ref,ArchiveRefused,HostIsolation)
from agentai_platform.lifecycle.netpolicy import NetPolicy

T='aa-'+'a1'*16;O='aa-'+'b2'*16

def make(path,members,tenant=T,manifest=True):
    with tarfile.open(path,'w:gz') as t:
        if manifest:
            body=json.dumps({'schemaVersion':1,'kind':'openclaw-fleet-cell-backup','tenant':tenant,'hostPort':19101}).encode()
            i=tarfile.TarInfo('manifest.json');i.size=len(body);t.addfile(i,io.BytesIO(body))
        for name,kind,data in members:
            i=tarfile.TarInfo(name)
            if kind=='file': i.size=len(data);t.addfile(i,io.BytesIO(data))
            elif kind=='dir': i.type=tarfile.DIRTYPE;t.addfile(i)
            elif kind=='sym': i.type=tarfile.SYMTYPE;i.linkname='/etc/passwd';t.addfile(i)

class ArchiveChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.d=Path(self.tmp.name)
        self.data=self.d/'data';self.auth=self.d/'auth';self.data.mkdir();self.auth.mkdir()
    def tearDown(self): self.tmp.cleanup()
    def extract(self,members,**kw):
        src=self.d/'in.tgz';make(src,members,**{k:v for k,v in kw.items() if k in ('tenant','manifest')})
        return extract_archive(src,self.data,self.auth,T,max_bytes=kw.get('max_bytes',10**6),uid=os.getuid(),gid=os.getgid())
    def test_extracts_data_and_auth_into_their_roots_only(self):
        self.extract([('data','dir',b''),('data/state','dir',b''),('data/state/db','file',b'D'),
                      ('data/canary.txt','file',b'canary-A'),('auth','dir',b''),('auth/key','file',b'K')])
        self.assertEqual((self.data/'canary.txt').read_bytes(),b'canary-A')
        self.assertEqual((self.data/'state'/'db').read_bytes(),b'D');self.assertEqual((self.auth/'key').read_bytes(),b'K')
        self.assertFalse(any(self.d.glob('*.tmp')))
    def test_unsafe_members_are_refused_before_anything_outside_is_written(self):
        for members in [[('../evil','file',b'x')],[('/etc/x','file',b'x')],[('other/x','file',b'x')],
                        [('data/link','sym',b'')],[('data/a\\b','file',b'x')]]:
            with self.assertRaises(ArchiveRefused,msg=str(members)): self.extract(members)
        self.assertFalse((self.d/'evil').exists());self.assertFalse((self.d.parent/'evil').exists())
    def test_wrong_tenant_missing_manifest_or_oversize_refused(self):
        with self.assertRaises(ArchiveRefused): self.extract([('data','dir',b'')],tenant=O)
        with self.assertRaises(ArchiveRefused): self.extract([('data','dir',b'')],manifest=False)
        with self.assertRaises(ArchiveRefused): self.extract([('data/x','file',b'x'*100)],max_bytes=10)
    def test_destinations_must_be_empty_and_are_never_overwritten(self):
        (self.data/'existing').write_text('keep')
        with self.assertRaises(ArchiveRefused): self.extract([('data/x','file',b'x')])
        self.assertEqual((self.data/'existing').read_text(),'keep')
        (self.data/'existing').unlink();(self.data/'lost+found').mkdir()
        self.extract([('data/x','file',b'x')])   # lost+found from mkfs is tolerated
    def test_fresh_cell_placeholder_is_replaced_only_when_asked(self):
        (self.data/'openclaw.json').write_text('{}')
        src=self.d/'in.tgz';make(src,[('data/x','file',b'x')])
        extract_archive(src,self.data,self.auth,T,max_bytes=10**6,uid=os.getuid(),gid=os.getgid(),replace_skeleton=True)
        self.assertFalse((self.data/'openclaw.json').exists());self.assertTrue((self.data/'x').exists())
    def test_symlinked_destination_is_refused(self):
        real=self.d/'real';real.mkdir();link=self.d/'link';link.symlink_to(real)
        src=self.d/'in.tgz';make(src,[('data/x','file',b'x')])
        with self.assertRaises(ArchiveRefused): extract_archive(src,link,self.auth,T,max_bytes=10**6,uid=os.getuid(),gid=os.getgid())
    def test_quarantine_slug_is_deterministic_per_tenant(self):
        self.assertEqual(quarantine_ref(T),quarantine_ref(T));self.assertNotEqual(quarantine_ref(T),quarantine_ref(O))
        with self.assertRaises(ValueError): quarantine_ref('x')

class IsolationChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.d=Path(self.tmp.name);self.calls=[]
        self.iso=HostIsolation(self.d/'q.json',self.d/'rules.nft',NetPolicy('10.78.0.0/16','10.77.0.1'),self.runner)
    def tearDown(self): self.tmp.cleanup()
    def runner(self,argv):
        self.calls.append(argv)
        if argv[:3]==['docker','network','inspect']: return 0,'10.78.5.0/24\n'
        return 0,''
    def test_quarantine_validates_then_loads_once_and_is_idempotent(self):
        self.iso.quarantine(T);self.iso.quarantine(T)
        nft=[c for c in self.calls if c[0]=='nft']
        self.assertEqual([c[1] for c in nft],['-c','-f'])
        self.assertIn('10.78.5.0/24',(self.d/'rules.nft').read_text())
        self.assertTrue(self.iso.is_quarantined(T))
    def test_release_removes_only_that_subnet(self):
        self.iso.quarantine(T);self.iso.release(T)
        self.assertNotIn('quarantined',(self.d/'rules.nft').read_text())
    def test_failed_validation_changes_nothing(self):
        def bad(argv):
            return (1,'') if argv[:2]==['nft','-c'] else self.runner(argv)
        iso=HostIsolation(self.d/'q2.json',self.d/'r2.nft',NetPolicy('10.78.0.0/16','10.77.0.1'),bad)
        with self.assertRaises(RuntimeError): iso.quarantine(T)
        self.assertFalse((self.d/'r2.nft').exists());self.assertFalse((self.d/'q2.json').exists())
if __name__=='__main__': unittest.main()
