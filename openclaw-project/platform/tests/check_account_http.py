"""Real loopback Gunicorn HTTP with two disposable accounts. No external effects."""
import contextlib
import http.client
from http.cookies import SimpleCookie
import io
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
with tempfile.TemporaryDirectory(prefix='agentai-account-http-') as root:
    os.environ['AGENTAI_STATE_DIR']=root
    os.environ['AGENTAI_SESSION_SECRET']=secrets.token_urlsafe(48)
    os.environ['DJANGO_SETTINGS_MODULE']='accounts.settings'
    import django
    django.setup()
    from django.core.management import call_command
    from django.db import connection,connections
    from accounts.services import create_invite,consume
    with contextlib.redirect_stdout(io.StringIO()): call_command('bootstrap_accounts',verbosity=0)
    for account in ['http-a','http-b']:
        with connection.cursor() as c:
            c.execute("INSERT INTO accounts(id,status) VALUES (%s,'active')",[account])
            c.execute('INSERT INTO projects(account_id,id,name) VALUES (%s,%s,%s)',[account,account,'Synthetic project'])
        user,raw=create_invite(account+'@example.invalid',account,'fixture',uuid.uuid4())
        consume(raw,'onboarding','CANARY-synthetic-http-password-193!',uuid.uuid4())
    connections.close_all()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base=Path(__file__).resolve().parents[1]
    with open(Path(root)/'process.log','w+') as log:
        process=subprocess.Popen([sys.executable,'-m','gunicorn','-c','deploy/gunicorn.conf.py','--bind',f'127.0.0.1:{port}','accounts.wsgi:application'],cwd=base,stdout=log,stderr=log,start_new_session=True)
        cookies={}
        def request(path,method='GET',data=None,jar=None,csrf=None,origin='https://localhost'):
            conn=http.client.HTTPConnection('127.0.0.1',port,timeout=3)
            headers={'Host':'localhost','X-Forwarded-Proto':'https','Origin':origin}
            if jar: headers['Cookie']='; '.join(k+'='+v for k,v in jar.items())
            if csrf: headers['X-CSRFToken']=csrf
            if data is not None: headers['Content-Type']='application/json'
            conn.request(method,path,json.dumps(data) if data is not None else None,headers)
            result=conn.getresponse(); body=result.read()
            if jar is not None:
                for key,value in result.getheaders():
                    if key.lower()=='set-cookie':
                        parsed=SimpleCookie();parsed.load(value)
                        for name,cookie in parsed.items(): jar[name]=cookie.value
            status=result.status;conn.close();return status,body
        try:
            for _ in range(100):
                try:
                    if request('/healthz')[0]==200: break
                except (OSError,http.client.HTTPException): pass
                if process.poll() is not None: raise AssertionError('HTTP process failed to start')
                time.sleep(.05)
            else: raise AssertionError('HTTP process startup timed out')
            status,body=request('/readyz'); assert status==200 and json.loads(body)['identity_ready'] and not json.loads(body)['customer_ready']
            assert request('/v1/projects')[0]==401
            for a in ['http-a','http-b']:
                jar={};cookies[a]=jar
                status,body=request('/account/login/',jar=jar);assert status==200
                csrf=re.search(rb'name="csrfmiddlewaretoken" value="([^"]+)"',body).group(1).decode()
                assert request('/auth/login','POST',{'email':a+'@example.invalid','password':'CANARY-synthetic-http-password-193!'},jar,csrf)[0]==200
                assert json.loads(request('/v1/projects',jar=jar)[1])['projects'][0]['id']==a
                other='http-b' if a=='http-a' else 'http-a'
                assert request('/v1/projects/'+other,jar=jar)[0]==404
                assert request('/v1/projects?account_id='+other,jar=jar)[0]==400
                assert request('/auth/logout','POST',{},jar)[0]==403
            log.flush();log.seek(0);output=log.read()
            for secret in [os.environ['AGENTAI_SESSION_SECRET'],'CANARY-synthetic-http-password-193!']+[v for j in cookies.values() for v in j.values() if v]:
                assert secret not in output,'Secret leaked into process logs'
        finally:
            if process.poll() is None:
                os.killpg(process.pid,signal.SIGTERM)
                try: process.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL);process.wait()
    print('PASS: real loopback Gunicorn startup/readiness; two authenticated accounts; direct cross-account denial; CSRF/routing guards; no secret logs; process/state cleanup')
