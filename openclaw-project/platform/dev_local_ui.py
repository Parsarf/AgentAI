"""Local UI preview: loopback Gunicorn with TLS, disposable state and account.

For operator eyes only. Binds 127.0.0.1, keeps all state in a temporary
private directory, creates one synthetic customer, and exits cleanly on
SIGTERM/SIGINT. Never use as the product server or expose it.
"""
import os
import secrets
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
from pathlib import Path

PORT = int(os.environ.get('LOCAL_UI_PORT', '8765'))
ORIGIN = f'https://127.0.0.1:{PORT}'
EMAIL = 'local-ui@example.invalid'
PASSWORD = 'Local-UI-Preview-2026!'

root = tempfile.mkdtemp(prefix='agentai-local-ui-')
os.chmod(root, 0o700)
os.environ['AGENTAI_STATE_DIR'] = root
os.environ['AGENTAI_SESSION_SECRET'] = secrets.token_urlsafe(48)
os.environ['AGENTAI_PUBLIC_ORIGIN'] = ORIGIN
os.environ['DJANGO_SETTINGS_MODULE'] = 'accounts.settings'

import django
django.setup()
from django.core.management import call_command
from django.db import connection, connections

with open(os.devnull, 'w') as devnull:
    import contextlib
    with contextlib.redirect_stdout(devnull):
        call_command('bootstrap_accounts', verbosity=0)
from accounts.services import create_invite, consume
import uuid
with connection.cursor() as c:
    c.execute("INSERT INTO accounts(id,status) VALUES ('local-ui-preview','active')")
user, raw = create_invite(EMAIL, 'local-ui-preview', 'fixture', uuid.uuid4())
consume(raw, 'onboarding', PASSWORD, uuid.uuid4())
with connection.cursor() as c:
    c.execute('INSERT INTO projects(account_id,id,name) VALUES (%s,%s,%s)', ['local-ui-preview', 'local-ui-project', 'Preview project'])
    c.execute("INSERT INTO deployments(account_id,id,generation,state) VALUES ('local-ui-preview','local-ui-deployment',1,'stopped')")
connections.close_all()

base = Path(__file__).resolve().parent
cert = Path(root) / 'local-cert.pem'
key = Path(root) / 'local-key.pem'
subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-keyout', str(key), '-out', str(cert),
                '-days', '2', '-nodes', '-subj', '/CN=127.0.0.1'], check=True, capture_output=True)

with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    free = sock.getsockname()[1]
port = PORT if PORT != free else PORT + 1

def shutdown(signum, frame):
    proc.terminate()
    proc.wait(timeout=15)
    shutil.rmtree(root, ignore_errors=True)
    sys.exit(0)

import shutil
proc = subprocess.Popen([sys.executable, '-m', 'gunicorn', '-c', 'deploy/gunicorn.conf.py',
                         '--bind', f'127.0.0.1:{port}', '--certfile', str(cert), '--keyfile', str(key),
                         'accounts.wsgi:application'], cwd=base, start_new_session=True)
signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)

import time
import urllib.request
for _ in range(100):
    try:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        if urllib.request.urlopen(f'https://127.0.0.1:{port}/healthz', context=context, timeout=2).status == 200:
            break
    except Exception:
        if proc.poll() is not None:
            sys.exit('preview server failed to start')
    time.sleep(0.1)
else:
    sys.exit('preview server startup timed out')

print(f'AgentAI local UI preview: {ORIGIN}/account/')
print(f'Sign in: {EMAIL} / {PASSWORD}')
print(f'State: {root} (disposable). Stop with Ctrl-C or kill {proc.pid}.', flush=True)
proc.wait()
shutil.rmtree(root, ignore_errors=True)
