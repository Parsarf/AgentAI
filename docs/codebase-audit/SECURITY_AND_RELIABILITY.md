# Security and reliability risks

> **UPDATE 2026-10-29:** production was verified over SSH after this document was written. Statements below that production is "unverified" are superseded for the items in [PRODUCTION_VERIFICATION_2026-10-29.md](PRODUCTION_VERIFICATION_2026-10-29.md) (live host is Hostinger `179.236.71.203`; IONOS is dead; IS-002 and the tool-origin v2 drift confirmed; IS-004 resolved; M-01 latent, not observed).

Audit date 2026-10-29. Branch `product-phases-6-11`, HEAD `03662de` plus uncommitted tool_origin/tool_relay/cell_bridge/cell_config work (IN PROGRESS, not judged). **Production is UNVERIFIED**: SSH attempts failed (L-01..L-03), so every item below is derived from repository code and config. No secret values are quoted; `ssk-key` contents were never read (only its 40-byte PEM header was seen by the infra investigator). Severity totals are approximate. Master and source IDs match `TECHNICAL_DEBT.md`.

Owner priority (memory: privacy over task guardrails): customer privacy and data leakage come first; no new task limits are proposed here beyond fail-closed bookkeeping fixes.

## 1. Customer privacy and data egress

| ID | Risk | Sev | Conf | Evidence pointer | Mitigation |
|---|---|---|---|---|---|
| M-02 (AG-002, AG-003, IS-014) | Raw JPEG screenshots of the customer's browser window are sent to `api.typesafe.ai` on every JEV step (popup, panel, human check, picture mode); scrub is text-only; switch `browser_optimization` and `OptimizationGate` do not control the live path; `personal_data_scrub` is per-account switchable; trace files keep up to 400 chars of raw model answer. Sign-in and payment pages stop before any model, which limits but does not remove exposure (cart, order summary, addresses, account pages). Prod key presence unverified. | High | HIGH (code), MEDIUM (frequency) | `browse/ladder.py:333,397,606`; `browse/loop.py:208-216`; `browse/service_main.py:72-77`; `switches.py:42-49`; `plans/product/privacy.md:17` | Decide (class C): send images only when no controls are listed or only on opt-in; wire `browser_optimization` into `jev_for` (or retire switch and gate); document in privacy notice and switch text; ask TypeSafe for no-retention terms. Expect JEV accuracy trade-off. |
| AG-012 | With `jev_routing` on, every re-claim after a Defer re-sends the sanitised message to TypeSafe. Switch default off. | Low | HIGH | `request_worker.py:65,75-77` | Classify once per request id. |
| AG-021 | "Never presses payment" is enforced in code only inside `lumina_browser`; cell keeps `exec`/`web_fetch` with sandbox off. Boundary is container isolation plus egress firewall (prod state unverified). | Medium | MEDIUM | `lifecycle/cell_config.py:25,53-56` | State the guarantee scope precisely; consider denying `exec` for accounts needing strong assurance. |
| BE-011 | Retention command scheduled by nothing in repo; `chat_messages` and `conversations` never deleted; 90-day cutoff uses `created_at`. Customer-data lifetime is undefined in practice. | Medium | MEDIUM | `retention_accounts`; `deploy/README.md:83-85` | Decide the retention contract, then schedule the command. Requires owner decision before any deletion. |
| OP-003 (in M-03) | `lumina-cost-audit/browsing-log-20261028/` and `browsing-audit-*/dinner/` contain request-level exports of the owner account's browsing. Untracked, un-ignored. | Medium | MEDIUM | `lumina-cost-audit/` | Ignore or relocate before any commit. |
| ST-020 | 183 tracked files under `evidence/` incl. `.log` and `.png`; contents not reviewed for emails or tokens. | Low | HIGH | `evidence/**` | grep for emails/tokens before the repo is ever shared. |
| OP-012 / OP-011 | `browse/service.py:519` `chmod 0o777` on screenshot dir shared with a container; predictable `/tmp` staging name in `bin/phase6/manage-connectors.py:115`. Only Sonar items with a privacy angle. | Low | MEDIUM | files cited | Tighten dir mode (stage runs as uid 1000); use `mkstemp`. |
| BE-019 | Download ticket consumed on GET (prefetchers burn it); `Content-Disposition` mishandles odd names. Not a leak, a reliability defect. | Low | HIGH | `accounts/files.py:97-101,155` | Use Django `content_disposition_header`; consume on first successful byte. |
| IS-022 / FE-010 | Live-view ticket and `?path=` appear in query strings (access logs); ticket HMAC, 120 s, bound to account+task. Mermaid `securityLevel` and markdown link filter regex not reviewed. | Low | MEDIUM | `LiveScreen.tsx:33`; `gen/components/mermaid.tsx` | Confirm mermaid config; keep logs free of query strings. |

