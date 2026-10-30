# Tech debt audit: Lumina (openclaw-project)

> **UPDATE 2026-10-29:** production was verified over SSH after this document was written. Statements below that production is "unverified" are superseded for the items in [PRODUCTION_VERIFICATION_2026-10-29.md](PRODUCTION_VERIFICATION_2026-10-29.md) (live host is Hostinger `179.236.71.203`; IONOS is dead; IS-002 and the tool-origin v2 drift confirmed; IS-004 resolved; M-01 latent, not observed).

> **Run 2 (2026-10-29)**, repeat-run status: VERIFIED in production: L-01 (live host is Hostinger), IS-002, AG-006 (production == uncommitted tree), IS-016, M-08 (runner.mjs is the production engine). RESOLVED in production: IS-004. CHANGED: M-01 is latent (0 stuck reservations). NEW: 58 gap findings (BG-001..030, GX-001..028) and PV-01..09, indexed in `TECHNICAL_DEBT.md` Supplement A. The task queue for cleanup is `HANDOFF.md`.

Audit date 2026-10-29. Branch `product-phases-6-11`, HEAD `03662de` (132 commits) plus uncommitted tool_origin / tool_relay / cell_bridge / cell_config work (IN PROGRESS, not judged). Read-only. **Production is UNVERIFIED** (SSH attempts failed: L-01..L-03). Full register: `TECHNICAL_DEBT.md` (125 rows); this document is the skill-format summary. No rewrites are recommended anywhere.

## Executive summary (ranked by impact)

1. **Customer screenshots leave the host (M-02).** Every JEV browser step sends a raw JPEG of the customer's browser window to `api.typesafe.ai`; scrubbing is text-only and the consent switch `browser_optimization` is not wired to the live path. Top owner priority (privacy).
2. **Cancelling a waiting request leaks money and a queue slot (M-01).** The reservation and `queued` task row are never released, so allowance shrinks, three cancels give "queue full", and the account's cell never sleeps.
3. **A private key sits untracked and un-ignored at the git root (M-03)**, beside about 800 MB of other untracked material (owner browsing logs, 14 worktrees). One `git add -A` publishes it.
4. **The repo and the real server may not describe each other (L-01, IS-002, AG-006).** Runbooks target an unreachable IONOS host while the owner's ssh config points to a Hostinger host; tool-origin v2 is documented as deployed from uncommitted code. All server facts are unverified.
5. **CI is thin (M-10).** About 20 of 73 platform test modules run; billing, browse, ops, cell and tool-origin tests, the whole React app, `tsc` and the build never run in CI.
6. **Rate limits are probably global (M-04), and one SSE route can stall the only web worker (BE-002).** Both are cheap to fix.
7. **Three browser engines and three generative-UI generations coexist (M-08, M-07)**, with SSRF policy implemented four times; both are half-finished migrations, not accidents.
8. **A browser-question and vault UI regression (FE-002)**: the shipping app has no screen for a run that asks the customer something, if the backend can still reach that state.
9. **Observability is deliberately blind (M-12)**: no traceback for 500s, 126 `except Exception` sites. Correct for privacy; costly for incidents.
10. **Docs describe a project that no longer exists (M-11, ST-014)**: README says phase 4 is next, BUILD_LOG stops 10-12, ServiceRouter was deleted in a commit titled for a UI change but is still documented.

## Architectural mental model

