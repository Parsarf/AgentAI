# Phase 8 build — summary (run 20260927T212204Z)

## Outcome

Build status **READY**; acceptance **DEFERRED to Phase 10**. A private,
owner-only ops dashboard is deployed and running on the VPS with real data;
every mutating control is server-side disabled and labeled truthfully.

## What was built

- **Private ops dashboard** (`openclaw-dashboard.service`):
  - Overview: gateway/proxy/Postgres health, release, container states,
    LiteLLM spend vs the configured $2/$25 targets (live from the proxy
    ledger: today $0.35 / 30d $3.68 at build time), Phase 7 backup freshness
    (RPO 24 h), each card with its observation timestamp; stale/unknown
    states are distinct from healthy/zero.
  - Sessions: sanitized session-key listing.
  - Files: allowlisted virtual view of the container `work/` root —
    dotfiles/`..`/absolute/symlinks refused, 2 MB cap, HMAC-signed 5-minute
    downloads bound to path + session.
  - Decisions: native pending approvals displayed exactly as reported;
    resolution stays with native policy (owner via Telegram/Control UI).
  - Integrations: connector manager listing; toggles stay with the owner's
    `bin/connect-tool`.
  - Audit: append-only application audit stream (logins, downloads,
    revocations) rendered read-only.
- **Auth**: app password (0600 on host) + HMAC session cookies
  (HttpOnly, SameSite=Strict, 12 h, rotated per login), 5 failures/hour
  lockout, CSRF on every POST, one-click global session revocation.
- **Trust boundary**: the dashboard stores only its own auth secrets and
  audit — no OpenClaw state, gateway/Telegram tokens, proxy/model keys or
  SSH material. Fixed argv native operations only; no client-supplied
  commands; no Docker socket anywhere.

## Proof from this run

- Local + remote `py_compile` clean (two bugs caught and fixed before
  install: a dead conditional; an approvals-JSON ternary that would always
  have shown "no items").
- Service active; listener confirmed loopback-only.
- Authenticated smoke: login page 200; wrong password 403 and audited;
  correct login → all six routes 200; overview renders real gateway health;
  CSP + X-Frame-Options verified.
- Zero model calls, zero paid suites.

## Honest limits

- No TLS: access is loopback-only behind SSH; TLS is a hard prerequisite
  before any broader exposure.
- File reads have a theoretical TOCTOU race; adversarial file cases are
  defined (`T10-DASH-FILE-TRAVERSAL`) for Phase 10.
- The audit stream is not claimed tamper-proof against the host
  administrator.
- Additional audiences/provisioning: designed in the role matrix only —
  no owner request, so nothing is activated; public signup remains out of
  scope.

## Access (owner)

`ssh -L 18795:127.0.0.1:18795 <user>@69.48.206.62` → http://127.0.0.1:18795
— password is `/opt/openclaw-production/dashboard/owner-secret` (read it
over SSH; the app never displays it).

## Rollback

`systemctl disable --now openclaw-dashboard`; remove the unit; delete
`/opt/openclaw-production/dashboard/`. Nothing else was modified.