## 2. Secrets and repository hygiene

| ID | Risk | Sev | Conf | Evidence pointer | Mitigation |
|---|---|---|---|---|---|
| M-03 (IS-001, OP-001, ST-003, GH-009) | Untracked ed25519 private key `ssk-key` (+ `.pub`) at the git root; mode 0600; NOT ignored (`*.key`/`*.pem` do not match the name); never in history. One `git add -A` publishes it to a GitHub-backed repo. Also about 800 MB other untracked, un-ignored material (zips, tarballs, jev-*, `.claude/worktrees` 573 MB). | High | HIGH | `git check-ignore -v ssk-key` empty; `git log --all -- ssk-key` empty | Phase 0: add `ssk-key*` and root-level archive patterns to root `.gitignore`; move key to `~/.ssh` or a vault. Owner to confirm what it opens (L-02 says it authorizes nothing on the tested host). Rotate only if it was ever shared. |
| GH-002 (in M-06) | `node_modules/` ignore pattern does not match symlinks: `lumina-character/node_modules` shows `??`; a node_modules symlink was committed once (90c5277, removed c0c7844). | Medium | HIGH | `.gitignore` | Use `node_modules` without trailing slash. |
| OP-006 | `jev-browser/.env`, `jev-window-core/.env` protected only by nested `.gitignore` in untracked dirs plus root `.env` rule. Values not read. | Low | MEDIUM | `git status --ignored` | Fine in practice; move prototypes out of the tree. |
| GH-010 | History pattern scan found no key-shaped additions; limits: unprefixed base64/hex, binaries, tests excluded. | Low | MEDIUM | `git log -G` | Run gitleaks locally. |
| IS-018 | No secret shapes in tracked files; `.env` ignored (mode 0600). Residual: public VPS IP, host fingerprint and an account id are tracked. | Low | HIGH | regex scan | Accept; review evidence logs (ST-020). |
| OP-010..012 | See section 9 (SonarQube). | - | - | - | - |

## 3. Host and access

| ID | Risk | Sev | Conf | Evidence pointer | Mitigation |
|---|---|---|---|---|---|
| L-01 | Deployment target drift: repo runbooks name IONOS `69.48.206.62` (timed out 2026-10-29); owner `~/.ssh/config` `lumina` host is Hostinger `179.236.71.203`. Either production moved or the runbooks target a dead server; the password-SSH finding (IS-002) must be re-verified on the real host. | High | HIGH | 17 tracked files; `~/.ssh/config` | Phase 2 VPS checklist; then update docs. |
| IS-002 | Operator access is root over SSH with a password kept in `openclaw-project/.env`; docs list key login as follow-up; `privacy.md` says key-only; root reads all tenant data. | High | MEDIUM | `bin/ssh-server:21-24`; `OPERATIONS.md:97` | On the real host: `sshd -T`; adopt key login, then disable password and root-password login; keep console access. |
| IS-013 | Root units (`agentai-browse`, `cell-bridge`, `supervisor-native`, `ops-*`) lack `ProtectSystem/ProtectHome/PrivateTmp/PrivateDevices`; browse parses customer web content as root with `CAP_DAC_OVERRIDE`. | Medium | HIGH | unit files | Add sandbox directives on a canary; review capability need. |
| IS-012 | Owner gateway mounts `docker.sock` (by design); `cap_drop` only NET_RAW/NET_ADMIN; postgres lacks `cap_drop`. | Medium | HIGH | `docker-compose.production.yml:55-56` | Preserve; optional `cap_drop: ALL` + `read_only` after testing. |
| IS-011 | Owner dashboard: lockout keyed to 127.0.0.1 via tunnel, no Host validation (DNS rebinding with existing session), `docker exec` into gateway/postgres; unit file not in repo. | Medium | MEDIUM | `dashboard/app.py:156-162,817,82` | Host allowlist; commit the unit; check privilege. |
| IS-021 | Tool relay authenticates cells by reusing the LiteLLM key over plain HTTP on the bridge; 20 failures/min/source. | Low | MEDIUM | `tool_relay.py:34` | Preserve; document in threat model. |
| AG-019 | (IN PROGRESS code) proof file owner not checked; hostile cell could forge its own proof. Defends misattribution, not hostile cells. | Low | LOW | `lifecycle/tool_origin.py:62-90` | Optionally require uid 1000 and nonce freshness. |
| AG-008 | (IN PROGRESS) any origin-proof failure gives one fixed refusal; failure of hook install is silent on restart. Safe (fail-closed) but invisible. | Medium | MEDIUM | `tool_relay.py:119-122`; `cell_config.py:183-188` | Distinguish transient vs ownership refusals; emit an event. |
| IS-025 | HSTS, `__Host-` cookies, CSP, no CORS: good. Gaps: preload, Permissions-Policy, COOP; Caddy static responses carry defaults. | Low | HIGH | `settings.py:50-51` | Optional Caddy `header` block. |

