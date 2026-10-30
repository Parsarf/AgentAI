# Gap-closing backend audit (scope prefix BG)

Branch `product-phases-6-11`, HEAD `03662de` plus the in-progress tool_origin / tool_relay / cell_bridge / cell_config work (read where relevant, not judged). Read-only. Production is UNVERIFIED for every runtime claim. Paths are relative to `/Users/parsa/AgentAI/openclaw-project/platform/` unless absolute. No secret values were read or printed.

## 1. Scope & method

Read in full (line by line): `agentai_platform/{storage,files,artifacts,events,vault,gateway}.py`, `genui/{document,artifacts,runner,store,intent,images,runtime}.py`, `live/{ticket,gateway,now}.py`, `ops/{backup,crypto,restore,sets,destinations,hostconfig,cli,alerts,rotation,exposure,pins,housekeeping,diagnostics,inventory}.py`, `routing/{store,shadow,config}.py` and the head of `routing/classifier.py`, `lifecycle/{coordinator,worker,sleep,capacity,profiles,secrets_custody,litellm_admin,volumes,netpolicy,maintenance,workspace,supervisor_transport,native_wiring}.py`, `accounts/{files,media,streams,genui,browse}.py`. Skimmed: `ops/{monitor,hostprobe,probe_models}.py`, `lifecycle/{fleet_driver,broker,supervisor}.py`, `routing/{classifier tail,display,bench,policy,decision}.py`, `genui/{schema,prompts}.py`.

Method: static reading, plus two pure-function checks run with `python3 -I` against the repo (no DB, no network, no state): `genui.document.extract_documents` with three malformed documents (BG-002), `files.FileService._validate_one` with a valid `.json` file (BG-012), `events.redact` with five token shapes (BG-001). A repo-wide grep for f-string / concatenated SQL (BG clean list). Importer checks with `rg` across `*.py`, `*.service`, `deploy/`, management commands and `urls.py` before calling anything unused.

Not checked: the frontend rendering of documents (what the user actually sees on an approval card or button), production data and config (backup destination order, vault key location, LiteLLM duplicate-alias behaviour, host IPv6), `fleet_driver.py` and `supervisor.py` beyond a skim, `routing/{bench,display,policy}.py` beyond grep for SQL. Tests were not run.

Existing register entries not repeated here: BE-001..024, AG-001..022, IS-001..025 (notably BE-011 retention, BE-010 swallowed exceptions in general, BE-013 single global lane, IS-007 env sprawl, AG-009/BE-014 orphan modules, M-05).

## 2. File/module map (scope only)

| path | responsibility | consumers / entry | notes |
|---|---|---|---|
| `agentai_platform/storage.py` (96) | O_NOFOLLOW, dir-fd rooted private store; components `[A-Za-z0-9_.-]`, no leading dot | `files.py`, `artifacts.py`, `accounts/files.py` | sound (see clean list) |
| `files.py` (184) | upload validation, quota (2 GiB/account incl. artifacts), project file listing | `accounts/files.py` | BG-012, BG-006 |
| `artifacts.py` (230) | versioned artifacts, HMAC single-use download tickets, bundles | `accounts/files.py`, `chat_driver._capture_files` | BG-005, BG-006, BG-007, BG-017 |
| `events.py` (191) | per-task timeline, allowlisted payloads, redaction, SSE stream bookkeeping | `accounts/streams.py`, `chat.py`, `chat_driver.py`, `lifecycle/worker.py` | BG-001, BG-015, BG-016 |
| `gateway.py` (404) | `NativeGateway` RPC client (lines 67-234) and `SyntheticGateway` test double (237-404) | `chat_driver.py:25` imports both | BG-026 |
| `vault.py` (194) | AES-GCM per-account HKDF, AAD-bound rows, key ring file | `accounts/vault.py`, `accounts/browse.py:213` | sound |
| `genui/document.py` (452) | JSON-schema interpreter + safety scans for `lumina-doc` fences | `genui/store.py:178`, `genui/artifacts.py`, `accounts/files.py:238` | BG-002 |
| `genui/artifacts.py` (256) | stored documents, event-to-action binding, state | `accounts/genui.py` | BG-003 |
| `genui/runner.py` (264) | plan phase runner | `request_worker` (`runner=`), `accounts/genui.py` | BG-014, BG-029 |
| `genui/store.py` (203) | blocks persistence, `attach_cards` | `chat.py`, `chat_driver.py:617` | BG-006 |
| `genui/{intent,images,runtime,prompts,schema}.py` | requirements form template, historical card images (read-only), prompt building | `chat.py`, `accounts/media.py` | `images.py` read path is account-scoped |
| `live/{ticket,gateway,now}.py` | HMAC watch tickets, frame server (separate process), whitelisted who-is-deciding file | `accounts/browse.py:live`, systemd unit | BG-027 |
| `routing/*` | shadow classifier (off by default) | `request_worker` command only | BG-021 |
| `ops/{backup,crypto,destinations,sets,restore,hostconfig,cli}.py` | age-encrypted backup sets, scoped account restore, CLI | `ops.cli` via timers | BG-008..010, BG-024 |
| `ops/{monitor,hostprobe,alerts,exposure,pins,inventory,diagnostics,housekeeping,probe_models}.py` | monitoring and recovery inventory | `ops.cli`; `probe_models` is a manual tool | BG-023 |
| `ops/rotation.py` (65) | key / secret rotation helpers | tests only | BG-018 |
| `lifecycle/{coordinator,worker,sleep,capacity,profiles}.py` | operation state machine, idle sleep / wake, capacity | `worker_main`, `request_worker`, `signup_admin` | state machine looks sound |
| `lifecycle/{secrets_custody,litellm_admin,volumes,netpolicy,maintenance,workspace,native_wiring,supervisor_transport}.py` | custody files, key admin, loop volumes, nft policy, bounded restore extractor, workspace collector | supervisor, bridge | BG-019, BG-020, BG-022 |
| `lifecycle/broker.py` | worker-stage envelope | only `deploy/p4_broker_check.py` | already known orphan (docs/orchestration-audit P29) |
| `accounts/{files,media,streams,genui,browse}.py` | HTTP surface | `accounts/urls.py:28-60` | BG-004, BG-016 |

