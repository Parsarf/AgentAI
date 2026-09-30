from contextlib import contextmanager
from dataclasses import replace
import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from agentai_platform.adapters import CapabilityUnavailable, DisabledGateway, GatewayCapabilities
from agentai_platform.config import Config
from agentai_platform.security import NotFound, Principal
from agentai_platform.server import BoundedServer, Handler
from agentai_platform.store import Store
ROOT=Path(__file__).resolve().parents[1]
class FixtureIdentity:
    def verify(self,cookie): return {'fixture=a':Principal('a','actor-a','customer'),'fixture=b':Principal('b','actor-b','customer')}.get(cookie)
@contextmanager
def running(config,store,service='app',identity=None):
    server=BoundedServer(('127.0.0.1',0),Handler,config=config,store=store,service=service,identity=identity)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try: yield server.server_port
    finally: server.shutdown();server.server_close();thread.join(timeout=2)
def request(port,path,method='GET',headers=None,body=None):
    con=http.client.HTTPConnection('127.0.0.1',port,timeout=3)
    try:
        con.request(method,path,body=body,headers=headers or {})
        res=con.getresponse();return res.status,dict(res.getheaders()),json.loads(res.read())
    finally: con.close()
class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.config=replace(Config.load(ROOT/'config.example.json'),state_dir=self.base/'state')
        self.store=Store(self.config.state_dir/'platform.sqlite3');self.store.initialize()
        with self.store.connect() as con:
            for a in ['a','b']:
                con.execute('INSERT INTO accounts(id,status) VALUES (?,?)',(a,'active'))
                con.execute('INSERT INTO memberships VALUES (?,?,?,?)',(a,'actor-'+a,'customer','active'))
                con.execute('INSERT INTO projects(account_id,id,name) VALUES (?,?,?)',(a,'project-'+a,'Project '+a))
                con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES (?,?,1,'pending')",(a,'deploy-'+a))
                con.execute('INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES (?,?,?,?)',(a,'project-'+a,'conv-'+a,'deploy-'+a))
    def tearDown(self): self.tmp.cleanup()
    def test_missing_database_readiness_does_not_create_state(self):
        missing=self.base/"missing.sqlite3"
        self.assertFalse(Store(missing).ready())
        self.assertFalse(missing.exists())
    def test_migrations_repeat_and_readiness(self):
        self.store.initialize();self.assertTrue(self.store.ready())
        with self.store.connect() as con: self.assertEqual(con.execute('SELECT count(*) FROM schema_migrations').fetchone()[0],len(list((ROOT/'migrations').glob('*.sql'))))
    def test_changed_or_newer_migration_fails_closed(self):
        with self.store.connect() as con: con.execute("UPDATE schema_migrations SET checksum='changed'")
        self.assertFalse(self.store.ready())
        with self.assertRaises(ValueError): self.store.initialize()
        with self.store.connect() as con: con.execute("INSERT INTO schema_migrations(version,checksum) VALUES ('9999.sql','x')")
        with self.assertRaises(ValueError): self.store.initialize()
    def test_failed_migration_rolls_back_ddl(self):
        import agentai_platform.store as module
        migrations=self.base/'migrations';migrations.mkdir()
        (migrations/'0001.sql').write_text('CREATE TABLE partial(id TEXT);\nINSERT INTO missing VALUES (1);\n')
        new=Store(self.base/'bad-state'/'db.sqlite3')
        with patch.object(module,'MIGRATIONS',migrations):
            with self.assertRaises(sqlite3.OperationalError): new.initialize()
        with new.connect() as con: self.assertIsNone(con.execute("SELECT name FROM sqlite_master WHERE name='partial'").fetchone())
    def test_cross_account_and_cross_project_foreign_keys(self):
        with self.store.connect() as con:
            for sql in ["INSERT INTO conversations(account_id,project_id,id,deployment_id) VALUES ('a','project-b','bad','deploy-a')", "INSERT INTO tasks(account_id,project_id,conversation_id,id,state,budget_microusd) VALUES ('a','project-a','conv-b','bad','queued',0)"]:
                with self.assertRaises(sqlite3.IntegrityError): con.execute(sql)
            con.execute("INSERT INTO projects(account_id,id,name) VALUES ('a','other','Other')")
            with self.assertRaises(sqlite3.IntegrityError): con.execute("INSERT INTO tasks(account_id,project_id,conversation_id,id,state,budget_microusd) VALUES ('a','other','conv-a','bad','queued',0)")
    def test_scoped_repository_and_revocation(self):
        actor=Principal('a','actor-a','customer')
        self.assertEqual(self.store.list_projects(actor)[0]['id'],'project-a')
        with self.assertRaises(NotFound): self.store.get_project(actor,'project-b')
        with self.store.connect() as con: con.execute("UPDATE memberships SET status='revoked' WHERE account_id='a'")
        with self.assertRaises(NotFound): self.store.list_projects(actor)
    def test_audit_append_only(self):
        with self.store.connect() as con:
            con.execute("INSERT INTO audit_events(account_id,id,actor_id,object_id,action,outcome,request_id) VALUES ('a','audit','actor-a','x','read','completed','request')")
            for sql in ["UPDATE audit_events SET action='changed'","DELETE FROM audit_events"]:
                with self.assertRaises(sqlite3.IntegrityError): con.execute(sql)
    def test_private_health_and_default_identity_denial(self):
        with running(self.config,self.store) as port:
            self.assertEqual(request(port,'/healthz')[0],200)
            status,headers,body=request(port,'/readyz');self.assertEqual(status,200);self.assertFalse(body['customer_ready'])
            self.assertEqual(request(port,'/v1/projects',headers={'X-Account-ID':'a','Authorization':'Bearer synthetic-secret'})[0],401)
            self.assertIn('X-Request-ID',headers)
    def test_direct_http_cross_account_denial(self):
        with running(self.config,self.store,identity=FixtureIdentity()) as port:
            self.assertEqual(request(port,'/v1/projects/project-a',headers={'Cookie':'fixture=a'})[0],200)
            self.assertEqual(request(port,'/v1/projects/project-a',headers={'Cookie':'fixture=b'})[0],404)
            self.assertEqual(request(port,'/v1/projects/nonexistent',headers={'Cookie':'fixture=b'})[0],404)
            self.assertEqual(request(port,'/v1/projects?account_id=a',headers={'Cookie':'fixture=b'})[2]['items'][0]['id'],'project-b')
    def test_control_and_customer_mutations_disabled(self):
        with running(self.config,self.store,service='control') as port: self.assertEqual(request(port,'/v1/operations',method='POST',body='{}')[0],401)
        with running(self.config,self.store,identity=FixtureIdentity()) as port: self.assertEqual(request(port,'/v1/tasks',method='POST',body='{}',headers={'Cookie':'fixture=a'})[0],503)
    def test_host_origin_size_denials(self):
        with running(self.config,self.store) as port:
            self.assertEqual(request(port,'/healthz',headers={'Host':'evil.invalid'})[0],403)
            self.assertEqual(request(port,'/healthz',headers={'Origin':'https://evil.invalid'})[0],403)
            self.assertEqual(request(port,'/v1/tasks',method='POST',body='x'*5000)[0],413)
    def test_logs_exclude_body_headers_query(self):
        with running(self.config,self.store) as port, self.assertLogs('agentai',level='INFO') as captured:
            request(port,'/v1/tasks?token=synthetic-secret',method='POST',body='synthetic-secret',headers={'Authorization':'Bearer synthetic-secret'})
        self.assertNotIn('synthetic-secret',''.join(captured.output))
    def test_public_bind_or_feature_activation_rejected(self):
        source=json.loads((ROOT/'config.example.json').read_text())
        for change in [{'bind':'0.0.0.0'},{'features':{**source['features'],'provisioning':True}},{'max_connections':True}]:
            f=self.base/'config.json';f.write_text(json.dumps({**source,**change}))
            with self.assertRaises(ValueError): Config.load(f)
    def test_unverified_gateway_never_dispatches(self):
        with self.assertRaises(CapabilityUnavailable): DisabledGateway().send('c','t','o','message')
        with self.assertRaises(CapabilityUnavailable): GatewayCapabilities('2026.9.6',3,True,True,True,True,False).require('send')
if __name__=='__main__': unittest.main()