## 4. Tenant isolation

Positive findings (all from code reading; no live isolation test was run):

- Every customer route derives `account_id` from the session via `customer_scope` (verified identity + epoch + active membership), never from request input; `BoundaryMiddleware` rejects `account`, `tenant`, `session`, `deployment_id` query keys and `X-Account-Id`-style headers; services re-authorize and scope SQL by `account_id`. No IDOR was found in the routes read (BE section 3a). Denials are a uniform audited 404.
- Per customer: gVisor container on a separate Docker engine, own volume, own LiteLLM virtual key and budget; nft table drops cell-to-host input except the model relay (4000) and tool relay (4100); private ranges and metadata blocked. Browser stages run `--read-only --cap-drop ALL --pids-limit 256`.
- Root bridge uses a unix socket 0660 with SO_PEERCRED and a method allowlist; the app user never holds a docker handle or cell token.
- Vault: AES-GCM with per-account HKDF key and AAD-bound rows.

**What was NOT audited** (do not read the above as a clean bill): `gateway.py`, `events.py`, `artifacts.py`, `files.py` service internals, `storage.py`, `genui/*` (HTTP surface and a skim only), `routing/*`, `ops/*` (only `restore.py`), `dashboard/app.py` beyond auth, OpenClaw 2026.9.6 internals, the live nftables/ufw rules and cell configs (IS-005 says the checked-in nft sample is stale), and any runtime test of cross-tenant access.

Risks:

| ID | Risk | Sev | Conf | Evidence | Mitigation |
|---|---|---|---|---|---|
| IS-005 | Checked-in `agentai_cells.nft.generated` has no doors for 4000/4100 whereas `netpolicy.py` emits them; real file generated at runtime; misleading on host rebuild. | Medium | MEDIUM | `cells-docker/` | `nft list table inet agentai_cells` on the host; delete or regenerate sample. |
| AG-004 | Single lane: one slot, one cell, one stage; possible starvation of an older account by the cell holder (by reading). Fairness, not leakage. | Medium | MEDIUM | `request_queue.py:147-175` | Product decision (private beta limit). |
| BE-008 | `ssrf.check_url` does not pin the resolved address (docstring admits it); inert until connectors are live. | Low | HIGH | `accounts/connections.py` | Pin address before enabling connectors. |
| M-08 (AG-010) | SSRF/private-range policy duplicated four ways (`runner.mjs`, `native_runner.py`, `ssrf.py`, `netpolicy.py`); a rule change must land in all. | High (architecture) | MEDIUM | files cited | Shared test vector first; consolidate after engine decision. |

## 5. Availability and DoS

| ID | Risk | Sev | Conf | Evidence | Mitigation |
|---|---|---|---|---|---|
| BE-002 | Authenticated SSE `/v1/tasks/<id>/stream` holds the only sync gunicorn worker up to 45 s (timeout 15 kills it); unused by React. One customer can stall the app. | High | MEDIUM | `streams.py:60-121`; `gunicorn.conf.py` | Remove or isolate the route. |
| M-04 (BE-003, IS-009) | Per-IP limits collapse to a shared bucket behind Vercel; one abuser exhausts login/signup for all (five signups per hour site-wide). `backend.getlumina.pro` also publicly reachable. | High | MEDIUM | `middleware.py:14-19`; `Caddyfile.getlumina:24-25` | Derive real client IP at Caddy from Vercel (trust only Vercel ranges or a shared-secret header), or document limits as per-email only. |
| BE-013 | One global running slot and a SQLite write per authenticated request cap throughput. | Medium | HIGH | `middleware.py:63-69` | Meter mutations only; product decision on slot. |
| BE-004 | 8192-byte cap 413s Stripe/Telegram webhooks above 8 KB; Stripe retries then disables endpoint. | Medium | MEDIUM | `middleware.py:23` | Exempt the two webhook paths. |
| AG-005 | PARK_LIMIT expiry does not end the run; bounded in practice by browse 300 s / 600 s limits. | Medium | MEDIUM | `chat_driver.py:363-366` | Call the stop path on timeout. |
| AG-011 | `BrowseService.jobs` never evicted (root process, MemoryMax 384M). | Low | MEDIUM | `browse/service.py:172` | Evict finished jobs after retention. |
| IS-003 | Monitor does not watch `agentai-browse`; dead service unalerted. | Medium | HIGH | `ops/monitor.py:19-20` | Add to REQUIRED_UNITS. |
| IS-004 | Port 18801 claimed by legacy control server and live gateway; silent bind failure on the loser. | Medium | MEDIUM | `config.example.json:5`; `service_main.py:54` | `systemctl is-enabled agentai-platform-control`; classify unit as legacy. |
| IS-010 / BE-019 / BE-021 | 30 MiB uploads into single worker (latent: uploads off); body caps by path suffix. | Low | MEDIUM | `middleware.py:21` | Caddy `request_body` cap. |
| AG-013 | `_reconcile_usage` holds the global slot up to 45 s after failed runs. | Low | MEDIUM | `chat_driver.py:749-777` | Cap or release earlier. |
| FE-007 / FE-008 | Polling: 5-8 req/s peak per active tab (estimate), background tabs keep polling. | Medium | HIGH | frontend files | Visibility pause; consolidate pollers. |

