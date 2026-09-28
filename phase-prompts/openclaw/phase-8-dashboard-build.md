# Phase 8 — Build the private control dashboard

Build phase 2 of the remaining sequence. Read the
[execution contract](execution-contract.md), [phase index](README.md), current
build log/runbook, Phase 7 build artifacts and recorded prior evidence. Build
an owner product around the existing OpenClaw runtime, then test it with the
rest of the completed system in Phase 10. Passing final acceptance is not a
prerequisite to authoring or privately previewing this dashboard.

## Required result

A private authenticated dashboard with real health/work/cost/file/decision/
connection data, maintainable source and locked dependencies, scoped native
API adapters, and prepared fixtures. Reuse the existing native Control UI
where it meets the product requirements; implement only the actual product
gaps. No second agent loop, scheduler, budget or approval engine.

Check installed-version official docs for
[Control UI](https://docs.openclaw.ai/web/control-ui),
[external apps](https://docs.openclaw.ai/gateway/external-apps),
[Gateway protocol](https://docs.openclaw.ai/gateway/protocol),
[approvals](https://docs.openclaw.ai/tools/exec-approvals) and
[trust boundaries](https://docs.openclaw.ai/gateway/multi-tenant-hosting).

## 1. Freeze the audience and safe starting conditions

Default to one owner, private access and read-only observability first. Reuse
any exact audience/feature approval already given; otherwise additional
operators or users remain disabled while their design and fixture tests can
be prepared. Public signup, billing, customer tenancy and internet publication
are separate expansions, not implied by a dashboard request.
Freeze the required feature set before implementation. User management or
provisioning explicitly requested by the owner remains required: implement and
test it with controlled identities, and report any missing live-audience
authorization as an activation blocker rather than silently dropping it.

Implement privileged controls behind server-side disabled feature gates when
prior behavioral evidence is missing. Existing authenticated native surfaces
remain available within their present authority. Building routes/components
can proceed before Phase 10 acceptance; enabling new mutating/provisioning
controls requires their targeted authorization proof. Do not widen tools,
isolation, spending or browser privileges to make controls appear usable.

Inventory server RAM/disk and service headroom. Choose the smallest maintainable
stack with a vetted identity/session component, locked dependencies and a
modest resource limit. Compare extending a supported native surface with a
separate curated dashboard; explain the actual product gap. For a separate
service, its database stores app identity, assignments and audit metadata,
not copies of OpenClaw agent state or model credentials.

## 2. Specify the server boundary before building controls

Write `plans/phase-8.md` with browser → dashboard server → native API adapter
→ OpenClaw/LiteLLM data flows, trust assumptions, role matrix, storage,
resource limits and rollout/rollback. Define every endpoint and event stream:
request/response schema, role, object ownership, allowed native operation,
audit event, rate/size limit, idempotency/reconciliation and failure behavior.

The dashboard server uses a scoped supported Gateway client privately. The
browser gets app sessions and sanitized responses, never Gateway/Telegram
tokens, proxy/model keys, SSH keys, SecretRef values or native auth stores.
The app container has no Docker socket, broad host mounts or arbitrary shell
API. Map fixed validated operations to documented native calls; reject client-
supplied RPC names, shell commands, filesystem roots and arbitrary session keys.
Discovery/version negotiation must fail safely on incompatible APIs.

| Role | Allowed scope | Forbidden scope |
|---|---|---|
| Owner | Approved dashboard controls, account assignments, native approvals and recovery requests | Secret export, unaudited actions or bypassing native policy |
| Operator, if authorized | Assigned objects and explicitly delegated decisions | Owner policy, global secrets, unassigned objects or host administration |
| User, if authorized | Their own linked identity, chat, sessions and virtual workspace | Other people's objects, approvals, policy, credentials or budgets |

Enforce this matrix on every server route, WebSocket subscription, export,
download and mutation. UI filtering is not authorization. An internal
Gateway operator token is not safe to distribute as a user's credential.
If native approval resolution cannot express the delegated scope, keep that
control owner-only instead of approximating authorization in the UI.

Use vetted sign-in with owner MFA, session rotation/revocation, httpOnly/secure/
sameSite cookies, CSRF protection, strict origins and WebSocket handshake
checks. Use TLS for network access and keep ports private. Apply CSP and safe
rendering to conversations, markdown, filenames and tool output. Sanitize
logs/responses; redact credentials before storage, not only when displaying.

Record actor, role, object, action, native request ID, timestamp and result in
an append-only application audit stream; forbid edits/deletes through app
roles and document retention/tamper detection. Do not call it immune to host
administrator compromise. If a required audit write fails, reject the
mutation. Record pending/completed/failed or uncertain outcomes and reconcile
native receipts before retrying; UI refresh must not repeat an effect.

## 3. Ship a complete owner interface first

Implement a small coherent UI with actual server data:

- Overview: Gateway/proxy/database health, release, sandbox state, backup age,
  current budget/usage, last audit and alerts. Show observation timestamps;
  stale/unavailable/unknown is distinct from healthy or zero cost.
- Work: scoped conversations and objective status, paginated sanitized history,
  new chat and native cancel/reset controls only where authorized. Resetting a
  session is scoped; never offer arbitrary state-file deletion.
- Files: an allowlisted virtual workspace with bounded read/download. Resolve
  ownership server-side; do not expose host paths, state/config directories,
  dotfiles, auth stores or raw logs. Deny traversal, encoded traversal and
  symlink escape using race-safe file access, not canonicalization alone.
  Use short-lived signed downloads bound to the exact object/version and
  current authorized identity; revocation must still prevent access.
- Decisions: native pending requests show exact action, target, payload, scope,
  expiry and known cost. Resolve native IDs through supported authorization;
  reject expired/replayed/changed requests. Keep native policy authoritative.
- Account/integrations: verified identity, link/revoke/session controls and
  connection status; no credential retrieval. Use documented protected
  credential/OAuth flows and preserve OpenClaw command-owner separation.

Add clear loading, empty, disconnected, error and permission-denied states,
keyboard access, readable contrast and responsive layouts. Use real server data rather than placeholder metrics or fake approvals.
Comprehensive owner browser flows are exercised later in Phase 10. File upload/write/delete is a separate authorized
increment: enable only with enforced permissions, size/type limits, safe
storage and malware scanning. If those are unavailable, keep uploads disabled.

## 4. Add identity/user operations only for the approved audience

For Telegram linking, verify numeric identity through the supported provider/
authenticated channel mechanism, not a claimed ID or display name. A one-time
link code is bound to the signed-in account and intended identity, expires
quickly, is rate-limited and consumed atomically. Author later cases for expiry, reuse, swapping
accounts and concurrent consumption; execute them in Phase 10. Linking a dashboard account must not
silently add it to the OpenClaw command-owner allowlist. Support disable,
active-session revocation and scoped export/delete with retention disclosure.

Choose and document the appropriate trust mode:

- Trusted collaborators may share an explicitly accepted Gateway trust
  boundary with separate DM sessions and assignments. Session separation is
  not protection from a hostile tenant; state this limitation clearly.
- Mutually untrusted users require separate Gateway instances and credentials,
  state/workspaces, channel accounts, model keys/budgets, networks and resource
  limits. Merely creating another agent/session in one Gateway is insufficient.
  Use a verified supported lifecycle mechanism; treat experimental native
  provisioning as experimental and evaluate before enabling it.

If provisioning is in scope, make it asynchronous, idempotent and recoverable
with pending/ready/failed states, quota/concurrency checks and receipts. Mark
ready only after real health/identity and the targeted budget/isolation
checks in Phase 10. Build the lifecycle path now; leave activation disabled. On partial
failure, preserve evidence and rollback only the run's resources. Never give
the web app a Docker socket to implement provisioning. A narrow authorized
native/operator service must own host lifecycle operations. Do not promise
dedicated Telegram bots without owner-supplied bot tokens or a verified
authorized provisioning mechanism. Do not overcommit this VPS to add users.

## 5. Prepare acceptance fixtures and privately deploy

Implement the fixture identities/objects, direct-route assertions, browser
scenario definitions and isolated app-database restore support needed by
Phase 10. Cover auth/object ownership, approvals, file traversal/symlink races,
CSRF/origins, revocation, replay, audit failures, error redaction and any
explicitly approved extra-user provisioning. Do not run the full suite or
independent paid review during this build. Scope is one owner unless additional
audience authorization was actually given; do not introduce public signup.

Use a private deployment/preview with real data, authenticated access, bounded
resources and a reversible config/image change. Lightweight checks: install/
build/type or syntax checks, schema/readback, startup and health/listener check,
no-secret browser assets, and a single basic authenticated page smoke where
practical. No paid model workflow, adversarial suite, full browser matrix or
restore drill. New controls without proof remain implemented but disabled
server-side; show their actual availability clearly without invented metrics.

## Artifacts and build completion

Produce `plans/phase-8.md`, dashboard source/lockfiles, API-role matrix, native
version contract, auth/session/file/control enforcement, prepared Phase 10
cases, private access/start/stop instructions and rollback. Update architecture,
runbook and build log; retain a sanitized `evidence/phase-8/<UTC-run-id>/`
manifest describing setup checks and disabled controls.
Build status READY/PARTIAL/BLOCKED is separate from acceptance DEFERRED to
Phase 10. Delivery must say exactly which features are built and usable versus
waiting for credentials/proof. Stop after Phase 8 unless more is authorized.
Next build is optional [Phase 9 browser optimization](phase-9-browser-optimization-build.md).
