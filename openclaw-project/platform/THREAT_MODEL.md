# Isolation threat model and activation gates

Assets: account membership, project/chat/memory/files, runtime workspaces/tools,
provider/connector/Gateway/cloud secrets, spend budgets, entitlements, audit and
backups. Adversaries: unauthenticated visitor, authenticated customer guessing
other IDs, malicious uploaded/retrieved/code content, compromised tenant Gateway/
harness and compromised trusted app/operator credentials. Physical/provider/
host administrator trust is disclosed, not magically eliminated.

| Path | Boundary / mitigation | Required proof / phase |
|---|---|---|
| Guessed account/project/session/URL | Server identity + membership + scoped SQL/adapter; opaque IDs alone insufficient | Local repository/direct API denial passes; real auth 3/15 |
| Cross-account FK insertion | Composite account/project/conversation/task/deployment relationships | Local cross-account and same-account wrong-project inserts fail |
| Stolen/revoked cookie/role | Maintained verifier, rotating revocable sessions, active membership on every access/stream | Default deny now; recovery/revocation 3/15 |
| Hostile tenant process/Gateway | Independent Fleet cells/host identities/network/key/storage with verified stronger worker runtime; no cross-cell mounts or shared owner auth | Actual two-cell/worker runtime negative tests 4/15; current single-VPS target unaccepted |
| Host-side Codex/ACP | Enforced project roots/environment/network/secret separation, reviewer read-only | Version/policy probe + actual denial 10/15 |
| Docker/cloud authority | Only trusted narrow supervisor; web app has no socket/cloud key/command endpoint | Control authentication/fixed-driver proof 4/15 |
| SSRF/private network/redirects | Node egress policy, destination validation after redirects, no metadata/control/other-node reach | Browser/connectors 11/15 |
| Prompt injection/tool content | Restricted workers; attributed findings; outside text cannot change authority/memory rules | Synthetic canary no effects 10/15 |
| File traversal/symlink race/active preview | Descriptor-safe root access and isolated preview origin, quotas/scan | Owner residual race must be fixed in 8/15 |
| Concurrent cost/uncertain usage | Atomic reservations/receipt reconciliation/store fail closed, no client pricing | Skeleton only; admission 5/15 |
| Audit failure/metadata tamper | Required mutation audit, append-only triggers, private state, off-host evidence | Trigger proof now; audit-required mutation flow 3/15 |
| Public edge/header spoof | Loopback-only skeleton, strict Host/Origin, no trust-user header; future TLS/OIDC | Foundation denial passes; edge 3/18 |
| Backup restore resurrects access | Encrypted off-host custody, tombstone/current billing/spend reconciliation, disabled clone delivery | 14/15 |
| Logging/exfiltration | Allowlisted request metadata, no body/header/query/native exception logs | Local canary passes; future tool/event redaction 9/15 |

Gateways/proxy/database remain private. Current app/control cannot execute,
provision, upload, bill, link Telegram or purchase; enabling a boolean fails
config validation. No direct customer capability is declared ready until the
corresponding identity/isolation/budget/receipt assertions pass. VM resource
limits are proposed starting allocations, not proof against kernel or provider
administrator compromise. Do not sell shared-operator trust as immunity from
operator access. Audit/support access must be minimal, visible and authorized.

Phase3 targeted proof replaces fixture-only account evidence: verified two-account
Django/Gunicorn direct API ownership, server mapping/routing spoof denial,
CSRF/origin/secure cookie/rotation/expiry, concurrent recovery consume/replay,
operator TOTP replay/MFA/expired scoped grant, membership/suspension/role/all-device
revocation, required audit failure including post-login rollback, safe HTML/logs
and180-day metadata expiry all pass synthetic checks. Public TLS/browser/SMTP/
real identities/load and tenant-runtime isolation remain unaccepted. Loopback
proxy client-IP/scheme overwrite and private state ownership are mandatory before
external activation; untrusted X-Forwarded-For is ignored.

Phase4 host assessment does not prove single-host runtime isolation. See ADR007
and the measured report; standard runc is present, gVisor/worker broker/quota
integration unbuilt, current agent admission0. Public app and customer-owned
infrastructure are separate concepts; customers need only the shared app origin.
