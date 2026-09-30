# API, roles and object ownership — v1

Public/current response schemas in `openapi.json`; internal metadata schemas
in `schemas.json`; not every internal field is a public DTO. All financial
metadata uses integer micro-USD (1 USD = 1,000,000 units), never float.
Ownership comes from a verified identity/membership and server mapping. Account
IDs in paths/payloads do not select another tenant. Every future route rechecks
role/account/object and uses fixed operations; unknown fields rejected.

| Route / stream | Role/scope | Operation / audit / limit | Foundation availability |
|---|---|---|---|
| GET /healthz | Local operator | Process health, no secrets; 5s socket bound | Implemented app/control |
| GET /readyz | Local operator | DB/schema/FK health; customer_ready distinct | Implemented app/control |
| GET /v1/projects | Customer, active account/membership | Own list (100-row max), no native calls | Implemented handler/repository; default identity denies |
| GET /v1/projects/{id} | Customer, own project | Scoped read; other/missing ID same404 | Implemented; test-only identity injection |
| POST /v1/projects | Customer own account | Plan quota/name validation, durable audit/idempotency | Phase 3/6, disabled |
| POST /v1/conversations/{id}/messages | Customer own project/conversation/deployment | Phase5 reservation + fixed native send; message op id, pending/uncertain reconciliation | Phase6, disabled |
| GET /v1/conversations/{id}/history | Customer own conversation | Bounded history/cursor, private native key | Phase6, disabled |
| POST /v1/tasks/{id}/cancel or pause | Customer own task | Verified exact native control, idempotency/audit, acknowledged state | Phases6/9; native pause/abort proof required |
| GET /v1/tasks/{id}/events | Customer own task + revocation during stream | Scoped cursor/replay; ≤3 streams/account, public typed payloads | Phase9, disabled |
| POST /v1/account/telegram-link; unlink | Signed-in customer | Hashed one-time code10min, rate limit, atomic consumption, audit | Phase7, disabled |
| GET/POST /v1/projects/{id}/files; artifacts/{id}/versions/{n} | Customer own project/task/version | Quotas/type/scan/preview/descriptor-safe download and revocation | Phase8, disabled |
| GET/PATCH/DELETE /v1/memory/{id} | Customer own native memory | Exact correction/delete index, retention disclosure, audit | Phase10, disabled |
| /v1/schedules, /v1/integrations | Customer scoped native job/connector | Stricter policy/OAuth identity/expiry/revoke, fixed tools, audit | Phases10/11 later scope, disabled |
| GET /v1/usage; checkout/portal | Customer own ledger/provider customer | Estimate vs final; verified prices/server-derived IDs, idempotency/audit | Phases5/13, disabled |
| POST /v1/webhooks/billing or telegram | Verified provider ingress, not customer cookie | Raw signature/update verification, inbox dedup, fixed routing | Phases7/13, disabled |
| POST /v1/operations (control port only) | Separate authenticated internal service identity | Fixed kind/account/deployment/generation, idempotency+request hash, durable audit; no command/path | Phase4, denies now |
| /internal/accounts/{id}/deployments and incidents | Scoped internal operator with MFA | Explicit support/lifecycle scope/audit, no secret export | Phases3/4/14, disabled |

Customer: own work only. Account-admin (later if selected): only explicitly
delegated account membership operations. Internal operator: explicitly scoped
operational metadata/actions, no automatic content access. Service: purpose-
bound operation credentials, no customer login. Role alone never grants all
account access. Default verifier denies every customer/internal endpoint.

Future mutation schema includes server operation ID, idempotency key, expected
object revision/generation and exact validated payload hash; replay mismatch
409. Store outage/audit/reservation/capability failure503, budget/entitlement
refusal recorded without native call. No raw provider/native exception text.
Streams/export/downloads apply current access, not stale grant-at-creation.

## Phase 3 account application overrides

Gunicorn/Django app replaces default-deny fixture identity for private account
checks. The stdlib control/fixture verifier continues to deny by default. No
customer task capability becomes enabled as a result of this replacement.

| Route | Authority | Audit/effect |
|---|---|---|
| GET /account/login,recover,reset,activate,mfa pages | Public forms | Escaped HTML, CSRF token, no token in URL |
| POST /auth/login | Password + verified eligible identity | Session rotates; pending/completed or denied audit;5/15min identity+IP |
| POST /auth/recovery | Public generic response | Eligible customer-only queue; no SMTP latency in request |
| POST /auth/activate,reset | Hashed15min purpose/epoch token | Atomic consume/password/epoch/audit; replay denied |
| POST /auth/logout,revoke-sessions | Current identity/customer respectively | Current session deletion/all-session epoch revocation + audit |
| POST /auth/mfa | Explicit operator identity, confirmed TOTP | OTP throttle/replay protection, session rotation, audit |
| GET /v1/me,projects,projects/{id} | Verified customer + live active membership | Account from identity; other/missing object same404 |
| /v1/tasks,streams,artifacts,conversations,operations/{id} | Same customer + scoped object | Ownership checked; own503 disabled, other404; no side effects |
| /v1/exports,memory,schedules,integrations,costs,controls | Same customer | Always503 disabled; no native calls or data |
| /internal/accounts/{id}/invite,revoke,suspend,audit | Operator MFA + exact current account/action grant | Required audit; no unrestricted content browsing |
| /internal/accounts/{id}/export,impersonate | None | Always403; unsupported privileges |

Optional account-admin is unselected; membership with that role cannot use the
customer interface. Service identities cannot sign in. General60read/10mutation
per-minute limits use trusted identity/IP, never client account IDs. Audit store
failure denies required mutations and cannot leave a saved unaudited session.

## Phase4/5 local continuation — 2026-09-30

Durable lifecycle metadata/coordinator and offline budget reservation/receipt core
are implemented, with scoped operation/usage read views and fixed MFA operator
queue routes. See platform/agentai_platform/lifecycle/README.md and platform/BUDGET.md
(paths relative to openclaw-project). Native lifecycle/worker dispatch, secrets,
stronger-runtime/quotas/network isolation, real route accounting and a fitting
existing-host profile remain incomplete; runtime/customer/payment/mail gates stay
off. No live migration or listener installed. Package new immutable SQL002/003
and Django004–007 with the release; explicit private bootstrap is required and
old releases reject the newer schema. Host-only lifecycle_status reads counts;
seed_trial prepares one seven-day/$1 entitlement without resetting one already
present. No account or invitation was created. Continue Phase4 native integration
and Phase5 provider enforcement before dependent chat activation.

## Serial request intake

GET/POST /v1/requests, GET /v1/requests/{request_id}, and POST
/v1/requests/{request_id}/cancel require verified account membership. Mutations
require CSRF. Request lookup combines authenticated account and ID; guessing
another account’s ID returns indistinguishable 404. Only message/idempotency key
are accepted for intake. /account/requests/ renders escaped own records. Queue
intake is enabled independently of native dispatch, which remains disabled.
