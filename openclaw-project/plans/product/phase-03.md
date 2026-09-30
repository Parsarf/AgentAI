# Product Phase 03 — customer accounts, recovery, roles and audit

Account build: **READY**. Targeted account boundary gate: **PASS**. Customer
activation: **BLOCKED** by actual TLS/mail setup, isolated provisioning (Phase4),
all-route budget admission (Phase5) and acceptance. RETENTION-CHAT overall build:
**PARTIAL**, dependent native/file/index/restore adapters remain explicitly tracked.
Full Phase15 security/browser/provider/restore acceptance: **NOT_RUN**.

## Bounded outcome / requirements

ACCOUNT-01/02 and RETENTION-AUDIT implemented in `platform/accounts/`; 90-day
product chat projection expiry/tombstones prepare RETENTION-CHAT without claiming
native deletion/export/confirmed erasure. Use maintained Django identity/session/
CSRF, confirmed django-otp MFA and Gunicorn; preserve owner runtime/config/data.
App + control do not load owner Gateway/provider/Telegram/SSH/Docker credentials.
Scope ends here; no Phase4 lifecycle driver, customer node or billing execution.

Dependencies: existing checked foundation migration and dedicated app metadata;
private random session secret; HTTPS reverse proxy; SMTP sender/provider for real
email; verified tenant and budget prerequisites for task activation. Local budget:
zero paid model/provider/task calls. Identity/mail/node operating totals remain
unknown until provider/node selection; owner $2/day/$25/month caps unchanged.

## Delivered

- Hashed password authentication, invite-only verified onboarding, generic queued
  recovery, logout/all-device revoke,12-hour session expiry and login/MFA rotation.
  Secure/HttpOnly/Strict cookies, CSRF/origin/Host/body guards and contract rate
  limits. No bearer identity header or customer account switching.
- Atomic hashed256-bit,15-minute, purpose/epoch-bound single-use recovery/onboarding
  tokens. Concurrent file-backed SQLite consumption proves one winner. Password/
  verification/epoch/audit commit as one local transaction.
- Customer binding + active account/membership on each request. Composite Phase2
  ownership constraints preserved; related server deployment mappings stay private.
  Cross-account/missing IDs same404. Existing task/stream/file objects assert
  ownership before reporting capability-disabled; all execution remains off.
- Explicit customer/operator/service identities. Optional account-admin excluded.
  One-hour account/action-specific operator grants, confirmed TOTP, throttling/
  replay denial; no superuser bypass/content/impersonation/export privilege.
  Host role changes/suspension/membership revocation invalidate sessions/streams.
- Append-only audit actor/account/object/action/request/operation/native-op/time/
  outcomes; local pending/completed atomic, external mail pending→completed/
  uncertain. Audit failure denies effects, including completed-audit failure
  after login (response middleware cannot recreate rolled-back session).
- Safe account forms/HTML; verified, verification-pending, deployment-pending and
  disabled task/billing states. Recovery queues IDs/purpose only; mail worker
  generates codes in memory. No code/password/cookie/customer text in logs.
- Restricted retention maintenance180-day audit/mail metadata; token/rate/session
  expiry;90-day chat projection tombstones. Native refs preserved for actual
  erasure reconciliation. Host custody can alter storage, not tamper-proof audit.
- Exact official wheel SHA256 lock, backward foundation adoption/Django integrity
  migrations, fail-closed WSGI schema startup, private deployment/env examples,
  source/API/threat/role/runbook/rollback/evidence records.

Evidence: [20260930T003526Z](../../evidence/product/phase-03/20260930T003526Z/manifest.json).

## Checks and failures

25 focused account checks PASS,14 unchanged foundation checks PASS, disposable
file-backed concurrency/migration/deployment checks PASS and real loopback
Gunicorn two-account direct HTTP/startup/log/cleanup smoke PASS. Test cases live
in `platform/accounts/tests.py` and `platform/tests/check_account_*.py`.
Sanitized manifest records exact commands, source hashes and final observations.
No full browser/real SMTP/native/provider/load/paid/customer acceptance ran.

During implementation: test helper initially collided with Django TestCase.client;
renamed it. Unique email index initially preceded later auth table replacement;
fixed explicit final-auth-migration dependency. Form fixture initially used
multipart instead of browser form encoding; corrected fixture. Readiness accepted
a Django test DB string where Store expected Path; normalized Store. Audit error
initially cleared an existing cookie; restored prior session after rollback and
added a post-login completion-failure assertion. Retained failure summaries in
evidence; final actual checks pass. No production record changed in any attempt.

Deployment checklist warning W021 is intentional: HSTS preload submission awaits
approved public domain/edge. Added maintained clickjacking middleware to resolve
W002. No missing migrations are silenced; drift check uses disposable state.

## Remaining gates / rollback / next

- SMTP/domain/test inbox and live invitations not authorized/configured; delivery
  default-disabled. No real customer/operator was created or mail sent.
- No permanent app service/public ingress was deployed. Local HTTP process and
  temporary state cleaned. Actual server Django RAM/TLS/SMTP must be verified
  before beta; previous Phase2 server smoke is not reused as Django-server proof.
- RETENTION-CHAT native history/export/confirmed deletion≤7days needs Phase6;
  artifacts/index/restore handling needs8/10/14, acceptance15. No missing adapter
  is mislabeled as merely a deferred test. Audit retention scheduler is prepared,
  not installed; production activation needs operational monitoring14.
- Operator enrollment/recovery and all public browser/MFA/mail workflows await
  Phase15 acceptance; no independent security review claimed.
- Rollback: stop only new app/worker; prior source pointer only with compatible
  schema. Otherwise restore private consistent pre-change DB to an isolated root,
  reconcile epochs/tombstones/access and force reauthentication before cutover.
  Never restore owner/proxy/native records. Local disposable cleanup completed.

Next implementation phase: **4 — isolated customer agent lifecycle**, only when
requested. Stop after this authorized phase.
