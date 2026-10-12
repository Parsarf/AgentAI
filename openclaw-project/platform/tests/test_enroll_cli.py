from pathlib import Path
import os,sqlite3,tempfile,unittest
from agentai_platform.lifecycle.enroll_cli import build_binding,free_port
from agentai_platform.lifecycle.supervisor import HostSupervisor
from agentai_platform.lifecycle import profiles

class EnrollChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.d=Path(self.tmp.name)
        db=sqlite3.connect(self.d/'app.db')
        db.execute('CREATE TABLE lifecycle_cells(account_id TEXT,deployment_id TEXT,tenant_ref TEXT,profile_revision TEXT)')
        db.execute("INSERT INTO lifecycle_cells VALUES ('a',?,?,?)",('1'*32,'aa-'+'2'*32,'trial-measured-v1'))
        db.commit();db.close()
        self.sup=HostSupervisor(self.d/'sup',backend=None,owner_uid=os.geteuid())
    def test_binding_comes_from_app_ids_and_host_profile_only(self):
        b=build_binding(self.d/'app.db','a','ghcr.io/openclaw/openclaw@sha256:'+'c'*64,self.d/'bk',19101)
        self.assertEqual((b.deployment_id,b.tenant_ref),('1'*32,'aa-'+'2'*32))
        self.assertEqual((b.memory_bytes,b.cpu_millis,b.pid_limit,b.volume_bytes),(profiles.CELL_MEMORY,profiles.CELL_MILLIS,profiles.CELL_PIDS,profiles.VOLUME_BYTES))
        self.assertEqual(b.quarantine_port,19151)
        self.sup.enroll(b)
        self.assertEqual(free_port(self.sup),19102)
    def test_unknown_account_and_unpinned_image_are_refused(self):
        with self.assertRaises(SystemExit): build_binding(self.d/'app.db','zzz','ghcr.io/openclaw/openclaw@sha256:'+'c'*64,self.d/'bk',19101)
        with self.assertRaises(ValueError): build_binding(self.d/'app.db','a','ghcr.io/openclaw/openclaw:latest',self.d/'bk',19101)
if __name__=='__main__': unittest.main()
