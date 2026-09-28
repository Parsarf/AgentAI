# Phase 8 — private control dashboard plan (2026-09-27)

## Audience (frozen)

**One owner, private, read-only-first.** No user management or provisioning
has been requested → additional roles stay *designed but disabled* (role
matrix below); public signup/billing/tenancy are out of scope entirely.
Native Control UI (loopback :18789 via SSH tunnel) remains the chat/settings
surface. The actual product gap it does not cover: one private page that
aggregates **ops truth** — gateway/proxy/db health, sandbox containers,
backup freshness (Phase 7), LiteLLM spend vs configured caps, approvals
pending, connector state, app audit — plus scoped session/file views.

## Stack decision

Separate **small host service** (not container): Python 3.12 **stdlib only**
(zero third-party deps → nothing to lock beyond the system interpreter),
single file `dashboard/app.py`, systemd-hardened, bound `127.0.0.1:18795`,
accessed through the same SSH-tunnel trust model as the Control UI
(possession: SSH key; knowledge: app password). Rationale for host service
over a container: it must invoke a **fixed map** of `docker exec`/read-only
SQL/ops commands; a container would need the Docker socket, which the
contract forbids. The service never runs shell strings — fixed argv tuples
only — and is restricted by systemd (ProtectSystem=strict, ReadWritePaths
limited to its own dir + backups/ops read, NoNewPrivileges, PrivateTmp,
MemoryMax=200M, CPUQuota=25%).

App storage: `/opt/openclaw-production/dashboard/` — `owner-secret`,
`session-secret` (0600), `audit/audit.jsonl` (append-only app audit; root
is host admin and could edit it — stated, not hidden). No OpenClaw state,
no model credentials, no tokens are stored or copied.

## Endpoint/flow map (all read-only unless noted)

| Route | Method | Data source (fixed native op) | Mutating? |
|---|---|---|---|
| `/login` | GET/POST | owner-secret constant-time compare; 5 fails/h lockout | session issue (audited) |
| `/` overview | GET | gateway `/healthz`, CLI `--version`, `docker ps`, `pg_isready`, LiteLLM SpendLogs SQL (today/30d vs $2/$25 configured targets), Phase 7 backup status file | no |
| `/sessions` | GET | `sessions list --json` (keys/agent only, sanitized) | no |
| `/files` | GET | allowlisted root `work/` in container via fixed `find` argv; dotfiles/`..`/absolute/symlink refused; 2 MB cap, HMAC-signed 5-min download bound to path+session | download is a read; audited |
| `/decisions` | GET | `approvals pending --json` — exact action/target/expiry display | **resolve disabled** (native policy stays authoritative; owner resolves via Telegram/Control UI) |
| `/integrations` | GET | `manage-connectors.py list` (adapters/enabled state) | **toggle disabled** (owner uses `bin/connect-tool`) |
| `/audit` | GET | last 20 app-audit records | no |
| `/logout`, `/revoke-all` | POST | destroy cookie / regenerate session secret (global revocation) | session-scope only; audited |

CSRF token on every POST; `HttpOnly; SameSite=Strict` cookies; CSP +
frame-deny + no-store headers; HTML-escaped output; short cache TTLs (5–60 s)
with observation timestamps on every card; stale/unavailable/unknown rendered
distinctly from healthy/zero. Deviation, stated: no `Secure` cookie flag and
no TLS because the listener is loopback-only behind SSH; if this is ever
exposed beyond loopback, TLS termination is a hard prerequisite (recorded in
remaining items).

## Role matrix

| Role | Allowed | Forbidden |
|---|---|---|
| Owner (only active role) | all routes above, session revocation | secret export, unaudited mutation, native policy bypass |
| Operator/User | **disabled** — no routes; design + Phase 10 fixture cases only | everything until a targeted authorization + isolation proof exists |

## Feature gates (server-side, shown truthfully in UI)

`new_chat`, `session_reset`, `approval_resolve`, `connector_toggle`,
`file_upload`, `provisioning` — all `False` with reason "awaiting Phase 10
targeted proof / owner authorization". No invented metrics; disabled controls
are visibly labeled.

## Rollout / rollback

Install = copy `dashboard/` + `owner-secret` (generated, 0600) + systemd
unit (`openclaw-dashboard.service`, enabled). Rollback = `systemctl disable
--now openclaw-dashboard` + remove unit + delete the directory. Existing
services untouched; port 18795 was free; gateway/litellm/postgres configs
unchanged.

## Phase 10 cases added (definitions only, not run here)

`T10-DASH-AUTH` (login, lockout, cookie flags), `T10-DASH-CSRF-ORIGINS`,
`T10-DASH-FILE-TRAVERSAL` (`..`, encoded, dotfile, symlink), 
`T10-DASH-DOWNLOAD-REPLAY` (expired/reused signature), `T10-DASH-REVOCATION`,
`T10-DASH-AUDIT-FAIL` (audit write failure rejects mutation),
`T10-DASH-REDACTION` (no secrets in responses/logs), 
`T10-DASH-DISABLED-CONTROLS` (gates actually refuse server-side).