Lumina is a multi-tenant "assistant in a box" product. A React SPA (`lumina/`, built to `lumina/dist` and served by Django at `/app/`, fronted by Vercel rewrites to a Caddy edge on a single VPS) talks to a Django/gunicorn app (one sync worker, SQLite) that authenticates the customer, admits a chat message against a budget ledger, and puts it into a durable serial queue with one global running slot. A `request_worker` claims requests; `ChatDriver` delivers each to the customer's own OpenClaw assistant, which runs in a gVisor container on a separate Docker engine through a root-owned cell bridge (unix socket, allowlisted RPCs) and a model relay to LiteLLM with a per-tenant virtual key and budget. For browsing, the assistant calls an MCP tool (`lumina_browser`) over a tool relay; a root browse service runs the page in a Docker stage with `runner.mjs` (default) or the cell's native browser (gated off), with a code-level safety floor and a JEV (TypeSafe) step chooser that hands over to the assistant. Owner tooling (dashboard, backups, ops monitor, release canary) is separate and stdlib-only by design. Tenant isolation is strong in the HTTP layer (session-derived account id, uniform 404) and in the cell design; the weak spots are bookkeeping (M-01), data egress (M-02) and operations (L-01, IS-002).

Documentation contradicts reality in several places: `README.md` says Product Phases 1-2 are delivered and phase 4 is next, while `BUILD_LOG.md` records phases 4, 13 and 14 built (and stops 2026-10-12 though work ran to 10-27) and plans reach phase 15; `RUNBOOK.md` says no persistent listener is installed; 17 files name the IONOS VPS while the owner's `lumina` host is Hostinger (L-01); `CLAUDE.local.md` and `docs/architecture/*` still describe `ServiceRouter`, which was removed in commit 5db9636 (M-11); `plans/product/LAUNCH.md` says JEV routing is record-only while code lets JEV decide browser steps (OP-015); and the privacy doc says one host door where code has two (IS-015). The branch, not `main`, is the real trunk: `main` is 107 commits stale and `origin/product-phases-6-11` is 47 commits behind local.

## Findings table

Severity is approximate. Effort: S under a day, M days, L a week or more. IDs as in `TECHNICAL_DEBT.md` (M-xx master, L-xx lead, otherwise source IDs).

