"""Disposable file-backed SQLite concurrency check; no network/mail/native calls."""
import concurrent.futures
import contextlib
import io
import os
from pathlib import Path
import secrets
import tempfile
import threading
import uuid
with tempfile.TemporaryDirectory(prefix='agentai-account-concurrency-') as root:
    os.environ['AGENTAI_STATE_DIR']=root
    os.environ['AGENTAI_SESSION_SECRET']=secrets.token_urlsafe(48)
    os.environ['DJANGO_SETTINGS_MODULE']='accounts.settings'
    import django
    django.setup()
    from django.core.management import call_command
    from django.db import connection,connections
    from accounts.services import create_invite,consume,Denied
    from accounts.models import ActionToken,Audit
    from agentai_platform.store import Store
    with contextlib.redirect_stdout(io.StringIO()): call_command('bootstrap_accounts',verbosity=0)
    with connection.cursor() as c: c.execute("INSERT INTO accounts(id,status) VALUES ('race','active')")
    user,raw=create_invite('race@example.invalid','race','fixture',uuid.uuid4())
    barrier=threading.Barrier(2)
    def attempt():
        barrier.wait()
        try:
            consume(raw,'onboarding','synthetic-atomic-password-429!',uuid.uuid4())
            return 'consumed'
        except Denied: return 'denied'
        finally: connections.close_all()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:attempt(),range(2)))
    assert sorted(results)==['consumed','denied'],results
    assert Audit.objects.filter(action='identity.onboarding',outcome='completed').count()==1
    assert Store(Path(root)/'platform.sqlite3').ready()
    with contextlib.redirect_stdout(io.StringIO()): call_command('bootstrap_accounts',verbosity=0)
    assert Store(Path(root)/'platform.sqlite3').ready()
    from django.core import checks
    diagnostics=checks.run_checks(include_deployment_checks=True)
    assert {d.id for d in diagnostics} <= {'security.W021'},[d.id for d in diagnostics]
    with contextlib.redirect_stdout(io.StringIO()):
        call_command('makemigrations',check=True,dry_run=True,verbosity=0)
    connections.close_all()
    print('PASS: concurrent single-use token consume; one committed mutation/audit; repeat migrations; private state/readiness; migration drift/deployment checks (only intentional HSTS preload W021)')
