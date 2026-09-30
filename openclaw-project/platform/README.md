# AgentAI private customer platform

Separate customer application/control metadata. OpenClaw remains the runtime.
The application now uses Django accounts and Gunicorn; the earlier stdlib
server is retained solely for private foundation/control fixtures. No production
identity fallback, developer header or enabled customer execution path.

Python3.12–3.14; exact pure-Python dependencies and hashes in requirements.lock.
Private dedicated SQLite WAL database; no owner/proxy state reuse. One small-beta
control node only; horizontal writer scaling requires a measured DB migration.
Read [account design](accounts/README.md), [deployment](deploy/README.md),
[API matrix](API_MATRIX.md), architecture and threat model before activation.

From this directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
# Supply private AGENTAI_SESSION_SECRET, AGENTAI_STATE_DIR and HTTPS public origin.
.venv/bin/python manage.py bootstrap_accounts
.venv/bin/gunicorn -c deploy/gunicorn.conf.py accounts.wsgi:application
# Control remains hard-disabled and private, using config.json.
python3 -m agentai_platform.server --config config.example.json --service control
```

Do not use `runserver` as the product server or publish the preview. Explicit
bootstrap creates private state, adopts the unchanged checksummed foundation
migration, then applies Django migrations. WSGI refuses missing/newer schema.
Readiness reports identity readiness separately and **customer_ready:false**.
Session/TLS/mail setup, provisioning and budget admission gate activation.

Cheap targeted checks (disposable synthetic identities, no model/mail charges):

```sh
.venv/bin/python manage.py test accounts
PYTHONPATH=. .venv/bin/python tests/check_account_concurrency.py
PYTHONPATH=. .venv/bin/python tests/check_account_http.py
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -p test_foundation.py
```

The HTTP checks need permission to bind loopback in sandboxed environments.
Test scripts generate temporary secrets privately and remove process/state.
Full browser/provider/security acceptance remains Phase15. Source/evidence
contains no real customer identities, cookies, codes or credentials.