| ID | Category | File:Line | Severity | Effort | Description | Recommendation |
|---|---|---|---|---|---|---|
| M-02 | Security hygiene | `browse/ladder.py:333,397,606`; `loop.py:208-216` | High | M | Screenshots sent to TypeSafe each step; text-only scrub; consent switch not wired | Decide gate (opt-in or no-controls only); wire `browser_optimization`; update privacy text |
| M-01 | Error handling | `request_queue.py:107-115`; `chat_driver.py:785-799` | High | M | Waiting-cancel leaks reservation and queued task | Release in `cancel`, revoked path, unfunded; sweep; tests |
| M-03 | Security hygiene | repo root `ssk-key*`; `.gitignore` | High | S | Untracked un-ignored private key and 800 MB clutter | Ignore rules; move key; relocate logs |
| L-01 | Doc drift | 17 files naming `69.48.206.62` | High | S | Deployment target drift IONOS vs Hostinger | Verify host (Phase 2) then fix docs |
| M-10 | Test debt | `.github/workflows/platform.yml` | High | M | About 20 of 73 test modules; no frontend job | `unittest discover` + lumina job |
| M-04 | Security hygiene | `middleware.py:14-19`; `Caddyfile.getlumina:24-25` | High | S-M | Global per-IP buckets behind Vercel | Real client IP at Caddy |
| BE-002 | Performance | `accounts/streams.py:60-121` | High | S-M | SSE blocks the only worker | Remove or isolate |
| IS-002 | Security hygiene | `bin/ssh-server:21-24` | High | M | Root password SSH from `.env` | Key login, then disable password |
| FE-002 | Architectural decay | `lumina/src/pages/Live.tsx:129` | High | M | No UI for browser asking state, vault, saved info | Port from fork or retire routes |
| M-08 | Architectural decay | `browse/runner.mjs`, `native_runner.py`, `service.py:647` | High | L | Three browser designs, four SSRF copies | Engine decision; shared test vector |
| M-06 | Architectural decay | `lumina-character/` (4,697 files) | High | M | Tracked fork unreferenced by deploy/CI | Decide; fix symlink ignore |
| M-11 | Doc drift | `routing/services.py` deleted (5db9636) | High | M | Documented-but-deleted ServiceRouter | Confirm retirement; fix docs |
| M-07 | Consistency rot | `components/genui/*`, `src/gen/*` | Medium | L | Three genui generations | Migrate form/task_plan to `gen` |
| M-05 | Architectural decay | `durable/memory/schedules/watchers/skills/optimization/policy_check.py` | Medium | S | Orphaned product modules | Decide wire/hide/park (preserve) |
| M-09 | Dependency/config debt | `accounts/settings.py`; `accounts.env.example` | Medium | M | 8 of about 45 env vars documented | Generate example + test |
| M-12 | Error handling | `settings.py:101-103`; `middleware.py:39` | Medium | M | No exception trace; 126 broad excepts | Redacted class/module logger |
| BE-005 | Error handling | `agentai-billing-worker.service:11` | Medium | S | No `--reconcile` schedule | Daily timer |
| BE-004 | Consistency rot | `middleware.py:23` | Medium | S | 8 KB cap 413s webhooks | Exempt two webhook paths |
| BE-006 | Error handling | `chat.py:313-345` | Medium | M | Admit race creates orphan reservation | Insert paused, flip in admit |
| BE-007 | Architectural decay | `accounts/telegram.py:26-31` | Medium | M | Telegram cannot complete in prod wiring | Finish or hide |
| BE-009 | Error handling | `request_worker.py:84-92` | Medium | S | Abandon timer uses created time | `uncertain_since` |
| BE-011 | Dependency/config debt | `retention_accounts` | Medium | S-M | Retention unscheduled; contract unclear | Decide, then schedule |
| BE-013 | Architectural decay | `request_queue.py`; `middleware.py:63-69` | Medium | L | Single slot; write per request | Meter mutations; product decision |
| AG-004 | Architectural decay | `request_queue.py:147-175` | Medium | M | Holder-cell starvation scenario | Fair claim; count started tasks |
| AG-005 | Error handling | `chat_driver.py:363-366,817-819` | Medium | S | PARK_LIMIT expiry re-parks | Stop path on timeout |
| AG-006 | Doc drift | `docs/browser-tool-ownership.md` | Medium | S | Deployed claim vs uncommitted code | Commit; tag |
| AG-007 | Error handling | `chat_driver.py:464-490` | Medium | M | Spend guard fails open | Alert/stop on repeated failure |
| AG-008 | Error handling | `tool_relay.py:119-122` (in progress) | Medium | S | Fixed refusal text hides transient errors | Distinguish causes |
| AG-018 | Architectural decay | `outcome.py:36-60` | Medium | M | Completion not verified | Product decision |
| AG-021 | Security hygiene | `cell_config.py:25,53-56` | Medium | M | "No purchase" only inside `lumina_browser` | State scope; optional deny exec |
| IS-003 | Error handling | `ops/monitor.py:19-20` | Medium | S | Monitor omits `agentai-browse` | Add to REQUIRED_UNITS |
| IS-004 | Dependency/config debt | `config.example.json:5`; `service_main.py:54` | Medium | S | Port 18801 double-claimed | Classify control unit legacy |
| IS-005 | Doc drift | `cells-docker/agentai_cells.nft.generated` | Medium | S | Stale nft sample | Regenerate or delete |
| IS-006 | Dependency/config debt | server-side hand-made files | Medium | M | Hand-made server state not in git | Commit examples; sync script |
| IS-011 | Security hygiene | `dashboard/app.py:156-162,817` | Medium | M | Throttle keyed to loopback; no Host check | Host allowlist |
| IS-012 | Security hygiene | `docker-compose.production.yml:55-56` | Medium | - | docker.sock into gateway (by design) | Preserve; harden if testable |
| IS-013 | Security hygiene | root `agentai-*.service` units | Medium | M | Root services lack sandbox directives | Canary hardening |
| IS-016 | Dependency/config debt | `ops/hostconfig.py` | Medium | M | Backups local; off-server manual | Confirm offsite and key custody |
| IS-017 | Dependency/config debt | `RELEASE_NOTES.md:151-155` | Medium | S | Source custody uncertain | Owner confirms remote |
| ST-006 | Dependency/config debt | `bin/phase6/authorize-google.py:12-13` | Medium | S | `mcp` undeclared | Declare |
| ST-008 | Architectural decay | `dashboard/app.py` 1718 LOC; `chat_driver.py` 907 | Medium | L | God files | Split when touched |
| ST-013 | Doc drift | `platform/deploy` vs ops docs | Medium | S | Seven units undocumented | Update docs |
| ST-014 | Doc drift | `README.md`; `RUNBOOK.md:1-35` | Medium | S | Stale status | Rewrite status sections |
| FE-008 | Performance | `Chat.tsx`; `state/data.tsx:50-54` | Medium | S | Overlapping pollers | Consolidate; pause hidden |
| FE-015 | Test debt | `state/data.tsx`; `gen/ChatBridge.tsx` | Medium | M | Hot files untested | Add tests |
| GH-001 | Consistency rot | commit `d95b796` | Medium | M | 4929-file mega-commit | Document and tag |
| GH-005 | Doc drift | `RELEASE_NOTES.md`; tags | Medium | S | No tags after live8 | Tag deployed commits |
| GH-013 | Consistency rot | `origin/*` refs | Medium | S | 47 unpushed commits; stale main | Push decision |
| GH-011 | Dependency/config debt | `.git` 351 MB; emoji + film assets | Medium | M | Repo weight | `git gc`; LFS option |
| ST-018 | Test debt | `accounts/middleware.py` | Medium | M | Boundary logic has no direct test | Middleware test |
| BE-012 | Consistency rot | `accounts/migrations`, `migrations/*.sql` | Low | M | Two migration systems | Single source of truth |
| BE-017 | Consistency rot | `accounts/chat.py:158-182` | Low | S | `task.create` cap skipped on send | Apply cap |
| BE-024 | Consistency rot | `accounts/*` service wiring | Low | M | Copy-pasted wiring and preambles | Decorator, single factory |
| BE-019 | Error handling | `accounts/files.py:97-101,155` | Low | S | Upload read before size check; header mishandled | Fix |
| BE-016 | Doc drift | `openapi.json`; `views.py:108-109` | Low | S | Hard-coded flags; no route gate test | Add test |
| AG-014 | Architectural decay | `browse/loop.py:124-343` | Low | L | 220-line safety-floor function | Extract pure function |
| AG-011 | Performance | `browse/service.py:172` | Low | S | Jobs never evicted | Evict |
| AG-017 | Test debt | `tests/e2e/*` | Low | M | Real-gateway tests skip in CI | Document / nightly job |
| FE-006 | Consistency rot | `lumina/src/lib/api.ts:12-30` | Low | S | Raw fetch bypass | Hardening |
| FE-011 | Security hygiene | `App.tsx:28` | Low | S | Dev gallery reachable | Gate |
| FE-013 | Type debt | `gen/components/extended.tsx` | Low | S | `any` clusters; no ESLint | Incremental typing; lint config |
| ST-007 | Dependency/config debt | `package.json` pins; `playwright-core 1.49.1` | Low | S | Mixed pins; old playwright | Confirm deliberate |
| OP-011 | Security hygiene | `browse/service.py:519`; `manage-connectors.py:115` | Low | S | 0o777 dir, predictable /tmp | Tighten |
| OP-008 | Doc drift | `routing/config.py:21` vs `product/plan.json` | Low | M | Two sets of task limits | Choose authority |

