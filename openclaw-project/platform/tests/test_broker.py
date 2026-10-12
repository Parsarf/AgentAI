import json
from pathlib import Path
import tempfile
import unittest
from agentai_platform.lifecycle.broker import (WorkerBroker,StageProfile,WorkerBinding,build_argv,
    BrokerBusy,BrokerRefused,StageUncertain)

IMG='sha256:'+'a'*64
A='aa-'+'a1'*16;B='aa-'+'b2'*16
RUN='c0'*16

def profile(**kw):
    base=dict(name='coder',image=IMG,command=('/usr/bin/stage','coder'),memory_bytes=512*1024**2,cpus=1,
              pids=128,timeout_seconds=30,network='none',project='rw')
    base.update(kw);return StageProfile(**base)

class BrokerChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.binding=WorkerBinding(A,21001,1000,self.root/'cells'/A)
        self.calls=[]
    def tearDown(self): self.tmp.cleanup()
    def broker(self,runner=None,**kw):
        def default(argv,timeout):
            self.calls.append(argv)
            if argv[1]=='ps': return 0,''
            return 0,'ok'
        return WorkerBroker(self.root/'broker',{'coder':profile(),'reviewer':profile(name='reviewer',project='ro'),
            'browser':profile(name='browser',project='none',network='egress'),
            'modeler':profile(name='modeler',needs_model_key=True)},run=runner or default,**kw)

    def test_envelope_flags(self):
        argv=build_argv(profile(),self.binding,RUN)
        text=' '.join(argv)
        for flag in ['--runtime runsc','--network none','--read-only','--cap-drop ALL','no-new-privileges',
                     '--memory-swap 536870912','--pids-limit 128','--user 21001:1000']:
            self.assertIn(flag,text)
        self.assertNotIn('docker.sock',text);self.assertNotIn('--privileged',text);self.assertNotIn('--env',text)
        self.assertNotIn('-e ',text);self.assertNotIn('--volume',text)
        self.assertEqual(argv[-2:],['/usr/bin/stage','coder'])
    def test_mounts_are_exactly_this_tenants_dirs(self):
        text=' '.join(build_argv(profile(),self.binding,RUN))
        self.assertIn(f'src={self.root}/cells/{A}/workers/project,dst=/work/project,readonly=false',text)
        self.assertNotIn(B,text)
        ro=' '.join(build_argv(profile(project='ro'),self.binding,RUN))
        self.assertIn('dst=/work/project,readonly',ro);self.assertNotIn('readonly=false',ro)
        none=' '.join(build_argv(profile(project='none'),self.binding,RUN))
        self.assertNotIn('/work/project',none)
    def test_network_and_secret_access_follow_the_profile_only(self):
        self.assertIn('--network bridge',' '.join(build_argv(profile(network='egress'),self.binding,RUN)))
        with self.assertRaises(BrokerRefused): build_argv(profile(needs_model_key=True),self.binding,RUN)
        with self.assertRaises(BrokerRefused): build_argv(profile(),self.binding,RUN,model_key_file='/x')
        keyed=' '.join(build_argv(profile(needs_model_key=True),self.binding,RUN,model_key_file='/keys/a'))
        self.assertIn('dst=/run/secrets/model-key,readonly',keyed)
    def test_customer_text_cannot_reach_argv(self):
        b=self.broker();b.prepare(self.binding,{'task':'"; rm -rf / #','$(evil)':'`x`'})
        b.execute(self.binding,'coder',RUN)
        flat=json.dumps(self.calls)
        self.assertNotIn('rm -rf',flat);self.assertNotIn('evil',flat)
        self.assertIn('rm -rf',(self.binding.dir('job')/'job.json').read_text())  # only in the data file
    def test_unknown_stage_and_bad_run_id_are_refused(self):
        b=self.broker()
        with self.assertRaises(BrokerRefused): b.execute(self.binding,'shell',RUN)
        with self.assertRaises(BrokerRefused): b.execute(self.binding,'coder','../x')
    def test_replay_returns_stored_result_without_rerunning(self):
        b=self.broker();first=b.execute(self.binding,'coder',RUN);n=len(self.calls)
        again=b.execute(self.binding,'coder',RUN)
        self.assertEqual(len(self.calls),n);self.assertTrue(again['replayed']);self.assertEqual(first['exit_code'],again['exit_code'])
        with self.assertRaises(BrokerRefused): b.execute(self.binding,'reviewer',RUN)
    def test_timeout_is_killed_and_drained(self):
        def runner(argv,timeout):
            self.calls.append(argv)
            if argv[1]=='run': return None,''
            if argv[1]=='ps': return 0,''
            return 0,''
        b=self.broker(runner);result=b.execute(self.binding,'coder',RUN)
        self.assertEqual(result['exit_code'],-9)
        self.assertTrue(any(c[:3]==['docker','rm','-f'] for c in self.calls))
    def test_undrained_container_leaves_stage_uncertain_and_blocks_next(self):
        def runner(argv,timeout):
            if argv[1]=='ps': return 0,'deadbeef\n'
            return 0,'ok'
        b=self.broker(runner)
        with self.assertRaises(StageUncertain): b.execute(self.binding,'coder',RUN)
        with self.assertRaises(StageUncertain): b.execute(self.binding,'coder','d1'*16)
    def test_second_concurrent_stage_is_busy(self):
        import fcntl,os
        b=self.broker();fd=os.open(b.lock,os.O_RDWR);fcntl.flock(fd,fcntl.LOCK_EX)
        try:
            with self.assertRaises(BrokerBusy): b.execute(self.binding,'coder',RUN)
        finally: os.close(fd)
    def test_admission_denial_runs_nothing(self):
        def deny(profile): raise BrokerBusy('headroom')
        b=self.broker(admission=deny)
        with self.assertRaises(BrokerBusy): b.execute(self.binding,'coder',RUN)
        self.assertFalse([c for c in self.calls if c[1]=='run'])
    def test_bad_profiles_and_bindings_fail_closed(self):
        for kw in [dict(image='latest'),dict(command=()),dict(network='host'),dict(project='all'),dict(memory_bytes=1),dict(cpus=9)]:
            with self.assertRaises(ValueError): profile(**kw)
        for args in [(A,100,1000,self.root),(A,21001,0,self.root),('x',21001,1000,self.root),(A,21001,1000,Path('rel'))]:
            with self.assertRaises(ValueError): WorkerBinding(*args)
if __name__=='__main__': unittest.main()
