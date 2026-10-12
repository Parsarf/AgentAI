from pathlib import Path
import tempfile
import unittest
from agentai_platform.lifecycle.volumes import VolumeManager, VolumeSpec, VolumeError

T='aa-'+'a1'*16

class FakeHost:
    """Records fixed argv and simulates truncate/mkfs/mount state."""
    def __init__(self, root, fail=None):
        self.calls=[];self.mounted=set();self.fail=fail;self.root=root
    def __call__(self, argv):
        self.calls.append(argv)
        if self.fail and argv[0]==self.fail: return 1,''
        if argv[0]=='truncate':
            with open(argv[3],'wb') as handle: handle.truncate(int(argv[2]))
        if argv[0]=='mount': self.mounted.add(argv[-1])
        if argv[0]=='umount': self.mounted.discard(argv[-1])
        if argv[0]=='findmnt':
            return (0,argv[-1]+'\n') if argv[-1] in self.mounted else (1,'')
        return 0,''

class VolumeChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.host=FakeHost(self.root)
        self.vm=VolumeManager(self.root/'img',self.root/'cells',run=self.host)
        self.spec=VolumeSpec(T,128*1024**2)
    def tearDown(self): self.tmp.cleanup()
    def test_prepare_formats_and_mounts_once_and_is_idempotent(self):
        self.vm.prepare(self.spec);self.vm.prepare(self.spec)
        kinds=[c[0] for c in self.host.calls]
        self.assertEqual(kinds.count('truncate'),1);self.assertEqual(kinds.count('mkfs.ext4'),1)
        self.assertEqual(kinds.count('mount'),1)
        mount=[c for c in self.host.calls if c[0]=='mount'][0]
        self.assertIn('nodev',mount[2]);self.assertIn('nosuid',mount[2])
    def test_resize_is_refused(self):
        self.vm.prepare(self.spec)
        with self.assertRaises(VolumeError): self.vm.prepare(VolumeSpec(T,256*1024**2))
    def test_failed_step_surfaces_and_does_not_mount(self):
        self.host.fail='mkfs.ext4'
        with self.assertRaises(VolumeError): self.vm.prepare(self.spec)
        self.assertFalse(self.host.mounted)
    def test_purge_requires_unmount_and_removes_only_that_tenant(self):
        other='aa-'+'b2'*16
        self.vm.prepare(self.spec);self.vm.prepare(VolumeSpec(other,128*1024**2))
        with self.assertRaises(VolumeError): self.vm.purge(T)
        self.vm.release(T);self.vm.purge(T)
        self.assertFalse(self.vm.image(T).exists());self.assertTrue(self.vm.image(other).exists())
    def test_inputs_are_validated(self):
        for bad in [dict(tenant='../x',size_bytes=128*1024**2),dict(tenant=T,size_bytes=1),
                    dict(tenant=T,size_bytes=True),dict(tenant=T,size_bytes=10**15)]:
            with self.assertRaises(ValueError): VolumeSpec(**bad)
        with self.assertRaises(ValueError): self.vm.image('aa-short')
        with self.assertRaises(ValueError): VolumeManager('relative','/abs')
if __name__=='__main__': unittest.main()