## Top 5 "if you fix nothing else"

### 1. M-01 release the reservation when a waiting request is cancelled

`RequestQueue.cancel` (`request_queue.py:107-115`) flips `customer_requests` to `cancelled` and stops. Do the release in the same coordinator transaction. Sketch only (not tested; check the reservation state CHECK constraint in the SQL migrations and how request id maps to task id before coding):

```python
# request_queue.py
def cancel(self, principal, request):
    with self.coordinator.transaction() as c:
        ...
        if row['state'] == 'waiting':
            c.execute("UPDATE customer_requests SET state='cancelled',cancel_requested=1 WHERE account_id=? AND id=?", ...)
            self.ledger.release_unstarted(c, account=principal.account_id, request=request)  # NEW
# budget.py (next to settle)
def release_unstarted(self, con, *, account, request):
    task = self._task_for(con, account, request)           # NEW lookup
    con.execute("UPDATE task_reservations SET state='settled' WHERE account_id=? AND task_id=? AND state='active'", (account, task))
    con.execute("UPDATE tasks SET state='cancelled' WHERE account_id=? AND id=? AND state='queued'", (account, task))
```

Repeat in the revoked-author path of `claim` (`:164`) and `request_worker` "failed_unfunded". Add a periodic sweep: reservations `active` whose request is terminal. Tests: cancel waiting then assert `_holds` and `max_queued_tasks` unchanged; double-cancel; cancel racing a claim. Coordinate with the `ChatDriver._close` settle path (`chat_driver.py:785-799`).

