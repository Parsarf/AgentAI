# Phase 8 — project files, versioned outputs and usable bundles

Status: **build READY; uploads disabled by default (documented scan
capability flag); storage unconfigured on production so routes fail closed
(503)** — activation is a host operator step (storage dir + signing key +
optional uploads flag). Deployed 2026-10-08 as release
`20261008T091500Z-files`. Full live end-to-end artifact proof stays in
Phase 15/17.

## Implemented

- Migration SQL0007 + Django0011: `project_files` (quarantined/scanned
  states, sha256, storage_ref) and `download_tickets` (HMAC-only storage,
  5-minute expiry, atomic single-use consumption).
- `agentai_platform/storage.py`: race-safe private root store. Every path
  component is validated (ASCII, no dots-leading, no separators); parent
  directories open with O_DIRECTORY|O_NOFOLLOW and leaves with O_NOFOLLOW —
  the intermediate-symlink race from plans/phase-8b.md is closed by
  construction and covered by tests (directory swapped for a symlink after
  validation still fails to open).
- `agentai_platform/files.py`: launch allowlist (.txt/.md/.csv/.json/
  .py/.js/.ts/.tsx/.jsx/.html/.css/.sql/.pdf/.png/.jpg/.jpeg); content
  sniffing independent of declared type (UTF-8 without NUL for text, JSON
  must parse, PNG/JPEG/PDF signature checks, encrypted PDFs rejected);
  10MiB/file, 25MiB/batch, 10 files/batch; 2GiB account storage accounting
  shared with artifacts; scanned content only is servable; quarantined
  content never served.
- `agentai_platform/artifacts.py`: immutable versioned capture bound to
  account/project/task with sha256+size; customer add-version; listing
  joins task state; single-use download tickets minted only by the owning
  account (exact account/object/version binding; replay/guess/expiry
  denied); project bundles as reproducible ZIPs (latest versions +
  manifest.json with paths/hashes/provenance/task; 250MiB uncompressed
  bound; content missing from storage yields a labeled partial bundle,
  never invented data).
- Routes: `GET/POST /v1/projects/{id}/files` (uploads multipart when
  `AGENTAI_UPLOADS_ENABLED=1`, else honest 503 `uploads_not_enabled`),
  `.../files/{id}/preview` (sandboxed CSP `default-src 'none'; sandbox`,
  nosniff, bounded 200KiB), `POST .../bundle`, `POST
  /v1/artifacts/{id}/versions/{n}/ticket`, `GET .../download`.
  `artifacts` leaves the disabled-route list; task list/create, streams,
  pause remain Phase 9.
- Chat page Files & results section: artifact versions with hash/size and
  Download buttons (ticket → redirect), uploaded files with scan state,
  upload form only when the scan capability is on, bundle builder. Storage
  unconfigured renders an honest empty panel.

## Checks actually run (2026-10-08)

- 9 service tests (storage traversal/symlink-race, allowlist, content
  mismatch, batch limits, scoped listing, capture/versions, ticket
  lifecycle, bundle manifest/versions, quota).
- 6 HTTP tests (fail-closed without storage, upload validation +
  ownership + cross-account 404, uploads disabled without flag, ticket
  flow single-use + scoped, bundle form flow + accounting, page section).
- Full suites: 133 core tests OK (incl. test_files/test_telegram),
  59 Django tests OK, concurrency + loopback HTTP scripts PASS, Vercel
  routing PASS. CI workflow extended with `tests.test_files`.

## Deployment 2026-10-08

Release `20261008T091500Z-files` deployed (hash-verified); SQL0007/
Django0011 applied during a stopped-services window; post-migration
backup `backup-20261008T091800Z-postmigrate.sqlite3` (integrity ok).
Origin verification: files route 401 anonymous, chat 302, stylesheet 200,
internal 404, readiness honest. **Process lapse repeated:** the
pre-migration backup step was again skipped (the Phase 7 correction was
recorded but not applied to a checklist); post-migration backup taken
immediately. Deploy backups must move BEFORE the stop step in future
releases.

## Not claimed / gates

- Storage is unconfigured on production: no AGENTAI_STORAGE_DIR or signing
  key yet, so every file/artifact route answers 503 for signed customers
  and the UI shows the honest unconfigured panel. Activation = create
  private storage dir + generate signing key in accounts.env (host
  operator step), then optionally enable the uploads scan flag.
- No live end-to-end artifact proof with a real customer task (Phase 17);
  previews of HTML stay download-only (never rendered in the dashboard
  origin); no archive inputs; PDF page-count enforcement pending a safe
  parser (beyond signature check) before uploads enable.
- Multi-account storage accounting is enforced at admission; background
  reaper/expiry of tickets is unnecessary (expiry checked at use).

Rollback: code-only to `20261006T073000Z-telegram` refuses the newer
schema; restore requires the verified post-migrate backup into a fresh
state root per runbook.

Evidence: `evidence/product/phase-08/20261008T091500Z/`.