## 3. Features

| ID | name | status | flags | frontend | backend | evidence | prod verified? | notes |
|---|---|---|---|---|---|---|---|---|
| FEAT-BG-01 | Artifact download by single-use ticket | ACTIVE | | Files UI | `artifacts.py` | `urls.py:33-34`, `accounts/files.py:173-210` | unknown | tickets bound to account+artifact+version, 300 s, atomic consume |
| FEAT-BG-02 | Customer upload of project files | INCOMPLETE | flag-gated (`AGENTAI_UPLOADS_ENABLED`), BROKEN for `.json` | Files UI | `files.py` | `accounts/files.py:89`, `settings.py:99` | unknown | BG-012 |
| FEAT-BG-03 | Customer adds artifact version | ORPHANED | | none | `artifacts.py:86` | only `tests/test_files.py` | n/a | BG-017; product decision |
| FEAT-BG-04 | Project bundle (zip of latest versions) | ACTIVE | BROKEN-ish | form POST | `artifacts.py:178` | `urls.py:32` | unknown | BG-007 |
| FEAT-BG-05 | Generative documents inside answers | ACTIVE | | `lumina/src/gen` | `genui/document.py` | `genui/store.py:178` via `chat_driver.py:617` | unknown | BG-002, BG-003 |
| FEAT-BG-06 | Plan runner (launch, approve, skip, retry) | ACTIVE | | `PlanBlock.tsx` | `genui/runner.py` | `urls.py:57-60` | unknown | BG-014 |
| FEAT-BG-07 | Live watch frames | ACTIVE | | LiveScreen | `live/gateway.py` | `accounts/browse.py:live` | unknown | BG-027 |
| FEAT-BG-08 | Encrypted backup + scoped account restore | ACTIVE | | none | `ops/backup.py`, `ops/restore.py` | `ops/cli.py` | not verified | BG-008..010 |
| FEAT-BG-09 | Secret rotation | ORPHANED (library only) | doc drift | none | `ops/rotation.py` | no CLI choice, no importer outside tests | n/a | BG-018 |
| FEAT-BG-10 | Shadow routing classifier | EXPERIMENTAL | default off, third-party egress when on | none | `routing/*` | `request_worker.py:64,83` | unknown | BG-021 |

## 4. Findings

- **ID**: BG-001 | **Category**: privacy / secret redaction | **Severity**: Medium | **Confidence**: HIGH | **Effort**: S
  Description: the timeline redactor misses common credential shapes and does not touch dict keys, then the text is stored for 30 days and included in nightly backups. `activity` events carry an `output` field (raw tool output), so this is a real path for secrets typed or printed in a task.
  Files: `agentai_platform/events.py:48-57` (patterns), `:60-71` (`redact`), `:45` (`activity` allows `output`, `detail`, `label`).
  Evidence (executed `events.redact`): `sk-ant-api03-...` unchanged (the `sk-` pattern needs 8 alphanumerics straight after `sk-`, so `sk-ant-` and `sk-proj-` never match); `password=hunter2hunter2` unchanged (second pattern needs a quoted value); `Authorization: Bearer ...` unchanged; `AKIA...` unchanged; `{"password": "hunter2hunter2"}` becomes `{"[redacted]}` (key quote eaten, still lossy but not leaking); `{'api_key': 'hunter2hunter2'}` unchanged (only values are scanned). Redaction can also be switched off per account (`safety.is_on(... 'secret_redaction')`, `events.py:108`).
  Runtime impact: secrets seen by a tool can persist in `events.public_payload` (account-scoped, visible only to that customer and to backups) until the retention command prunes (`retention_accounts.py:34`).
  Recommended action: F (add Anthropic/OpenAI/AWS/Bearer/unquoted-assignment patterns; scan dict keys; add a test table of token shapes).
  Risk of changing: low; over-redaction only hides text in the timeline.