### 2. M-03 ignore and relocate the private key

```gitignore
# root .gitignore (add)
ssk-key*
*_key
*_key.pub
id_ed25519*
id_rsa*
/*.tar.gz
/*.zip
/*.png
/*.PNG
.claude/
node_modules
```

Then `mv ssk-key ssk-key.pub ~/.ssh/` (owner action; confirm what it opens, L-02 says it authorizes nothing on the tested host), move or ignore `lumina-cost-audit/`, and verify with `git check-ignore -v ssk-key` and `git status`. Change `node_modules/` to `node_modules` so symlinks match.

### 3. M-02 gate screenshots on the live browse path

Owner decision first (class C). Minimal code shape in `browse/ladder.py` where the JEV request is built (`:333,397`, `sight = shot and candidates` at `:606`):

```python
# ladder.py
def _sight(self, shot, candidates):
    if not shot or not self.images_allowed:   # NEW: from a wired switch, default False
        return None
    return shot if not candidates else None   # only when no controls could be listed
# service_main.py jev_for(): pass images_allowed=SwitchStore(...).is_on('browser_optimization')
```

Also update the `personal_data_scrub` switch text ("page text and labels" only), `plans/product/privacy.md:17`, and add a test that the outgoing payload has no `assets` image when the switch is off. Phase 2 should first confirm whether the TypeSafe key is installed (`jev_for` returns no JEV without it).

### 4. M-04 trust a real client IP

In `Caddyfile.getlumina`, replace `{remote_host}` for the Vercel-fronted path with the verified client address, accepting the forwarded header only from a trusted peer or with a shared secret Vercel adds:

```caddy
@from_vercel header X-Edge-Secret {env.EDGE_SECRET}
handle @from_vercel {
    reverse_proxy 127.0.0.1:18800 {
        header_up X-AgentAI-Client-IP {http.request.header.X-Vercel-Forwarded-For}
        header_up X-Forwarded-For   {http.request.header.X-Vercel-Forwarded-For}
    }
}
# requests without the secret keep {remote_host} (direct hits are not trusted)
```

Add the secret to `vercel/routing.mjs` rewrites (header) and keep `BoundaryMiddleware` loopback-only trust. Verify in Phase 2 which peers Caddy actually sees before and after. Sketch; header names depend on the Vercel setup.

### 5. M-10 run what you have in CI

