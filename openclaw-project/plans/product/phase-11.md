# Phase 11 — scoped customer integrations and account setup

Status: **BUILD COMPLETE offline; every service DISCONNECTED and link flow fail-closed.**
Readiness and acceptance are separate: no provider account was connected or read, no
credential was touched, nothing was deployed, no paid call. Date 2026-10-09.

## Delivered (by prompt item)

1. **Inventory and matrix** — `phase-11-permission-matrix.json`: connector versions and
   exact tool exposure (from a read-only server probe of `mcp.servers`, values only),
   per service the reader, exact allowed/forbidden scopes, read/draft/send/share/write/delete
   distinctions, token storage/refresh/revocation and billing. **Decision recorded:** all
   four connectors and credentialed browsing are `later` scope (INT-01..05), so they are
   optional for private-beta launch; nothing launch-required is blocked by them. Brave stays
   live for the owner researcher only and is not available to customers.
2. **Protected linking** — `connectors.py`: OAuth state (single use, 10-min expiry, bound to
   account+actor) with PKCE S256, exact redirect allowlist, verifier held in custody, state burned
   before any provider call, errors generic, tokens only as account-bound custody references.
   Re-linking revokes the previous connection. Cross-account credential selection/refresh is
   structurally impossible (every custody read is account-bound; swapped-reference test).
3. **Read-only by default** — granted scopes must be a non-empty subset of the read-only set
   (compose/send/modify/full-Drive/`:write` rejected and the freshly minted tokens revoked);
   mandatory server-enforced selection for Drive and GitHub; local draft proposals only. No
   writable kind exists in the production catalog. A synthetic service proves the future write
   machinery (exact payload hash + target + expiry authorization) so enabling later needs only
   native enforcement proof.
4. **Content handling** — only the `researcher` is a permitted reader (policy_check fails any
   other agent holding connector tools); provider content returns via `attribute()` as untrusted
   data with `instruction: false`, secrets redacted. Hostile email/event/doc/issue fixtures prepared.
5. **Failure handling** — 429/5xx bounded to two retries (Retry-After honoured, 60s cap); 401 =>
   `reconnect_required`; idempotency keys; uncertain operations reconcile from provider receipt and
   block resend; disconnect cancels queued operations and revokes even if custody deletion fails
   (audited `uncertain`, `purge_revoked()` retries).
6. **Owner-deferred sign-ins preserved** — UI/API/config built; link and callback answer 503 and
   consume nothing. Brave key exposure/rotation carried in BUILD_LOG as an open custody obligation
   without reproducing the key.
7. **Credentialed browser** — `BrowserProfiles` + `ssrf.py`: per-account profiles, credential and
   cookie jar only in custody, HTTPS-443 allowlist, private/loopback/link-local/metadata/IPv4-mapped
   blocked, redirects rechecked per hop, revoke deletes references, swapped-secret canary proven with
   a mock. Backups of profiles must be encrypted with separately held keys (RUNBOOK).
8. **Prepared proofs** — `config/phase11-fixtures/cases.json` maps identity/scope, disabled/revoked,
   unauthorized target, injection, draft-only, replay/uncertain and browser cases to P15 gates; the
   mock-coverable ones are covered by tests, the rest are marked live-only.

Account settings: `/account/connections/` page, `GET /v1/account/connections`, `POST .../link`,
`GET .../callback`, `POST .../disconnect`, `GET /v1/account/drafts` (OpenAPI + API matrix updated).

## Checks actually run

- Platform suite 200 tests OK (2 skipped): new `test_connectors` 24 (link/PKCE/state/redirect,
  scope rejection + token revocation, no token in DB, selection, cross-tenant, relink, retry policy,
  reconnect, disconnect + purge, idempotency, write refusal and authorization machinery, drafts,
  attribution, SSRF and redirects, browser profiles), policy_check +1, asset checks +2.
- Django suite 66 OK (62 existing + 4 new route tests), Vercel routing check passes. Django was run
  from a scratch venv built from the hash-pinned `requirements.lock`.
- Read-only probe of `mcp.servers` config on the server (no connect, no content read).

## Not claimed / blockers

- No real provider, custody backend, client registration, OAuth exchange adapter or GitHub App exists;
  mocked flows are not provider acceptance. Live proofs: P15-GMAIL/CALENDAR/DRIVE/GITHUB/AUTH-BROWSER.
- The single Google MCP server serves Gmail, Calendar and Drive, so separation relies on granted
  scopes. GitHub per-repo scoping through the Copilot read-only endpoint is unverified.
- Customer-cell blockers from Phase 10 still apply (customer cell boundary; owner connector tools must
  not exist in a customer cell).
- Owner actions pending: Google/GitHub sign-ins (when wanted), Brave key rotation.

Cost: zero provider spend. Rollback: code-only; migration 0011 is additive; routes fail closed.
Evidence: `evidence/product/phase-11/20261009T180000Z/manifest.json`.
