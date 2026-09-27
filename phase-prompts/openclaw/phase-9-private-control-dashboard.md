# Phase 9 — Private operator dashboard with scoped control

Build a useful private dashboard around the verified OpenClaw runtime. The
owner should see truthful health, work, costs, files and pending decisions,
and use narrowly authorized controls. Deliver a working operator product with
tested access boundaries, rather than a browser proxy for host administration.

Read [the execution contract](execution-contract.md), accepted Gate 8 evidence,
the runbook and current deployment. Verify installed-version docs for
[Control UI](https://docs.openclaw.ai/web/control-ui),
[external-app integration](https://docs.openclaw.ai/gateway/external-apps),
[Gateway protocol](https://docs.openclaw.ai/gateway/protocol),
[approvals](https://docs.openclaw.ai/tools/exec-approvals),
[security](https://docs.openclaw.ai/gateway/security) and
[tenant boundaries](https://docs.openclaw.ai/gateway/multi-tenant-hosting).
Inspect native UI/client capabilities before selecting custom components.
Reuse supported APIs; do not recreate runtime, memory, scheduling, budgeting
or approval engines in a dashboard database.

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

Before enabling privileged controls, confirm private authenticated Gateway
access, effective sandbox/tool boundaries, daily/monthly budget rejection and
budget-store fail-closed behavior, verified scheduled backups/restore, and
accepted doctor/security findings. A changed or missing prerequisite blocks
the affected control; do not silently disable isolation to expose it.

Inventory server RAM/disk and service headroom. Choose the smallest maintainable
stack with a vetted identity/session component, locked dependencies and a
modest resource limit. Compare extending a supported native surface with a
separate curated dashboard; explain the actual product gap. For a separate
service, its database stores app identity, assignments and audit metadata,
not copies of OpenClaw agent state or model credentials.

## 2. Specify the server boundary before building controls

Write `plans/phase-9.md` with browser → dashboard server → native API adapter
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
keyboard access, readable contrast and responsive layouts. Exercise the
actual owner flows in a browser; placeholder metrics or fake approvals do
not satisfy the product. File upload/write/delete is a separate authorized
increment: enable only with enforced permissions, size/type limits, safe
storage and malware scanning. If those are unavailable, keep uploads disabled.

## 4. Add identity/user operations only for the approved audience

For Telegram linking, verify numeric identity through the supported provider/
authenticated channel mechanism, not a claimed ID or display name. A one-time
link code is bound to the signed-in account and intended identity, expires
quickly, is rate-limited and consumed atomically. Test expiry, reuse, swapping
accounts and concurrent consumption. Linking a dashboard account must not
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
ready only after real health, identity, budget and isolation checks. On partial
failure, preserve evidence and rollback only the run's resources. Never give
the web app a Docker socket to implement provisioning. A narrow authorized
native/operator service must own host lifecycle operations. Do not promise
dedicated Telegram bots without owner-supplied bot tokens or a verified
authorized provisioning mechanism. Do not overcommit this VPS to add users.

## 5. Test, review and roll out privately

Create fixture identities for the enabled roles and at least two assigned
objects. Test allowed operations and forbidden routes directly, bypassing UI
filters. Cover cross-object enumeration/access, history/memory/cost leaks,
CSRF, WebSocket origins/subscriptions, session revocation, role changes,
expired/reused/swapped link codes, traversal/symlink races, unsafe rendering,
file limits, approval replay/payload change, audit failure, rate limits and
error redaction. Denied operations must leave no native/provider side effect.
Tests for a planned user role do not justify enabling that audience.

Prove the browser cannot obtain secrets, call arbitrary native/Docker commands
or alter unapproved policy/budgets. Where multiple users are approved, prove
state/channel/credential and network isolation in the selected trust mode,
including failed provisioning and cleanup. Test upload controls only if enabled.

Run real end-to-end owner sign-in, safe conversation/file view, a supported
native approval/denial, logout/revocation and dashboard restart. Include linked
user chat/reset/export/revoke only when that audience is enabled. Exercise
disconnection and ensure stale approval decisions cannot execute after
reconnect. Verify the app's database backup/isolated restore in addition to
the native recovery evidence, with outbound work disabled in restored clones.

Obtain independent review of auth/authorization and file/control boundaries,
fix valid findings and rerun affected checks. Deploy first to a private staging
address; activate only the already-authorized scope with a verified rollback.
Check listener exposure, app health, native doctor/security/secrets audits,
budget proxy and backup freshness afterward. Public exposure needs its own
concrete review and authorization.

## Artifacts and Gate 9

Produce the dashboard source/lockfiles, threat model/API-role matrix, tested
native version contract, startup/config examples without secrets, native-call
adapter tests, browser evidence, independent review/dispositions and the
execution-contract manifest. Update build log, architecture and runbook with
access, revocation, alert response, backup/restore and rollback. Explain which
audience and controls are enabled and which remain optional/disabled.

PASS requires the agreed private product to work with truthful data; every
enabled route/event/file/action to enforce identity and object authorization;
no browser/app access to raw host/Docker/secret controls; native approvals to
remain authoritative; audit/replay/revocation/negative tests to pass; and
sandbox, budgets, backups and restart recovery to retain objective evidence.
Additional-user scope requires its matching isolation proof. A missing
required boundary leaves Gate 9 BLOCKED/FAIL. A useful read-only owner view may
be handed over as partial work, with disabled controls and the incomplete gate
clearly reported. Stop after Phase 9.