```yaml
# .github/workflows/platform.yml (replace the hand-listed unittest line)
- name: Platform tests
  run: python -m unittest discover -s tests -p 'test_*.py'
# new job
frontend:
  runs-on: ubuntu-latest
  defaults: { run: { working-directory: openclaw-project/lumina } }
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-node@v4
      with: { node-version: '22' }
    - run: npm ci && npx tsc --noEmit && npx vitest run && npm run build
```

Run `discover` locally once first: tests needing `age`, Chrome, OpenClaw or Linux `SO_PEERCRED` already self-skip, but some of the 53 currently unlisted modules may fail. Also add `browse/` `node --test` and `tool_origin_plugin.test.mjs` once the in-progress work is committed.

## Quick wins checklist

- [ ] Add `ssk-key*` and root archive patterns to `.gitignore`; `node_modules` without slash (M-03, GH-002).
- [ ] Move `ssk-key` to `~/.ssh` (M-03).
- [ ] Commit the in-progress tool_origin work after owner review (AG-006).
- [ ] Tag deployed commits d95b796 and native1-4/safety1; add hashes to RELEASE_NOTES (GH-001, GH-005).
- [ ] Decide push of 47 commits; fast-forward `main` (GH-013).
- [ ] Exempt the two webhook paths from the 8 KB cap (BE-004).
- [ ] Add a daily `billing_worker --reconcile` timer (BE-005).
- [ ] Add `agentai-browse` to `REQUIRED_UNITS` (IS-003).
- [ ] Remove or gate `/v1/tasks/<id>/stream` (BE-002) and `/app/gen-gallery` (FE-011).
- [ ] Apply `task.create` limit on `chat_send` (BE-017).
- [ ] Remove dead `DATA_UPLOAD_MAX_MEMORY_SIZE` line, unused `import hmac`, `GoalChain.limit` (BE-021, AG-015).
- [ ] Declare `mcp` or note the optional extra (ST-006).
- [ ] Fix README/RUNBOOK status and ServiceRouter references (ST-014, M-11).
- [ ] `git gc`; prune merged worktrees after dirty check (GH-011, GH-014).
- [ ] Tighten `0o777` browse out dir and `/tmp` staging name (OP-011).

## Things that look bad but are actually fine

1. Single gunicorn worker, one sync thread: deliberate with SQLite `IMMEDIATE` transactions and a 128 MiB cap (the problem is the SSE route, BE-002, not the model).
2. Root services (`agentai-browse`, `cell-bridge`, `supervisor-native`): they need Docker/nft/chown; the app user never gets a docker handle. Narrow, designed trust anchor (missing sandbox directives are IS-013).
3. `django` logger to `NullHandler` and `print` of request id only: privacy-first by design (M-12 is about adding a redacted record, not about logging content).
4. `AccountMiddleware`/`endpoint()` swallowing `Denied` into a uniform 404: enumeration defence, each denial audited.
5. Switch helpers and hard-coded 503s (`disabled`, `connections.callback`): fail-closed gating, not broken features.
6. `SyntheticGateway` next to `NativeGateway`: test double never built by the worker entry point.
7. `except Exception: pass` around `shadow.before/after`, event writes and file capture: optional observers that must not fail a customer task.
8. Cell `noSandbox` and `evaluateEnabled`: assistant cannot call the browser tool (denied); bridge accepts only named scripts and fixed routes; address policy reset at every start.
9. `gen/legacy.tsx` and `Cards.tsx` indirection: live path for old stored cards; do not delete.
10. `lumina-character/node_modules` symlink and near-duplicate files: intentional frozen snapshot (tag `lumina-character-final`), not a 2x disk copy.
11. 13 `worktree-*` branches and `main` 107 behind: strict ancestors of the working branch; only product-images had an extra commit and it was re-landed.
12. `dashboard/app.py` at 1718 LOC without platform helpers: stdlib-only, separately deployed on purpose.
13. vulture's 241 lines at confidence 60: Django `Command`/`Meta`/middleware dynamic loading, not dead code.
14. `RUN_TIMEOUT` 900 s vs backstop 1200 s vs MCP timeout vs browse 600 s: layered backstops for a dead supervisor.
15. `jev-browser/` and its four tarballs: intentional snapshots of different architectures, not a production dependency; production JEV is the hosted TypeSafe model.
16. `@csrf_exempt` on Stripe/Telegram webhooks: they cannot carry CSRF tokens and authenticate by signature or secret header; Sonar flags them mechanically.
17. `docker-compose` publishing LiteLLM on `127.0.0.1:4000`: loopback only, required for the model relay (only the README is stale).
18. Skipped tests: all are `skipUnless` with stated environment preconditions.

