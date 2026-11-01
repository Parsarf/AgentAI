"""Real local UI→Django→connection store→SDK→fixture MCP→runtime relay test.

Run with platform/.venv/bin/python tests/mcp_ui_fixture.py; reads/writes only a
TemporaryDirectory. Never loads production credentials. The private HTTP
transport is injected in this test program, never enabled by an app setting.
"""
import datetime
import io
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import sys
import tempfile
import time
import uuid
from types import SimpleNamespace
from wsgiref.simple_server import make_server, WSGIServer, WSGIRequestHandler
from socketserver import ThreadingMixIn

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests.mcp_fixture import Fixture, URL


def main():
    with tempfile.TemporaryDirectory(prefix='lumina-mcp-ui-') as tmp:
        root=Path(tmp); state=root/'state';state.mkdir(mode=0o700)
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
        origin=f'https://localhost:{port}'
        os.environ.update(AGENTAI_STATE_DIR=str(state),AGENTAI_SESSION_SECRET=secrets.token_urlsafe(64),AGENTAI_PUBLIC_ORIGIN=origin,
                          AGENTAI_UI_BUNDLE_DIR=str(Path(__file__).resolve().parents[2]/'lumina'/'dist'),DJANGO_SETTINGS_MODULE='accounts.settings')
        import django;django.setup()
        from django.core.management import call_command
        from django.contrib.auth.models import User
        from accounts.services import token_for,consume
        from accounts.models import Identity
        from accounts import mcp_connections as views
        from django.core.wsgi import get_wsgi_application
        from agentai_platform.store import Store
        from agentai_platform.security import Principal
        from agentai_platform.chat import ChatService,FixedRoute
        from agentai_platform.chat_driver import ChatDriver,synthetic_gateway_factory
        from agentai_platform.gateway import SyntheticGateway
        from agentai_platform.request_queue import RequestQueue
        from agentai_platform.capacity import CapacityResult
        from agentai_platform.budget import BudgetLedger
        from agentai_platform.tool_relay import Relay
        from agentai_platform.mcp_connections.relay import RemoteTools
        from agentai_platform.lifecycle.tool_origin import inspect_origin
        call_command('migrate',verbosity=0,stdout=io.StringIO())
        email='mcp-fixture@example.invalid'; password='Lumina fixture password 2026!'
        call_command('onboard_trial',email=email,stdout=io.StringIO())
        user=User.objects.get(email=email);consume(token_for(user,'onboarding'),'onboarding',password,uuid.uuid4())
        account=Identity.objects.get(user=user).account_id
        store=Store(state/'platform.sqlite3');principal=Principal(account,str(user.pk),'customer')
        fixture=Fixture()
        original=views.service
        def service(store_=None):
            s=original(store_ or store);s.remote=fixture.remote();return s
        views.service=service
        with store.connect() as con:
            project=con.execute('SELECT id FROM projects WHERE account_id=?',(account,)).fetchone()[0]
            con.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES (?,'fixture-deployment',1,'ready')",(account,))
        queue=RequestQueue(store);ledger=BudgetLedger(store,service_limit_microusd=10**9);gateway=SyntheticGateway(polls=1000)
        chat=ChatService(store,queue=queue,ledger=ledger,pricer=FixedRoute(100000),execution=True)
        conversation=chat.create_conversation(principal,project)['id']
        sent=chat.send(principal,conversation_id=conversation,message='Fixture remote tool',key='mcp-fixture-request')
        claim=queue.claim(owner='mcp-fixture',capacity=CapacityResult(1,1,1,1,1,()))
        driver=ChatDriver(store,ledger=ledger,gateway_factory=synthetic_gateway_factory(gateway))
        driver._begin(claim,gateway,driver._admit(claim))
        with store.connect() as con:
            delivery=dict(con.execute('SELECT * FROM chat_deliveries WHERE account_id=? AND request_id=?',(account,sent['id'])).fetchone())
            native_session=con.execute('SELECT native_session_ref FROM conversations WHERE account_id=? AND id=?',(account,conversation)).fetchone()[0]
        proofdir=root/'tool-origins';proofdir.mkdir(mode=0o700)
        relay=Relay(SimpleNamespace(store=store),origin=lambda acct,name,args:inspect_origin(root,name,{k:v for k,v in args.items() if k!='_lumina_origin'},args.get('_lumina_origin')),remote=RemoteTools(service()))
        app=get_wsgi_application()
        def application(environ,start_response):
            if environ['PATH_INFO']=='/__fixture__/agent':
                data=json.loads(environ['wsgi.input'].read(int(environ.get('CONTENT_LENGTH') or 0)))
                name=data.get('name','lumina_mcp_discover');arguments=data.get('arguments',{})
                nonce=secrets.token_hex(16)
                proof={'version':2,'name':name,'arguments':arguments,'session_key':native_session,'run_id':delivery['native_run_id'] or delivery['idempotency_key'],
                       'call_id':uuid.uuid4().hex,'started_ms':int(time.time()*1000)}
                path=proofdir/(nonce+'.json');path.write_text(json.dumps(proof));path.chmod(0o600)
                result=relay.handle(account,{'jsonrpc':'2.0','id':'fixture','method':'tools/call','params':{'name':name,'arguments':{**arguments,'_lumina_origin':nonce}}})
                encoded=json.dumps(result).encode();start_response('200 OK',[('Content-Type','application/json'),('Content-Length',str(len(encoded)))]);return [encoded]
            return app(environ,start_response)
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')])
        now=datetime.datetime.now(datetime.timezone.utc)
        cert=x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),critical=False).sign(key,hashes.SHA256())
        certfile=root/'cert.pem';keyfile=root/'key.pem';certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM));keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));keyfile.chmod(0o600)
        class Server(ThreadingMixIn,WSGIServer): daemon_threads=True
        class Handler(WSGIRequestHandler):
            def log_message(self,*args): pass
            def get_environ(self):
                value=super().get_environ();value['HTTPS']='on';value['wsgi.url_scheme']='https';return value
        server=make_server('127.0.0.1',port,application,server_class=Server,handler_class=Handler)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(certfile,keyfile);server.socket=context.wrap_socket(server.socket,server_side=True)
        print(json.dumps({'ready':True,'origin':origin,'email':email,'password':password,'mcp_url':URL}),flush=True)
        try:server.serve_forever()
        except KeyboardInterrupt: pass
        finally:server.server_close();fixture.close()

if __name__=='__main__':main()