## 6. Money and budget correctness

| ID | Risk | Sev | Conf | Evidence | Mitigation |
|---|---|---|---|---|---|
| M-01 (BE-001, AG-001) | Cancelling a WAITING request (or revoked-author/unfunded paths) leaves an `active` reservation and a `queued` task: counted in `_holds` against daily/period/service caps ($50 service allocation means about 50 leaks exhaust it for everyone), counted toward `max_queued_tasks` (3 cancels give "queue full"), and keeps `can_sleep` false so the cell never idles. Only `ops/restore.py:154-157` closes stale reservations. | High | HIGH | `request_queue.py:107-115`; `budget.py:53-58,79`; `chat_driver.py:785-799` | Release reservation and set task `cancelled` in `RequestQueue.cancel`, the revoked path and unfunded failure, plus a sweep for active reservations whose request is terminal; add `_holds` tests. |
| BE-006 | Admit happens after submit; a fast worker tick can fail the request as unfunded and then admit creates an orphan reservation (compounds M-01). | Medium | LOW | `chat.py:313-345` | Insert request paused and flip to waiting inside the admit transaction. |
| AG-007 | `_over_budget`/`_usage_before` fail open on LiteLLM errors; no cap on model calls or tool rounds. Time limit 900 s and provider caps remain (unverified). | Medium | HIGH | `chat_driver.py:464-490` | Treat repeated snapshot failure as stop or alert; consider a turn cap (owner decision: avoids new task limits). |
| BE-009 | Uncertain-request abandon uses `created_epoch`, can abandon a still-running native run. | Medium | MEDIUM | `request_worker.py:84-92` | Track `uncertain_since`. |
| BE-017 | `task.create` hourly cap not applied on `chat_send`. | Low | HIGH | `accounts/chat.py:158-182` | Apply via shared decorator (BE-024). |
| BE-005 | `billing_worker --reconcile` is never scheduled; dead-lettered Stripe events never repaired. | Medium | HIGH | unit line 11 | Daily reconcile timer. |
| OP-008 | Two sets of task limits (plan 3600 s/$5 vs routing config 1800 s/$1); steps/model-call/search caps not found enforced; constants duplicated. | Low | MEDIUM | `routing/config.py:21` | Decide authoritative source. |

## 7. Observability

| ID | Risk | Sev | Conf | Evidence | Mitigation |
|---|---|---|---|---|---|
| M-12 (BE-010, IS-008, ST-010) | `django` logger to NullHandler; only `{request_id,status}` logged; 126 `except Exception`, about 39 bare `pass`; 500s leave no trace of class or location. Privacy-motivated and good for customers, costly for forensics. | Medium | HIGH | `settings.py:101-103`; `middleware.py:39` | Add allowlisted `{event, exception_class, module, request_id}` handler; never message or URL. |
| IS-003 | Monitor blind spot (browse). | Medium | HIGH | above | above |
| BE-018 | Owner signup notice goes to noreply address. | Low | MEDIUM | `signup.py:152` | Add owner-address setting. |
| AG-020 | Browser-job stop failures swallowed. | Low | MEDIUM | `chat_driver.py:515-546` | Count failures. |
| IS-015(g) | `LOOPBACK_PORTS` includes 2019 (Caddy admin) undocumented. | Low | HIGH | `ops/monitor.py` | Document. |

## 8. Backup, DR and source custody

