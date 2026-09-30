# Customer account layer — Phase 3

Private application built with pinned Django 5.2.17 authentication, password
validation/hashers, database sessions, CSRF and django-otp 1.7.3 TOTP. Gunicorn
26.2.0 replaces the foundation preview for the application; the control service
remains disabled. No Gateway, provider, Telegram, SSH or Docker credentials are
loaded by this application. No new runtime/agent loop.

## Identity and authorization

- Invitation-only. Verified onboarding requires the emailed code and a new
  validated password. A pending account cannot sign in. Account creation is a
  host-only audited command; invitation requires host custody or an operator's
  explicit account-scoped grant and confirmed MFA.
- Customer identities have one internal account binding. No account switching
  or optional account-admin role is offered yet. Membership, active account,
  verified identity and current session epoch are checked on every request.
  Revocation, suspension, role changes and password recovery invalidate access
  without relying on the UI. Each future stream must repeat this check at frame
  delivery/reconnect; no stream is enabled now.
- Operator has no customer browsing/project/export/impersonation privilege.
  Only invite, revoke, suspend and minimal audit reads exist, scoped to a named
  account with a one-hour host-issued grant; MFA is mandatory on each operator
  route. Django staff/superuser flags provide no bypass; Django admin is absent.
  Service identities cannot use password/browser sessions; control credentials
  and fixed operation scopes belong to Phase 4.
- Client tenant/session/agent headers and routing parameters are rejected.
  Composite account/project/task foreign keys remain the Phase 2 authority.
  Customer DTOs omit native session references, secret bindings and storage paths.
  Future task/stream/artifact endpoints prove ownership before reporting disabled.
  Memory/export/schedule/integration/cost/control capabilities stay unavailable.
- Cookies use `__Host-` names, Secure, HttpOnly, SameSite=Strict, path `/` and no
  domain. Sessions expire after 12 hours and rotate on every sign-in and MFA.
  Logout deletes the session; sign-out-all increments the identity epoch.
  Django's password/session hash invalidates old sessions after recovery.
- All POST routes use Django CSRF and same HTTPS origin. No GET has user effects.
  Bodies ≤8KiB, no file uploads. Rate defaults match the contract: 60 reads/min,
  10 mutations/min per identity+IP; shared sign-in/recovery ceiling 5/15min per
  email+IP. Additional global IP and email delivery limits bound abuse.
  Counts are private salted hashes, expire and are cleaned by maintenance.
- TLS terminates at a loopback-only trusted proxy which overwrites protocol and
  validated client-IP headers. Do not expose Gunicorn directly or trust arbitrary
  X-Forwarded-For. Default settings require a strong private session secret and
  direct private state (0700 directory,0600 database). WSGI startup refuses
  missing/unknown migrations and invalid foundation checksums.

## Recovery and delivery

Recovery is generic202 for known/unknown/ineligible addresses. It queues only
eligible customer IDs/purpose; SMTP is outside the request to avoid delivery
latency revealing account existence. Codes are generated in worker memory,
stored only as SHA256 hashes, 256-bit random, purpose-bound, epoch-bound,
15-minute expiry and single-use. SQLite IMMEDIATE transactions serialize consume
with password/verification/epoch/audit writes. Issuing a new code invalidates the
old purpose code; consuming invalidates all outstanding codes for the identity.
Codes are pasted into a form, never put into request URLs or cookies.

SMTP is disabled by default; no console/file backend writes codes to logs. A
host may configure a TLS SMTP provider and sender privately. The bounded mail
worker sends at most10 queued instructions once. Crash during delivery leaves
`running`; timeout/unknown delivery leaves `uncertain`. Neither is retried
implicitly. Reconcile or issue a fresh customer request; never manufacture a
completed receipt. SMTP/domain/delivery and actual onboarding remain activation
gates, not tests claimed from synthetic fixtures. Operator recovery uses host
custody to enroll a separate MFA identity; customer recovery cannot reset an
operator's MFA. No automatic MFA bypass or shared fallback key.

## Audit, retention and access

Append-only application audit rows capture actor, optional account, object,
action, request UUID, operation UUID, optional native operation and timestamp/
outcome. Local mutation + pending/completed audit commit atomically. A rollback
has no effect; a failed login also restores its prior session store, preventing
response middleware from saving rolled-back authentication. Email crosses an
external boundary: commit pending before send, then completed/uncertain receipt.
Logs contain only generated request ID/status; no URLs/bodies/cookies/emails/
exceptions/raw reasoning. Native operation IDs remain null until native adapters.

Restricted host maintenance expires sessions, codes and rate records; purges
minimal audit/mail metadata after180days. Only its transactional retention path
lifts delete guards then reinstalls them; HTTP cannot purge/edit audit. SQLite
and the app process share trusted metadata custody: this is **not** tamper-proof
against host administrators or compromised application code. Encrypted off-host
backups/independent integrity monitoring remain Phase14.

90-day chat event projection expiry creates scoped tombstones. Private native
routing refs remain available for later native erasure reconciliation. Native
history deletion, scoped export, confirmed account erasure≤7days, artifacts,
indexes and restore tombstone replay still require Phases6/8/10/14. No affected
chat/file/customer execution is activated here. RETENTION-CHAT remains PARTIAL.

## Primary sources verified for this implementation

- [Django supported versions](https://www.djangoproject.com/download/)
- [Django authentication](https://docs.djangoproject.com/en/5.2/topics/auth/default/)
- [Django sessions](https://docs.djangoproject.com/en/5.2/topics/http/sessions/)
- [Django CSRF](https://docs.djangoproject.com/en/5.2/howto/csrf/)
- [Django deployment](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/)
- [django-otp verification](https://django-otp-official.readthedocs.io/en/stable/overview.html)
- [Gunicorn releases](https://gunicorn.org/2026-news/)

Exact downloaded wheel versions and SHA256 are in `../requirements.lock`.
