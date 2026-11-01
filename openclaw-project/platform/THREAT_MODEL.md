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

## Side panel in the customer's own Chrome (mini chat beside the agent's tab)

The extension shows the run's activity and a small chat in Chrome's side panel, only on the tabs Lumina works in. Its credential is a **panel ticket**: HMAC-signed, 90 seconds,
bound to one account, the person it runs for, one conversation and one connected computer. It carries no cookie and no device token.

* **Who can mint:** only the request worker (app user), which alone reads `AGENTAI_PANEL_SECRET_FILE`. The root browse service never has the key; it only relays an opaque string,
  in a fixed shape, to the one computer the ticket names, and only while that computer is connected (`DeviceDesk.push_panel`). A compromised browse service therefore cannot speak as a customer.
* **When one exists:** the worker pushes a fresh ticket every 30 seconds while a run of that conversation is going, the customer's "use my own browser" choice is on, and that computer is
  connected. When the run ends the pushes stop and the last ticket lapses within 90 seconds, just long enough to read how it ended.
* **What the app re-checks on every call, not just the ticket:** the origin is one of the configured `chrome-extension://` origins (exact match, no credentials mode); the person is still
  an active member and the conversation is theirs; the named computer is connected now with the choice on (status and writes); the run is still going (send and stop). `send` steers the run through
  the same `ChatService.send` as the web chat, so budget, size, idempotency and denial categories are identical; it never starts a new task. Rate limits: by address before the ticket is checked
  (forged-ticket floods), by account after.
* **Not an expansion of the extension's reach:** no host permissions; the panel is enabled per tab by the extension only for the tabs it owns; the panel page never holds the ticket (the service
  worker makes the calls); text from the network is shown with `textContent`.
* **Residual risk:** a ticket stolen from the extension's memory within its 90 seconds can read that conversation and steer its running task; it cannot reach other conversations, start tasks, or
  work after the computer disconnects. Someone controlling the browser itself controls the panel while a run is going. Page content can still try to steer the agent (prompt injection) exactly as before.

