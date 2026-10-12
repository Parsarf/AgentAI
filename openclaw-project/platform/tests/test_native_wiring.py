import json,os,shutil,sys,tempfile,unittest,hashlib
from pathlib import Path
from agentai_platform.lifecycle.native_wiring import build_native_backend,http_health
from agentai_platform.lifecycle.fleet_driver import FleetCliDriver,HeadroomAdmission

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

class WiringChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.r=Path(self.tmp.name)
        b=self.r/'bin';b.mkdir();n=b/'node';shutil.copyfile(sys.executable,n);n.chmod(0o755)
        e=b/'entry';e.write_text('#!/bin/sh\n');e.chmod(0o755)
        (self.r/'custody.json').write_text(json.dumps({'schema_version':2,
            'cli':{'node':str(n),'entry':str(e),'node_sha256':sha(n),'entry_sha256':sha(e)},
            'env':{'PATH':'/usr/bin:/bin','DOCKER_HOST':'unix:///run/agentai-cells/docker.sock'},'cwd':str(self.r),
            'timeout_seconds':30,'output_limit_bytes':65536,'headroom_reserve_bytes':1024,
            'list_states':{'running':['running'],'stopped':['created','exited']},'verified':['create','start']}))
        self.w={'fleet_custody':str(self.r/'custody.json'),'secrets_dir':str(self.r/'sec'),'volume_images':str(self.r/'img'),
                'cell_state_root':str(self.r/'cells'),'firewall_state':str(self.r/'q.json'),'firewall_rules':str(self.r/'rules.nft'),
                'cell_pool':'10.78.0.0/16','bridge_gateway':'10.77.0.1','model_proxy_port':None}
    def write(self,w): p=self.r/'wiring.json';p.write_text(json.dumps(w));return p
    def test_builds_the_full_native_backend_with_independent_admission(self):
        driver,admission=build_native_backend(self.write(self.w))
        self.assertIsInstance(driver,FleetCliDriver);self.assertIsInstance(admission,HeadroomAdmission)
        self.assertIsNotNone(driver.secrets);self.assertIsNotNone(driver.volumes)
        self.assertIsNotNone(driver.isolation);self.assertIsNotNone(driver.health)
    def test_unknown_keys_relative_paths_and_bad_policy_fail_closed(self):
        for change in [dict(extra=1),dict(secrets_dir='relative'),dict(cell_pool='8.8.0.0/16')]:
            w=dict(self.w);w.update(change)
            with self.assertRaises(ValueError): build_native_backend(self.write(w))
        w=dict(self.w);del w['fleet_custody']
        with self.assertRaises(ValueError): build_native_backend(self.write(w))
    def test_isolation_docker_calls_target_the_cell_engine_explicitly(self):
        from unittest.mock import patch
        driver, _ = build_native_backend(self.write(self.w))
        seen = []
        with patch('agentai_platform.lifecycle.native_wiring.default_run', lambda argv, env=None: seen.append((argv, env)) or (0, '10.78.9.0/24\n')):
            driver.isolation.subnet_of('aa-' + 'a' * 32)
        self.assertEqual(seen[0][1], {'DOCKER_HOST': 'unix:///run/agentai-cells/docker.sock'})
    def test_health_probe_requires_http_200_within_the_bound(self):
        class R:
            def __init__(s,st): s.status=st
            def __enter__(s): return s
            def __exit__(s,*a): return False
        self.assertTrue(http_health(1,timeout=2,interval=0,opener=lambda *a,**k:R(200)))
        self.assertFalse(http_health(1,timeout=0.05,interval=0.01,opener=lambda *a,**k:R(503)))
        def boom(*a,**k): raise OSError('refused')
        self.assertFalse(http_health(1,timeout=0.05,interval=0.01,opener=boom))
if __name__=='__main__': unittest.main()