## Open questions for the maintainer

1. Which host is production today: Hostinger `179.236.71.203` or the IONOS `69.48.206.62` in the docs (L-01)? Is the IONOS server decommissioned?
2. What does `ssk-key` open (L-02)? Was it ever shared or deployed to a server or GitHub? Should it be rotated?
3. Is SSH password and root login still enabled, and when will key login be adopted (IS-002)?
4. Is the TypeSafe key installed in production, and did the customer-facing terms cover sending screenshots as well as text (M-02)? Should `browser_optimization` gate it?
5. Should a cancelled waiting request release its reservation immediately or via a reaper (M-01)? Has any account shown "queue full" after cancelling?
6. Which browser engine does production use (`browse-engine.json`), and are any accounts on `native` (M-08)? Who owns the eval gate in `native-browser-plan.md`?
7. Is tool-origin v2 really deployed from the uncommitted tree, and when will it be committed (AG-006)? Which commits were deployed as native1-4 and safety1?
8. Was removal of `routing/services.py` in 5db9636 intentional, and does production still run a live3/live4-style router (M-11)?
9. Is `lumina-character` the future UI, the home of the film feature, or an archive (M-06)? Are the 61 MB of scenes meant to stay in git?
10. Does the backend still put browser runs into an `asking` state, and who answers it now (FE-002)? Are vault and saved-info coming back in `lumina` or should the routes retire?
11. Which generative-UI path is the target, and is `/v1/genui/registry` meant to be consumed by the frontend (M-07)?
12. Is the single global lane a permanent constraint or a private-beta limit (BE-013, AG-004)? Is the X/Y stall reproducible with two accounts?
13. Should Telegram ship (pricer wiring, result relay, drain unit) or be hidden (BE-007)? Same for connector OAuth.
14. Does a host cron run `retention_accounts` and `billing_worker --reconcile`? What is the intended retention for `chat_messages` (BE-011, BE-005)?
15. Where is the second off-server backup copy, and where do the age private keys and the vault key live (IS-016)? Is the code on GitHub again (IS-017, GH-013)?
16. Is `/v1/tasks/<id>/stream` meant to ship (BE-002)? Should `/app/gen-gallery` be reachable by customers (FE-011)?
17. Which task limits are authoritative: `product/plan.json` (3600 s, $5, steps and calls) or `routing/config.py` (1800 s, $1) (OP-008)? Are steps/model-call caps enforced at all?
18. Is JEV currently deciding browser steps in production or record-only (OP-015)?
19. Should CI switch to test discovery and gain a frontend job, and should a periodic Sonar run be wired in (M-10, OP-010)? Is `playwright-core 1.49.1` pinned on purpose (ST-007)?
20. Where should `jev-browser`, `jev-window-core`, the zips, tarballs, `lumina-cost-audit` and screenshots live, and which of the 14 worktree branches hold unmerged work (M-03)?
21. Is `BUILD_LOG.md` still the status source of truth given no entry since 2026-10-12 (ST-014)? Are `config/skills`, workspace templates and phase fixtures installed by hand on a host or dead assets (M-05)?
22. Do `openclaw-dashboard.service` run as root, and where is its unit committed (IS-011, IS-006)? Should the root browse and bridge units gain the full systemd sandbox set (IS-013)?