| ID | Risk | Sev | Conf | Evidence | Mitigation |
|---|---|---|---|---|---|
| IS-016 | Backups local by default; off-server copy is a manual pull from the Mac; vault key file, `live.secret`, runner dir not in backup scope; no automated customer-DB restore drill. | Medium | MEDIUM | `ops/hostconfig.py` | Confirm second off-host copy and age private-key custody; extend `config_paths`. |
| IS-017 | GitHub account suspended 14 Oct (stale note); code on one Mac plus bundles; large untracked artifacts outside any backup. | Medium | MEDIUM | `RELEASE_NOTES.md:151-155` | Owner to confirm remote status; verify bundle dates. |
| GH-013 | 47 commits unpushed; origin branch 13 Oct. | Medium | HIGH | `rev-list` | Push decision (Phase 0). |
| AG-006 | (IN PROGRESS) docs claim tool-origin v2 deployed from uncommitted code; rollback/forensics depend on a manifest outside git. | Medium | MEDIUM | `docs/browser-tool-ownership.md` | Commit the work; tag deployed commits (GH-005). |
| IS-006 | Hand-made server state not in git (dashboard unit, drop-ins, `runner.mjs` copies, `live.secret`). | Medium | HIGH | `RELEASE_NOTES.md:129-137` | Compare on host; commit examples. |
| GH-005 | No tags for native1-4/safety1. | Medium | HIGH | RELEASE_NOTES | Tag deployed commits. |

## 9. Supply chain and static analysis

| ID | Risk | Sev | Conf | Evidence | Mitigation |
|---|---|---|---|---|---|
| OP-010 | Sonar scan 2026-10-13: 28 vulnerabilities, 52 bugs, 709 smells (789 issues), gate OK. Report never committed, re-run or acted on. Mostly by-design (webhook `csrf_exempt`, loopback dev helper). | Info | HIGH | `SONARQUBE-REPORT.md`; `sonarqube-export/` | Triage; wire a periodic run. |
| OP-011 | 14 of 14 spot-checked items still present. | Low | HIGH | files cited in TECHNICAL_DEBT | Fix the two privacy-relevant ones. |
| OP-012 | Triage: only `0o777` browse out dir and predictable `/tmp` staging matter for privacy. | Low | MEDIUM | above | above |
| ST-007 | Hash-pinned `requirements.lock` (Django 5.2.17, gunicorn 26.2.0, cryptography 50.0.2) is good; npm mixed pins; `playwright-core 1.49.1` is old (version impression only; no audit run); no Python input file. | Low | HIGH | manifests | Decide deliberate pin; add `requirements.in`. |
| ST-006 | `mcp` imported by `bin/phase6/authorize-google.py` but undeclared. | Medium | HIGH | file:12-13 | Declare or document. |
| M-10 | No lint, type, `pip-audit` or SAST step in CI; frontend untested in CI. | High | HIGH | `platform.yml` | Add discovery run, `tsc`/vitest/build job. |

Not done: `npm audit`, `pip-audit`, gitleaks, any network scan (no network allowed).

## Positives worth preserving

1. **Webhook verification**: Stripe raw-body HMAC, multi-secret overlap, v0 ignored, 300 s tolerance, dedup inbox, canonical re-fetch, backoff to dead-letter, `Idempotency-Key` on checkout/portal; Telegram shared secret with `hmac.compare_digest`.
2. **Uniform 404 enumeration defence**: denials answer 404 and are audited; signup/recovery replies are uniform and rate-limited.
3. **Fail-closed switches**: `SwitchStore` re-reads from disk and defaults off; `_rate_limits_off` keeps limits on on any error; locked switches need recorded facts.
4. **Cell isolation design**: separate Docker engine, gVisor, per-tenant key and budget, nft drop-only table, two named doors, root bridge with SO_PEERCRED and allowlist, browser stages with `cap-drop ALL`.
5. **Age-encrypted backups**: public recipient only on host, private key never on the server, scoped `restore_account` proven not to touch other accounts, restore refuses unclassified tables.
6. **Privacy-first logging**: no URL/body/header in customer logs (keep when adding observability).
7. **Session and header posture**: `__Host-` cookies, HSTS, strict CSP, pinned ALLOWED_HOSTS and CSRF origin, no CORS code anywhere.
8. **Secret hygiene in tracked files**: no secret shapes; Stripe/Telegram/SMTP/Anthropic keys by name or file path only; vault AES-GCM with per-account HKDF.
9. **Tool relay**: body capped 64 KiB, no content logging, per-source failure limit.
10. **Canary release with schema-compatible rollback** (`release.py`) and dated deployment evidence.
