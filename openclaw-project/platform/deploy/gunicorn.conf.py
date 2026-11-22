import os
bind='127.0.0.1:18800'
# The worker count comes from the unit (agentai-platform-app.service sets AGENTAI_APP_WORKERS beside the memory and CPU limits sized for it), so a release
# never starts more workers than its unit has room for. One worker served the whole web app one request at a time: the Inbox's first calls queued behind
# each other (2026-11-19). Sync workers share the SQLite file in WAL mode like every other process of the platform.
workers=max(1, min(8, int(os.environ.get('AGENTAI_APP_WORKERS') or 1)))
worker_class='sync'
threads=1
timeout=15
graceful_timeout=10
backlog=16
# 4094 only so that a provider's sign-in return fits (GET /v1/hub/link/callback?code=...: Microsoft's code for a work account alone can pass 2,000 characters).
# Every other route is still held to 2,048 by accounts/middleware.py.
limit_request_line=4094
limit_request_fields=32
limit_request_field_size=2048
max_requests=1000
max_requests_jitter=20
accesslog=None
errorlog='-'
# Only the loopback TLS proxy may set the trusted protocol header.
forwarded_allow_ips='127.0.0.1,::1'