- **ID**: BG-002 | **Category**: error handling / robustness of model-visible validator | **Severity**: Medium | **Confidence**: HIGH (executed) | **Effort**: S
  Description: the document validator raises `AttributeError` (not `SpecError`) on structurally wrong container props, which the callers do not catch. `_children` calls `.get` on `props` and on each tab/accordion entry before any schema check (`validate_block` calls `_shape` first, line 235).
  Files: `genui/document.py:176-186` (`_children`), `:235` (`_shape` before `_check` at `:238`), `:421` (`extract_documents` catches only `SpecError, ValueError, KeyError, TypeError`), `genui/store.py:178` (no catch), `chat_driver.py:617-620` (`except Exception: pass`), `accounts/genui.py:30-42` (`_run` has no `AttributeError` branch), `genui/artifacts.py:241-256` (`strict_document`).
  Evidence: `extract_documents` on `{"blocks":[{"id":"a","type":"section","props":{"blocks":[3]}}]}` and on `{"type":"tabs","props":{"tabs":[1]}}` and on `"props":[1]` raised `AttributeError: 'int' object has no attribute 'get'` / `'list' object has no attribute 'get'`.
  Runtime impact: a single malformed model-written fence aborts `attach_cards` before the message is cleaned, so the raw ```lumina-doc fence (JSON) stays in the stored assistant message and no card is created, silently (the driver swallows it). `POST /v1/genui/artifacts/<id>/update` with such a body returns 500 instead of 400. The model is the attacker surface here (prompt injection from a browsed page can steer it to emit this), so it should fail closed with a fallback, not crash.
  Recommended action: F/D (make `_children`/`_shape` type-safe or run `_check` first; catch `Exception` narrowly in `extract_documents`; add the three cases as tests).
  Risk of changing: low.

- **ID**: BG-003 | **Category**: security (prompt-injection surface) | **Severity**: Medium | **Confidence**: MEDIUM (server side verified; what the UI shows next to the button was not checked) | **Effort**: M
  Description: model-authored documents may contain buttons / forms / approval cards whose visible label and the action actually executed are independent fields, and an `approval_request` block whose `planBlockId`/`phaseId` the model chooses. Execution still requires a user POST, so nothing fires without a click, but the click is not tied to what the user read.
  Files: `genui/artifacts.py:33-55` (`bindings`: `agent.request` takes `action.message`, `agent.approve`/`agent.deny`/`agent.retry` take model-supplied ids), `:151-221` (`event`: authorises by conversation and phase state only, then `chat.send(... message=action.message ...)` as a customer-provenance message, or `chat.runner.act(... 'approve')`), `genui/document.py:214-224` (`_check_actions` only checks the action kind is in the component's supported list), `genui/document.py:448-449` (prompt says agent-widget contents "come from Lumina, never from you", but nothing enforces it).
  Evidence: `event()` checks `plan.conversation_id == row.conversation_id` and `phase.state == 'awaiting_approval'` (`:185`), not that the card text matches the phase title or that the card was server-generated. `message` is `[:16000]` of arbitrary model text and arrives as the person's own next message (`ui='interactive'`).
  Runtime impact: an injected page can make the model emit "Continue reading" whose message is "Delete the files in my workspace" or an "Approve" card for a real gated phase; the click launders model text into user-authority input or approves a gated phase the user did not read. Low reach per attempt (one click, one conversation) but it defeats the purpose of approval gates.
  Recommended action: F (server-render approval cards from `plan_phase_runs`, reject model-supplied `agent.approve|deny|retry` bindings in model documents; show the exact message under a button, or require label == message for `agent.request`). Verify the frontend rendering before deciding scope.
  Risk of changing: medium (UX of existing documents).

- **ID**: BG-004 | **Category**: bug (functional) | **Severity**: Medium | **Confidence**: HIGH | **Effort**: S
  Description: `gen_asset` reads artifacts/files with `max_bytes=MAX_PREVIEW_BYTES` (200 KiB); `read_private` raises `ValueError('content exceeds bound')`, which `_mapped` turns into a generic 400. Any generated image or PDF in a document larger than 200 KiB cannot be shown.
  Files: `accounts/files.py:266` and `:272`, `files.py:24`, `storage.py:75-77`, `accounts/files.py:79-80`.
  Evidence: lines above; typical PNG/JPEG screenshots and charts exceed 200 KiB. The `download=1` path is capped the same way, so even the download fallback fails.
  Runtime impact: broken images in `image`/`gallery` blocks for realistic files; no log, only a 400.
  Recommended action: D (separate bound for inline media, e.g. 5-10 MiB, stream with `FileResponse`).
  Risk of changing: low; keep the sandbox CSP.

- **ID**: BG-005 | **Category**: unbounded growth | **Severity**: Low | **Confidence**: HIGH | **Effort**: S
  Description: `download_tickets` rows are never deleted. `gen_asset` mints and immediately consumes a ticket on every asset view (`accounts/files.py:261-265`), so each page view of a document with N pictures adds N rows, plus every Files-panel download.
  Files: `artifacts.py:138-174` (insert / consume, no purge), `accounts/management/commands/retention_accounts.py:12-37` (purges events, audit, sessions, tokens; not tickets or `event_streams`), `ops/restore.py:33` (lists the table as LIVE).
  Evidence: `rg download_tickets` finds only artifacts.py, the migration, restore.py and tests.
  Runtime impact: slow SQLite growth in the hot DB, included in backups. Also the in-process mint+consume is pointless indirection (the view already authorised the actor).
  Recommended action: F/A (delete `expires_epoch < now - 1 day` in the retention command; let `gen_asset` read through a direct authorised helper without a ticket).
  Risk of changing: low.

- **ID**: BG-006 | **Category**: bug (silent truncation) | **Severity**: Medium | **Confidence**: HIGH (code), MEDIUM (reach) | **Effort**: S
  Description: three listings use `ORDER BY ... created ASC LIMIT N`, so once a bucket exceeds N the newest rows are the ones dropped.
  Files: `artifacts.py:118-121` (200 artifact versions per project), `files.py:168-170` (200 files per project), `genui/store.py:114-119` (`data_blocks ... ORDER BY created_epoch,position LIMIT 100` per conversation; `add_display` creates a `display` block for many requests, `store.py:147-160`).
  Evidence: the SQL above. `gen_asset` resolves "latest version of file X" from the truncated `list_artifacts` result (`accounts/files.py:259-261`), so after 200 rows it can serve a stale version or 404.
  Runtime impact: in a long conversation, new cards stop rendering after about 100 data blocks; in a busy project new artifact versions vanish from the Files list. Counts of requests needed are unverified (likely hundreds); a heavy browser-using customer reaches it.
  Recommended action: D (order newest first and paginate, or add `after` cursor; query "latest by name" directly).
  Risk of changing: low-medium (UI paging contract; `UI_CONTRACT.md` documents `/blocks` as unpaged).

- **ID**: BG-007 | **Category**: unbounded growth / resource | **Severity**: Medium | **Confidence**: HIGH | **Effort**: S-M
  Description: `build_bundle` zips the latest version of every artifact in the project, including earlier bundles, then stores the zip as a new artifact (`capture`, new id each time). Each press roughly doubles the next bundle and consumes quota; the whole zip is built in memory inside the web request.
  Files: `artifacts.py:185-186` (no exclusion of `media_type == BUNDLE_MEDIA`), `:199-201` (only a 250 MiB uncompressed total), `:205-224` (reads each file fully with `max_bytes=250 MiB`, `BytesIO`, then a second copy via `getvalue()`), `:223` (`capture` -> new artifact, counts toward the 2 GiB quota at `:51-54`), `accounts/files.py:213-228` (synchronous view).
  Runtime impact: repeated "Download all" makes the project's bundles recursive; a project near 250 MiB can use roughly 3x that in a gunicorn worker (OOM risk on the 15.6 GiB host shared with cells; BE-002 context). Quota consumed without a clear user cause.
  Recommended action: D (skip bundle artifacts; stream to a temp file; bound total compressed size; maybe dedupe by project).
  Risk of changing: low.

- **ID**: BG-008 | **Category**: privacy / restore correctness | **Severity**: Medium | **Confidence**: HIGH (code), MEDIUM (frequency: restore is an operator action) | **Effort**: S-M
  Description: `restore_account` re-inserts `memory_entries`, `memory_terms` and `saved_choices` with `INSERT OR REPLACE` (backup wins), so anything the customer deleted after the backup comes back: forgotten memories (content restored from backup) and "forgotten" saved personal details. Only conversations have tombstones (`restore.py:109-110`). The file itself recognises this principle for the vault ("so a deleted card cannot return", `restore.py:37`) but not for memory or saved choices.
  Files: `ops/restore.py:20-21` (RESTORE list), `:128` (`INSERT OR REPLACE`), `agentai_platform/memory.py:114-127` (forget blanks content, sets `status='deleted'`, deletes terms), `agentai_platform/saved.py:33-34` (hard delete).
  Runtime impact: a restore within the 30-day backup window resurrects data the customer asked Lumina to forget. This matters most given the product's privacy stance.
  Recommended action: F (move deletions to tombstones or treat `memory_entries` / `saved_choices` as MERGE with live-wins; at minimum honour `status='deleted'` live rows; add a test).
  Risk of changing: low; restore tool only.

- **ID**: BG-009 | **Category**: restore design gap | **Severity**: Low | **Confidence**: MEDIUM | **Effort**: M
  Description: the DB restore is account-scoped and proven; the file bytes are not. The `customer-files` source is one tar of the whole storage directory with host-absolute member names, and the inventory's restore step is "Extract beside the restored app-db with the app stopped". There is no per-account file restore command, so restoring one customer's files by extracting the tar overwrites other accounts' files with backup-time copies (or the operator must hand-pick paths).
  Files: `ops/backup.py:105-117` (`archive.add(path, arcname=str(path).lstrip('/'))`), `ops/hostconfig.py:101-103`, `ops/inventory.py` (customer-files `restore` text), `ops/cli.py:63-65` (`restore-account` fetches only `app-db`).
  Runtime impact: operator error risk during an incident; cross-tenant rollback of file content. Note `RootStore.write_private` uses `O_EXCL` so a live app never overwrites, but `tar -x` does.
  Recommended action: E/D (add an account-scoped `restore-files` that extracts only `<account_id>/...` into a staging dir and compares to `project_files.sha256`).
  Risk of changing: low.

- **ID**: BG-010 | **Category**: backup retention correctness | **Severity**: Low | **Confidence**: MEDIUM | **Effort**: S
  Description: `_prune` treats any set that has a `manifest.json` as a candidate recovery point, but `_deliver` writes the manifest even when `manifest['complete']` is false. `select_keep` then keeps "newest per day / per ISO week", so an incomplete later set can take the day's slot and evict an earlier complete set from the same day or week. The docstring promises an incomplete set never causes pruning of older complete sets.
  Files: `ops/backup.py:183` (manifest delivered when `artifacts` exist), `:233-238` (`complete` list is manifest presence only), `:134-150` (`select_keep`), `:187` (prune runs only after a complete run, but then applies to all sets). Contrast `ops/sets.py:26-32` which does check `manifest['complete']`.
  Runtime impact: after a bad night followed by a good one on the next day, the earlier day can be left with only the incomplete set; recovery then needs `allow_incomplete`. Low frequency.
  Recommended action: F (filter `complete` by reading each manifest's `complete` flag before `select_keep`).
  Risk of changing: low.

- **ID**: BG-011 | **Category**: config bug / DoS | **Severity**: Medium | **Confidence**: HIGH (settings), MEDIUM (reach: Caddy / Vercel body limits unverified) | **Effort**: S
  Description: `DATA_UPLOAD_MAX_MEMORY_SIZE` is assigned twice; the later assignment (31,457,280, intended for file uploads) overrides the 200,000 meant for every API body, so all JSON endpoints, including unauthenticated ones, accept 30 MiB bodies that `json.loads(request.body)` fully parses before any field or size check.
  Files: `accounts/settings.py:58` (200000), `:100` (31457280, comment "25MiB batch cap plus multipart overhead"), `accounts/views.py:57` (parse), `:63` (`len(request.body)>131072` runs after parsing, only for `structured` endpoints). `FILE_UPLOAD_MAX_MEMORY_SIZE=0` (`:59`) is correct and unrelated.
  Runtime impact: memory / CPU amplification per request on login, signup and chat endpoints. Complements BE-002 (worker starvation) and BE-003.
  Recommended action: F (check `CONTENT_LENGTH` per route before reading; keep the 25 MiB limit only on the multipart upload view, e.g. a per-view `request.upload_handlers` or a size check in the wrapper).
  Risk of changing: low.

- **ID**: BG-012 | **Category**: bug (broken feature, gated) | **Severity**: Low | **Confidence**: HIGH (executed) | **Effort**: S
  Description: `.json` uploads are always rejected. `ALLOWLIST['.json'] = ('json',)` but `sniff()` never returns `'json'` (it returns `'text'` for JSON), and the `text` branch demands `'text'` in the allowed kinds. The `elif kind == 'json'` branch is dead.
  Files: `files.py:29`, `:39-55`, `:145-156`. `chat_driver.py:732` already special-cases `kind == 'text' and 'json' in kinds`, so the same bug was fixed on the assistant-file path only.
  Evidence: `_validate_one('a.json', '', b'{"a":1}')` raised `Rejected: content does not match the .json extension`. `tests/test_files.py:77` only asserts that invalid JSON is rejected.
  Runtime impact: customers cannot upload JSON once uploads are enabled (flag off by default).
  Recommended action: D (same special case in `_validate_one`; add the accept test).
  Risk of changing: none.

- **ID**: BG-013 | **Category**: error handling / data loss | **Severity**: Medium | **Confidence**: HIGH | **Effort**: S
  Description: `_capture_files` wraps the whole loop in one `try ... except Exception: pass`, so the first file that raises (storage quota `Conflict`, version cap, `IntegrityError` from a concurrent capture, a disk error) silently drops every remaining deliverable of the task and emits no event. Related: `path.replace('/', '_')` makes `a/b.txt` and `a_b.txt` the same artifact name, so different files become versions of one artifact; and `capture_or_version` reads the current version in one transaction and inserts in another (`artifacts.py:67-84`), so two captures of the same name race into a primary-key conflict.
  Files: `chat_driver.py:718-746` (`except Exception` at `:745`, loop at `:729`), `chat_driver.py:740-743` (name mapping), `artifacts.py:65-84`.
  Runtime impact: a customer's finished work is not saved and nothing tells them; the 2 GiB quota makes the `Conflict` path realistic for heavy users. (`workspace.collect` itself is bounded: 10 files, hidden names skipped; see clean list.)
  Recommended action: D (per-file try/except, emit an `error`/`artifact` event on failure, one transaction in `capture_or_version`).
  Risk of changing: low.

- **ID**: BG-014 | **Category**: race / stuck state | **Severity**: Medium | **Confidence**: MEDIUM-HIGH | **Effort**: M
  Description: `_spawn` marks a phase `running` in one transaction, then calls `chat._spawn`, then stores `request_id` in a second transaction. If the process dies (or `chat._spawn` succeeded but the second write failed) between the two, the phase is `running` with `request_id NULL` forever: `sync()` joins on `request_id` so it never advances, `advance()` returns early while any phase is `running` (`runner.py:80`), and the user cannot skip (needs pending / awaiting_approval / failed, `:191`) or retry (needs failed, `:187`). Only "stop" works.
  Files: `genui/runner.py:106-126`, `:50-60`, `:73-80`, `:186-198`.
  Evidence: the deterministic request key `phase-{block}-{phase}-{attempts}` (`:116`) means a re-run would be idempotent, but nothing re-drives phases with a NULL request.
  Runtime impact: a multi-phase plan stalls permanently after a worker restart at the wrong instant; low frequency, high annoyance, no self-heal.
  Recommended action: D (in `sync`, fail or re-spawn `running` phases with NULL `request_id` older than N seconds; allow skip/retry on them).
  Risk of changing: low.

- **ID**: BG-015 | **Category**: bug (low) | **Severity**: Low | **Confidence**: HIGH | **Effort**: S
  Description: in `EventService.events`, the loop variable `row` shadows the task-state row, so `'task_state': row[0]` returns the last event's `sequence` (an integer) whenever the page has events; it is the real state only for an empty page.
  Files: `events.py:127-141`.
  Evidence: `row` is reassigned by `for row in rows:` at `:135`; `task_state` is read after the loop. No in-repo consumer reads `task_state` from this endpoint (`rg task_state` hits other fields), which is why it went unnoticed; `tests/test_events.py` does not assert it.
  Runtime impact: wrong field in `GET /v1/requests/<id>/events`; latent for any client using it (UI_CONTRACT lists it).
  Recommended action: D.
  Risk of changing: none.

- **ID**: BG-016 | **Category**: input validation | **Severity**: Low | **Confidence**: HIGH | **Effort**: S
  Description: the SSE view parses `after` with `int(...)`, so negative values pass, open a stream row, then `EventService.events` raises `ValueError('invalid pagination')` inside the generator after the 200 response started. The polling view uses `isdecimal()` and returns 400.
  Files: `accounts/streams.py:80-82`, `:102`, `events.py:123-124`.
  Runtime impact: a broken stream (closed by `finally`), and an audited `stream.open` for nothing; cosmetic.
  Recommended action: D (reuse the `isdecimal` check).
  Risk of changing: none.

- **ID**: BG-017 | **Category**: dead / incomplete | **Severity**: Low | **Confidence**: HIGH | **Effort**: S (decision)
  Description: `ArtifactService.add_version` (customer-supplied new version) has no route and no caller outside tests, and it lacks the 2 GiB quota check that `capture` has.
  Files: `artifacts.py:86-110` vs `:51-54`; `rg add_version` -> only `tests/test_files.py`.
  Checked: `urls.py`, management commands, `accounts/*.py`.
  Recommended action: C (product decision: expose "upload new version" or delete); if kept, add the quota check first.
  Risk of changing: none.

- **ID**: BG-018 | **Category**: doc drift / orphaned ops | **Severity**: Medium | **Confidence**: MEDIUM-HIGH | **Effort**: M
  Description: `OPERATIONS.md` section 8 presents `rotate_provider_key`, `retry_pending_revocations` and `rotate_session_secret` as the rotation procedure, but `ops/rotation.py` has no CLI entry (`ops/cli.py:20` choices omit it), no systemd unit and no importer except tests, so rotation is a Python-REPL job. Design gaps in the code: (1) it replaces the key in custody and revokes the old key at LiteLLM, but a running cell received the old key at provisioning / start (`lifecycle/cell_config.py:211,237` read it from custody when building config), so the cell loses model access until restart, contradicting "a working secret at every moment"; (2) `pending.write_text(...)` then `os.chmod(0o600)` leaves a short world-readable window for a file holding revoked-but-secret keys (`rotation.py:32`, same pattern in `add_webhook_secret` `:50-51`); (3) `rotate_session_secret` rewrites the whole env file non-atomically (`:64`), so a crash mid-write corrupts the file holding every app secret; (4) `retry_pending_revocations` rewrites the queue without a lock.
  Files: `ops/rotation.py:19-65`, `OPERATIONS.md:87-98`, `ops/cli.py:20`.
  Runtime impact: the documented incident response (rotate everything after exposure) is slow and error-prone; tenant keys rotate without a defined cell restart step. Production use of these helpers is UNVERIFIED.
  Recommended action: D/E (add `ops rotate ...` subcommands that write via temp file + `fchmod` + rename, restart or re-inject the cell key, and update the doc).
  Risk of changing: medium (touches live secrets).

- **ID**: BG-019 | **Category**: reliability / orphan keys | **Severity**: Low | **Confidence**: MEDIUM-LOW (LiteLLM duplicate-alias behaviour unverified) | **Effort**: S
  Description: `ProviderKeys.issue` generates the LiteLLM key, then writes it to custody. A crash between the two leaves a budgeted key at the proxy that nothing records; the retry sees no key in custody and generates a second key with the same `key_alias=tenant`. If the proxy enforces unique aliases the retry fails forever; if not, the first key is an unrevocable orphan with its own budget.
  Files: `lifecycle/secrets_custody.py:130-138`, `ops/rotation.py:22-26` (same window).
  Recommended action: D (look up by alias before generating; record intent first).
  Risk of changing: low.

- **ID**: BG-020 | **Category**: reliability | **Severity**: Low | **Confidence**: MEDIUM | **Effort**: S
  Description: `SecretStore._create` opens the file with `O_EXCL` and then writes without fsync / temp-rename. A crash between create and write leaves an empty file; `_read` then raises `CustodyError('corrupt secret')` on every call (`TOKEN` needs 16+ chars), so `gateway_token` / `provider_key` / `issue` fail permanently for that tenant until someone deletes the file by hand.
  Files: `lifecycle/secrets_custody.py:52-72`, `:74-83`.
  Recommended action: D (write temp + `fsync` + `link`/rename; treat empty as absent).
  Risk of changing: low.

- **ID**: BG-021 | **Category**: privacy / resource | **Severity**: Low | **Confidence**: HIGH (code) | **Effort**: S
  Description: when routing shadow mode is enabled, every claimed customer message (scrubbed, first 2,000 chars) goes to a third-party classifier (`https://api.typesafe.ai/...`, `routing/config.py:14`). Default is `enabled: False` plus an owner switch, so this is a flag-gated egress to document. Separately, `ShadowRouter.before` is called on every claim, including re-claims of parked / deferred requests, spawning another classification thread and external call each time; `_started`/`_threads` entries are only removed in `after()`, which `RequestWorker._run` calls only for finished requests (not for Parked, Defer or exceptions), so the dicts leak per such request.
  Files: `routing/shadow.py:42-52`, `:77-90`; `request_worker.py:64-65,82-83`; `routing/classifier.py:14-16,31-33` (sanitize).
  Runtime impact: none while disabled (UNVERIFIED in prod). If enabled: duplicate provider calls and a slow memory leak in the long-lived worker; the privacy policy should name the processor.
  Recommended action: C (decide whether shadow routing ships) / F (dedupe per request id; pop in a `finally`).
  Risk of changing: low.

- **ID**: BG-022 | **Category**: security hygiene | **Severity**: Low | **Confidence**: LOW (needs host IPv6 facts; UNVERIFIED) | **Effort**: S
  Description: the cell firewall is an `inet` table but every match is IPv4-only (`ip saddr`, `ip daddr`). In the `input` chain an IPv6 packet cannot satisfy `ip saddr != @cell_sources return`, so non-established IPv6 traffic falls through to the final `counter drop` (host inbound IPv6 would be dropped), while in `forward` IPv6 matches no drop rule (policy accept). If the host or cells have IPv6 this is either an availability bug or an egress gap; if IPv6 is off everywhere it is inert. `classifier.py:_V4Connection` documents that the server has "no working IPv6".
  Files: `lifecycle/netpolicy.py:55-92`.
  Recommended action: F (add `meta nfproto ipv6` handling explicitly: return in input, drop cell IPv6 in forward; or disable IPv6 on the cells bridge and assert it).
  Risk of changing: medium (host firewall).

- **ID**: BG-023 | **Category**: recovery inventory gap | **Severity**: Low | **Confidence**: MEDIUM | **Effort**: S
  Description: `ops/inventory.ASSETS` lists the age key as the only "key outside the host" asset. The vault master key (`AGENTAI_VAULT_KEY_FILE`, deliberately never backed up: `OPERATIONS.md:192`), the live-frame secret, the artifact signing key (inside `accounts.env`) and the TypeSafe key are not inventoried, so the monitor cannot show that a restore of `app-db` (which includes `vault_items` ciphertext) is useless without an off-host copy of the vault key. The recovery doc says it; the machine-checked inventory does not.
  Files: `ops/inventory.py:ASSETS`, `vault.py:3-8`, `OPERATIONS.md:192`, `ops/restore.py:37`.
  Recommended action: E/G (add `vault-key` as `backed_up_by=''` with the restore note; keep it out of backups).
  Risk of changing: none.

- **ID**: BG-024 | **Category**: monitoring gap | **Severity**: Low | **Confidence**: MEDIUM (prod config unverified) | **Effort**: S
  Description: `ops verify`, `fetch`, `restore-account` and the monitor's `HostProbe` use `hostconfig.destinations(cfg)[0]` only. The shipped default destination list is a single local directory with `offsite: False` (`hostconfig.py:27`), and the `check` command reports the missing off-server destination as a "LAUNCH BLOCKER" that does not fail the exit code (`cli.py:33,35`). If production lists an offsite destination second, drills and freshness checks look only at the local copy.
  Files: `ops/cli.py:33-35,51`, `ops/hostconfig.py:27,126-127`.
  Recommended action: F (verify every destination; make the missing-offsite problem fail `check`). Cross-check with PRODUCTION_VERIFICATION_2026-10-29.md for the real destination list.
  Risk of changing: low.

- **ID**: BG-025 | **Category**: race (narrow) | **Severity**: Low | **Confidence**: MEDIUM | **Effort**: S
  Description: `launch_plan` reads the block (state and plan) outside the transaction, then inside it re-checks only `status == 'draft'`, not `version`. A concurrent `save_state` (another tab) between the read and the transaction is silently overwritten: the older plan is stored as the "approved" revision and written back over `state_json`.
  Files: `chat.py:390-415` (`fresh` selects `version` at `:403` but only `status` is tested at `:404`).
  Runtime impact: the user launches a plan different from the one on screen; narrow window.
  Recommended action: D (compare `fresh['version'] == version`).
  Risk of changing: none.

- **ID**: BG-026 | **Category**: dead-in-prod / duplication | **Severity**: Low | **Confidence**: HIGH | **Effort**: S
  Description: 168 of `gateway.py`'s 404 lines (`SyntheticGateway`, `:237-404`) are a test double living in the production module; `chat_driver.py:25,904` imports it and exposes `synthetic_gateway_factory`. The module docstring says it is never installed in a request path. Checked importers: only `chat_driver.py` (import + factory) and tests. Keeping it in the shipped module means a production import of a fake gateway is one wrong factory away.
  Files: `gateway.py:237-404`, `chat_driver.py:25,904`.
  Recommended action: B (move to `agentai_platform/testing/` or `tests/`).
  Risk of changing: low (update imports in tests).

- **ID**: BG-027 | **Category**: availability (low) | **Severity**: Low | **Confidence**: MEDIUM | **Effort**: S
  Description: the frame gateway allows 12 concurrent waiters globally and a ticket is replayable for its 120 s lifetime from any client. One viewer with a handful of parallel loops (or a leaked ticket) can occupy all 12 slots and make other customers' live view return 429. The design note ("view only, a leaked ticket looks at one task's frames") is correct about confidentiality; availability across tenants is the gap.
  Files: `live/gateway.py:28,36,69-70`, `live/ticket.py:12`.
  Recommended action: F (per-request-id slot cap, e.g. 2; per-IP limit in Caddy).
  Risk of changing: low.

- **ID**: BG-028 | **Category**: doc drift | **Severity**: Low | **Confidence**: HIGH | **Effort**: S
  Description: `events.py` docstring (`:9`) and `EventService.prune_expired` (`:186`) describe the 30-day timeline retention, but nothing in production calls `prune_expired`; the real purge is a raw SQL `DELETE` in `retention_accounts.py:34`. Two implementations, one used (`rg prune_expired` -> tests only). Same for `artifacts` docstring vs `download_tickets` (BG-005). Fine today, but a change to one will not change the other.
  Files: `events.py:186-191`, `accounts/management/commands/retention_accounts.py:32-34`.
  Recommended action: B (call `prune_expired` from the command, or delete it).
  Risk of changing: none.

- **ID**: BG-029 | **Category**: state hygiene | **Severity**: Low | **Confidence**: MEDIUM | **Effort**: S
  Description: `PlanRunner._stop` cancels pending / awaiting phases and in-flight requests but leaves `ui_blocks.status = 'launched'`; `_announce_completions` requires every phase to be completed or skipped, so a stopped plan is never announced and the block stays "launched". `_run` reports `status='stopped'` from phase states, so the UI copes, but `edit` / `_own` still treat the plan as running.
  Files: `genui/runner.py:216-227`, `:128-140`, `genui/store.py:17-36`.
  Recommended action: D/C (decide a terminal `stopped` status).
  Risk of changing: low.

- **ID**: BG-030 | **Category**: swallowed exceptions (in scope, consolidated) | **Severity**: Low | **Confidence**: HIGH | **Effort**: S
  Description: places where failures disappear with no log or event, beyond the general BE-010: `runner._audit` (`runner.py:157`: the audit row for approve / skip / retry / stop is best-effort, so the trail can silently lack decisions), `runner._stop` queue.cancel (`:225`), `chat_driver` `attach_cards` (`:619`) and `_capture_files` (`:745`), `lifecycle/worker._say` (`:126`), `ops/backup._deliver` (`:225`, a destination failure keeps no reason in the report) and `_prune` (`:239`), `ops/hostconfig.tenants` (`:90`: a custody-db read failure returns `[]`, so tenant cell archives are silently dropped from the set; the set is then still marked complete because `tenant-cells` is excluded from `expected_assets`, `hostconfig.py:119`).
  Last point is the notable one: a transient `custody.sqlite3` error removes every tenant cell backup from a "complete" set.
  Files as cited.
  Recommended action: F (log category + counts; make `tenants()` failure a set failure).
  Risk of changing: low.

## 5. Verified clean (checked and found sound)

- **Path traversal / symlink races in storage**: `storage.py` validates every component (no dots, slashes, non-ASCII), opens each directory with `O_DIRECTORY|O_NOFOLLOW` through fd chaining, leaf with `O_NOFOLLOW`, writes with `O_EXCL`; the store root must be a private 0700 direct directory. Storage keys are `[account_id, 'artifacts'|'files', id, version]` built from DB rows, never from client input (`artifacts.py:61,107`, `files.py:112,184`).
- **Tenant isolation in artifacts, files, tickets, media, genui assets**: every SQL in `files.py`, `artifacts.py`, `genui/store.py`, `genui/artifacts.py`, `accounts/files.py`, `accounts/media.py`, `images.py` carries `account_id = ?` (the account from the session, or from the ticket row, never from the URL); IDs are regex- or `identifier()`-checked. `consume_ticket` takes the account from the stored ticket row and updates `consumed_epoch IS NULL` atomically, so tickets are single use under concurrency; tokens are stored as HMAC hashes. `gen_asset` requires the file to be referenced by the same account's document and the document's own project. `card_image` is account-scoped and returns the same 404 shape for other accounts.
- **Download response headers**: attachment disposition, `Cache-Control: no-store`; preview and asset responses carry `Content-Security-Policy: default-src 'none'; sandbox`, `nosniff`; non-allowlisted media is refused for inline view.
- **Live tickets**: HMAC-SHA256 with `compare_digest`, `v1.` prefix, request id and expiry bound in the signed body, 120 s TTL; gateway never touches the DB and serves only `request_id/out/live.jpg` under a `[a-f0-9]{32}` regex (no traversal); `now.json` is whitelist-only, size-capped, and written atomically.
- **SQL built from strings**: repo-wide grep of `execute(f"...")`, `%`-formatting and concatenation across `agentai_platform/` and `accounts/` found only (a) `ops/restore.py` (table names from the fixed `SCOPE` lists after `check_classified`, tombstone ids parameterised), (b) `chat_driver.py:117` (column list built from code constants), (c) `memory.py:83` (placeholder count only), (d) `accounts/views.py:281` (table from a four-entry dict). No injectable string reaches SQL.
- **Restore**: builds a new file from the live DB, attaches the backup read-only, refuses unclassified tables, neutralises schedules, watchers, browser profiles, tasks, requests and reservations, and proves other accounts' rows, ledger rows, integrity and FKs before returning (`restore.py:161-173`); `vault_items` and billing / identity are never restored. (Gaps are BG-008 and BG-009 only.)
- **Backup encryption and key handling**: `AgeCrypto` takes public recipients only, refuses to overwrite, verifies the age header; plain copies live only in a 0700 work dir and are removed in `finally`; manifests carry hashed tenant labels; `sets.fetch` checks ciphertext size and hash, decrypts, re-checks the plaintext hash, then type-verifies; destination names pass `safe_name` (no `..`). Off-host decryption identity is never on the host.
- **Vault crypto**: AES-256-GCM, per-account HKDF key, fresh 12-byte nonce, AAD binds account, kind and item id (swapped rows fail), key file must be 0600 and well-formed, CVV never accepted, `open_item` is called from exactly one place (`accounts/browse.py:213`, after the customer picks the saved item, account-scoped).
- **Workspace collection** (`lifecycle/workspace.py`): dir-fd walk with `O_NOFOLLOW`, hidden and oddly named files skipped, extension allowlist, 10 files / 2 MiB / 8 MiB / depth 4, runtime persona files skipped. **Quarantined restore extractor** (`maintenance.py`): regular files and dirs only, manifest-first tenant binding, normalised names under `data/`/`auth/`, `O_EXCL|O_NOFOLLOW`, member and size bounds.
- **Lifecycle state machine** (`coordinator.py`): idempotency keys with request hashes, generation fencing, lease + fence checks on every receipt, operator grant rechecked inside the write transaction, system requests limited to stop / backup / start, a single account slot; wake / sleep decisions are pure (`sleep.py`) and never stop a cell with running, queued or approval-waiting work. **Supervisor socket**: `SO_PEERCRED` on both ends, 8 KiB framing, duplicate-field rejection, fixed action set.
- **Secret custody files**: host-owned 0600, `lstat` private checks, `O_EXCL|O_NOFOLLOW`, tenant regex `aa-[a-f0-9]{32}`, destroy removes exactly one tenant directory. **Volumes**: fixed argv lists, tenant and size validated, mount `nodev,nosuid`, purge refuses a mounted volume.
- **Alerts**: fixed fields, ASCII-only, secret-pattern filter, cooldown + recovery message, no caller-chosen destination. **Diagnostics**: counts and hashed labels only.
- **Plan runner concurrency**: the pending-to-running claim is an atomic conditional `UPDATE ... WHERE state='pending'` (`runner.py:108-113`); user actions re-authorise and every attempt is audited.

## 6. Looks bad but is fine

1. `ops/restore.py` and `ops/hostconfig.py` build SQL with f-strings; every interpolated name comes from fixed lists or the DB schema after a classification check, values are bound (see clean list).
2. `consume_ticket` and `download` accept an unauthenticated GET with the secret in the query string. That is the design (single use, 5 minutes, bound to account and version, HMAC-hashed at rest); replay fails because `consumed_epoch` is set atomically. The only residue is BG-005 (rows never deleted).
3. `LocalDir.list` does `rglob('*')` on every call, which looks quadratic; the backup tree holds at most about 16 sets, so cost is trivial.
4. `ArtifactStore.event` writes `INSERT OR REPLACE` into `gen_artifact_events` and re-runs after 60 s of `pending`; the deterministic queue key (`uie...`) makes the re-send idempotent, as the comment says.
5. `host_create` / `request_system` bypass operator grants: both are host-local (CLI / worker) and bounded (create only for active accounts within capacity; system limited to stop / backup / start), as their docstrings state.
6. `vault.add` takes `accepted=True` from the view without UI proof: `accounts/vault.py:51` hardcodes it after the route's own validation; the disclaimer is enforced client-side by design (reviewed as product, not a server gap).

## 7. Cross-scope links

- BG-002 / BG-003 -> frontend: `lumina/src/gen/{schemas.ts,safety.ts,ChatBridge.tsx}` must be checked for what approval cards and buttons display versus `action.message`; `gen_registry.json` is generated from `schemas.ts` (a drift test exists).
- BG-004 / BG-006 -> frontend Files panel and `ChatBridge.tsx:45` (`/blocks` is unpaged).
- BG-011 -> Caddy / Vercel request body limits (`platform/deploy/caddy/*`, `vercel.json`): not read in this pass.
- BG-018 -> `cell_config.py:211,237` (in-progress file) for how a running cell receives a rotated key.
- BG-021 -> `docs/` privacy statements and `platform/PRIVACY*.md`: list the classifier processor if shadow routing is ever enabled.
- BG-022, BG-024 -> PRODUCTION_VERIFICATION_2026-10-29.md (IPv6 state, backup destination order).
- BG-026 -> AG-014 (chat_driver god file): the synthetic factory lives there too.

## 8. Open questions for the maintainer

1. Should approval cards and `agent.request` buttons be server-rendered / label-bound (BG-003), or is the model-authored label considered acceptable because the user always clicks?
2. Is a restore expected to resurrect forgotten memory and saved details (BG-008), or should memory / saved choices be live-wins?
3. Does production run with `AGENTAI_UPLOADS_ENABLED=1`? If yes BG-012 is a live bug; if not it can wait.
4. Which destination is first in `/etc/agentai-ops/config.json` (BG-024), and is the offsite entry present?
5. Is customer "upload a new version" (BG-017) planned? If not, delete `add_version`.
6. Where does the vault key file live, and is its off-host copy tracked anywhere besides OPERATIONS.md (BG-023)?
7. Is LiteLLM's `key_alias` unique in the deployed version (BG-019)?
8. Should rotation become an `ops` subcommand with a defined cell-restart step (BG-018)?
