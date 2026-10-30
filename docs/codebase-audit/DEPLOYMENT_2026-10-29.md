# Deployment and experience changes — 29 October 2026

Production backend release: `20261030T022448Z-webhook-0c48ade` (30 October UTC,
29 October Los Angeles). Source: `0c48adeb44b3c0b248519fd5ed00da7c0fdda387`.
Owner explicitly requested deployment. Result: **released and verified**.

## Changes and app experience

| Change | Where it applies | Expected experience |
|---|---|---|
| Billing webhook body limit corrected | Live backend, `98d091a` | Valid signed provider events above 8 KiB can reach billing processing. This reduces avoidable subscription/payment-update retries; it does not activate billing or add a billing screen. Outer ceiling is 256 KiB. |
| Telegram webhook handling corrected | Live backend, `98d091a` | Legitimate updates above 8 KiB reach the handler. After secret verification, updates above 64 KiB are acknowledged and ignored without reading their body. This does not activate or finish the Telegram integration. |
| Required backend checks expanded from 20 to 25 modules; all other 48 modules get reports | Local Git workflow, `671f121`; first GitHub run awaits a push | More regressions are caught when preparing updates. Existing required checks are preserved. No direct screen change. |
| Frontend type checks, 362 tests and production build added to CI; tool-origin JS and browser runner checks added | Local Git workflow, `671f121` | Better validation for future releases. Browser checks initially report-only for the first Linux baseline. |
| Browser test fixtures honor the configured Chrome path | Test code, `671f121` | Tests can exercise Linux Chrome as well as the Mac installation. No customer browser-engine change. |
| Existing tool-origin code saved in four reviewed commits | `82bbdf4`, `af10c90`, `6df24da`, `6404d90` | Preserves the browser-call identity/progress behavior that was already deployed; makes the source recoverable and reproducible. It is not a new browser capability in this deployment. |
| Ignore rules cover private key names, root archives/images, local tooling, private exports, experiment code and node_modules symlinks | Local Git, `a973add`, `cc136cf` | Reduces accidental inclusion of private/local files in future commits. No app interaction changes; nothing was deleted. |
| Audit, source snapshot, test results and owner choices preserved | Local documentation and private backup | Easier recovery and continuation. Deployment now includes a source-commit/file-hash manifest. |

This batch changes background reliability. The frontend bundle was not replaced,
so the app screens retain their existing design. Screenshot behavior was left
unchanged at the owner's explicit request. No budget/cancellation fix, admission
column, retention change, SSH hardening or feature activation was included.

## Validation

- Before deploy: 980 platform tests, OK (2 skipped); 49 relevant account tests
  passed; oversized Telegram body-read assertion passed. Frontend build/type
  check and 362 tests, browser fixture 78 tests, Node runner 26 tests and plugin
  3 tests were previously green.
- The earlier heavy end-to-end run hit local disk exhaustion; its clean rerun
  is still pending. It was not represented as passing.
- Production preflight found no waiting/running/uncertain requests, active or
  uncertain reservations, or occupied request slot.
- Immutable archive SHA-256:
  `0c16359b42f3259cad54df8d53d58a4f2ed2e0b74889dc3ac5c955ceb0e5f4ae`.
- `release.py --dry-run` passed copy migration, canary probes and compatibility
  with the previous release; actual release passed live probes.
- All 307 deployed source hashes match the archive manifest. No SQL migration
  changed. Six checked services/timer are active.
- Health/readiness: 200/200. Public login: 200. Anonymous `/v1/me`: 401.
- Public unsigned billing body 9 KiB: 400 (signature check reached); Telegram
  9 KiB without a valid secret: 403; billing 300 KiB: 413; ordinary login
  request 9 KiB: 413. No valid provider update or customer task was submitted.

## Recovery and release evidence

Previous platform release: `20261028T212308Z-tool-origin-v2`.
The supervisor remains on that release; its runtime code is identical in the
new source archive. Only the platform app required a live restart.

The release process created
`backup-20261030T022958Z-premigrate-20261030T022448Z-webhook-0c48ade.sqlite3`
on the server: mode 0600, 7,938,048 bytes, SQLite quick-check OK. Binary rollback
compatibility was verified. The previous release, backup and source artifacts
were retained; no rollback was needed. This is a server-side recovery copy,
not a verified off-server backup.

Evidence: `openclaw-project/evidence/deployments/20261030T022448Z-webhook-0c48ade/deployment.json`.
The existing release process also recorded the dry run and release in
`/var/lib/agentai-ops/releases.log`. No Git push was performed.
