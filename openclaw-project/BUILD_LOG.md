# OpenClaw build log

## Product Phase4/5 continuation — 2026-09-30 (local components READY; full phases PARTIAL)

Built account-bound lifecycle coordinator/queue API, scoped MFA/action grants,
leases/fences, receipt reconciliation, global execution slot and retry limits;
file-backed fixtures demonstrate all seven lifecycle operation kinds. Native
driver/worker/quotas/network/secrets/restore/rollback integration remains missing.
Independent Phase5 core adds atomic tasks/reservations, append-only provider
receipts, budget caps, idempotency, late/uncertain usage and scoped usage views;
real metered routes/per-call dispatch/native fences remain missing.

14 lifecycle +10 budget +9 new API checks passed, with25 account,14 foundation
and7 capacity regressions. Initial helper/grant-trigger/sandbox failures retained
and corrected. New schema migrated only into private disposable local databases.
Fresh read-only VPS check:~909MiB available, swap>99% used, runc only; smaller
complete-task footprint not proved. No live cell/provider/invite/paid/public effect
or owner change, and no hardware upgrade requirement/purchase. Every planned
feature/121 requirements retained; Phase4/5 activation remains blocked.

Evidence: openclaw-project/evidence/product/phase-04/20260930T195312Z/manifest.json and openclaw-project/evidence/product/phase-05/20260930T195312Z/manifest.json.


## Product trial target — 2026-09-30 (existing VPS; plan updated, not deployed)

Owner selected existing-host trial first, every planned feature retained, upgrade
later. Added product/EXISTING_VPS_TRIAL.md; deployment-policy v2 selects two
invite-only accounts, one global customer task/cell, on-demand wake/drain/stop
and sequential isolated worker stages. Revised Phase4/5/15/17 and shared contract
to remove upgrade-first sequencing and distinguish invitation/account access
from task capacity. Parallel runtime tests remain capacity-expansion gates;
serialized trial still requires real isolation/budget/recovery/task proofs.
Historical default-cell zero-slot result and Phase4 evidence remain unchanged.
No smaller profile measured, native lifecycle still missing, no live feature
flags changed, invitations sent, owner workloads stopped or VPS upgrade bought.
Next implementation remains Phase4 on the existing server.


## Product Phase4 assessment — 2026-09-29/30 (shared-VPS target; implementation PARTIAL; agent activation BLOCKED)

Owner clarified one service-operated VPS/shared domain and requested architecture/
capacity assessment. Earlier ADR002 separate service-owned customer VMs did not
require customers to own infrastructure, but the target is now shared Fleet cells.
Recorded ADR007 and revised contract/prompt/ledger with missing effective worker/
host identity/network/secret/disk isolation and native lifecycle/broker work.
Unintegrated VM-specific draft withdrawn before any migrations/deployment; Phase3
settings/models/admin match prior final source hashes exactly.

Read-only owner host inventory:3.78GiB RAM,2CPU,0.94–0.97GiB available,2GiB swap
>99% used; owner Gateway1.36–1.40GiB, five browsers~876MiB,82.8GiB disk free.
Only runc runtime; AppArmor/seccomp/cgroupv2 present, gVisor/Podman absent; ext4
mount has no project-quota option, Docker storage reports overlayfs. KVM device
present is not VM startup or isolation proof. One public app domain/metadata auth
already fit; lifecycle remains disabled, no public80/443 app listener installed.

Read-only capacity calculator7 focused checks PASS. After planned256MiB app and
512MiB headroom reserves,209203200bytes remain; default Fleet2GiB yields0 added
agents. Native/task peaks and CPU/disk/PID admission remain unknown. Proposed
16GiB/4CPU/two-beta-account/one-global-task scenario is UNMEASURED, no purchase.
Current fleet CLI help and official docs support available lifecycle flags;
whole runtime source copy was rejected by auto-review as internal source egress.
No bypass; assessment completed from help and public docs.

No provisioning/model/provider/customer message/payment call, owner change or
cleanup of live workloads. Full Phase4 lifecycle and live A/B isolation not passed;
resume Phase4 after concrete single-VPS hardware/runtime plan. Phase5 not started.
See plans/product/phase-04-single-vps-assessment.md and phase-04-capacity.json.
Evidence: `evidence/product/phase-04/20260930T011410Z/manifest.json`.

## Product Phase 3 — 2026-09-29 (account build READY; private checks PASS; activation blocked)

Added separate Django5.2.17 authentication/database sessions/CSRF, django-otp1.7.3
confirmed operator TOTP and Gunicorn26.2.0. Exact official wheel hashes locked.
Verified invite-only onboarding, generic queued recovery with15-minute hashed
single-use purpose/epoch-bound codes, session rotation/expiry/logout/revocation,
live membership/account checks, contract rate limits and server-only mappings.
Operator permissions are one-hour account/action grants requiring MFA; no support
content/impersonation/export or service browser login. Customer task gates remain off.

Append-only required audit commits with local effects; external mail has durable
pending/completed/uncertain receipts. Fixed a rollback/session middleware hazard
and final-auth-migration email-index ordering; explicit negative fixtures pass.
Restricted180-day audit retention and90-day chat projection/tombstones prepared;
native erasure/export/7-day account deletion is tracked PARTIAL for6/8/10/14.

25 focused account checks,14 foundation checks, concurrent token/migration checks
and actual two-account loopback Gunicorn HTTP smoke passed. Temporary process/state
cleaned. Full browser/SMTP/native/provider/server-resource/load/independent review
acceptance remains NOT_RUN15. SMTP disabled; no real identities/invites/messages,
paid calls/public route/permanent deployment or owner runtime change. HSTS preload
W021 intentionally awaits approved domain. Source/API/architecture/runbook,
plans/product/phase-03.md, requirement ledger and sanitized evidence updated.
Evidence: `evidence/product/phase-03/20260930T003526Z/manifest.json`.
Next authorized-on-request implementation phase is4; this phase stops here.

## Product Phases 1–2 — 2026-09-29 (design READY; private foundation READY; customer acceptance pending)

Owner requested both phases. Product contract,14-screen annotated wireframes,
complete reading-list example, sourced Decimal cost/capacity scenarios and121
requirement mappings delivered. Owner selected79USD/month,25USD included provider
consumption,5USD/task,one running task/customer and no automatic overage.
Complete commercial coding/reviewer costs remain unknown; later features retain
IDs/cases. Existing owner caps/config/state/proxy DB preserved.

Built separate dependency-free private app/control skeletons, composite tenant
metadata schema, immutable/checksummed migrations, deny-by-default identity,
hard-disabled customer capabilities, fixed log fields, schemas/interfaces and
architecture/API/isolation/capability/deployment records.14 targeted checks passed,
including direct scoped HTTP/FK denial and rollback/readiness/revocation/log tests.
Live read-only inventory confirmed2026.9.6, LiteLLM1.102.1/Postgres16.10, limited
host RAM and near-full swap. Selected customer boundary: separate VMs; owner host
admits no customer deployment. Installed Fleet/RPC advertisement is not client proof.

Final actual VPS smoke: both unprivileged loopback app/control startup/readiness
passed, API401,128MiB/no-swap/25%CPU/16-task limits; observed~13MiB each. Temporary
units/source/empty DB cleaned up. Initial safe symlink-state refusal retained as
failed evidence; fixture corrected to direct ephemeral state and passed. Browser
wireframe rendering NOT_RUN because file protocol blocked by browser policy;
script/static design checked. No paid model/provider tests, live sign-ins, charges,
customer messages, public ingress or owner service changes.

Evidence: `evidence/product/phase-01/20260929T233120Z/` and
`evidence/product/phase-02/20260929T233120Z/`; source hashes identify uncommitted snapshot.
Next product implementation phase3. Full security/native/provider/recovery/customer
acceptance remains Phase15 onward. Historical phase labels below remain history.


## Customer-platform prompt replacement — 2026-09-29 (planning only)

Owner requested a new sequence from Phase 1 combining ten customer-product
workstreams with every unfinished previous/future prompt requirement.
Replaced the old Phase 0–12 executable prompt files and personal-only brief
with 19 bounded phases (12, 16 and follow-on 19 optional), a shared execution contract and
an old-to-new coverage ledger. Updated repository entry points. Historical
implementation plans, eval cases/results and runtime evidence are preserved;
new records use `plans/product/` and `evidence/product/`.

Scope now includes customer accounts, separate deployments and hosted service
billing; no retired Python runtime is restored. Budget admission precedes
chat. Coding/review, memory/durability/scheduling, integrations, off-host
recovery, unresolved 4A/8B gaps and the 180-run optional browser comparison
carry forward. Older multi-user prompts from Git were also reviewed: watcher/skill reuse,
credentialed browser/profile custody, safe load/shutdown tests and optional
follow-on purchase requirements carry forward in Phases 10/11/15/19.
Costs/capacity require measured inputs in new Phase 1; none
were invented. No runtime deployment, paid calls, account connections,
customer messages, live payments or acceptance tests occurred in this update.

Canonical instructions: `../phase-prompts/openclaw/README.md` and
`../phase-prompts/openclaw/coverage-ledger.md`. Old labels below are historical.

## Phase 8B — dashboard v2 with live work viewer, 2026-09-29 (build READY; live SSE verified; deploy completed)

Owner pasted the Phase 8B prompt; VPS was down at start (rebooted by owner
mid-build). Built locally, then deployed and verified live after recovery.

- **§1 defects fixed with regression tests (17 green):** dotted file names;
  descriptor-based no-follow containment via new fixed container helper
  `workread.mjs`; hashed server-side sessions (idle 2h / absolute 24h,
  per-session logout, rotation); single-use downloads bound to
  session+path+version+expiry; truthful unhealthy/unknown states with
  preserved observation timestamps. Two additional real bugs caught by the
  tests: the v1 `.`-check in `validate()` rejected every v2 token (owner
  lockout) and the root-listing rejection regression.
- **Live work viewer implemented and verified LIVE:** session tree, SSE
  timeline with cursor-resume/pause/filters, web-activity rendering, Jev
  toggle (documented config file, readback + audit), now-running strip,
  pending-approvals count. Authenticated SSE returns 200 with cursor+pings
  every 2s; unauthenticated 303. Two deployment bugs found and fixed live
  (SSE header buffering — replaced with a raw status-line write; moving
  audit cursor so events between polls are visible). Paid verification:
  two small researcher runs observed during streaming; spend today $1.15
  of $2. **Backend:** cli-audit (verified native); gateway-http history
  backend implemented but gated on the §0 token+endpoint probe (not_run).
- **Honest limits:** per-run cost attribution unavailable in the LiteLLM
  ledger → "unknown" where not exposed; cancel/approval-resolution absent
  (no verified native path); browser/codex specialized views render from
  the same transcript stream and are only as complete as the runtime's
  audit records.
- Budget integrity re-verified after the owner's reboot: the transient
  failsafe died with the reboot, so the cap was re-checked and confirmed
  $2/24h + $25/30d via the budget_limits readback (mechanism documented in
  `backups/ops/phase4a-restore-budget.sh`). Cron follow-up (2026-09-29):
  disposable `phase4a-jev-eval` key lifetime spend confirmed **$0.000029
  (2 calls)** — within its $0.05 cap; production caps read back unchanged.
- **Artifacts:** `plans/phase-8b.md` (progress/resume), dashboard v2 +
  `static/` + `workread.mjs` + tests, 4 new T10-DASH2-* cases (suite 39),
  `evidence/phase-8b/20260929T001500Z/`. Deployed hash matches repo.

## Phase 4A continuation — verification + close-out, 2026-09-28 ~22:15 UTC (layer NOT promoted)

Another session built Phase 4A up to the toggle and ran out of usage mid-
verification; this session verified its state and closed out within the
authorized window (which ends 22:29 UTC).

- **Verified intact:** Brave MCP live (researcher-only); Gate 3 baseline
  PASSED (research fetch+citations, critic verification, injection reported,
  no side effects — sessions `p4a-gate3-*-20260928`, audit 21:00–21:03 UTC);
  LiteLLM Jev pass-through works (`/typesafe/v1/systemone`, `jev-1.13.0`,
  $0.000011676 probe under the disposable `phase4a-jev-eval` $0.05 key);
  adapter + middleware sources present with 10 Python + node tests green;
  plugin staged, config-enabled, private key mounted, `config validate`
  clean; budget failsafe timer armed ($10 → $2 at 22:29 UTC).
- **One open defect found by live verification:** the gateway does NOT load
  the `jev-research` middleware at runtime (absent from the startup plugin
  list) despite config-enablement — toggle ON produced no decision rows and
  no Jev spend; both probes correctly behaved as plain baseline fetches
  (fail-open proven in practice). Suspected manifest/entry contract
  mismatch in `openclaw.plugin.json`; fix requires the plugin-loader source.
- **Verdict per the frozen promotion gate: NOT PROMOTED.** Toggle left
  **off** (`openclaw-state/jev-research/config.json`), no paired comparison
  run (would not fit the remaining window), no accuracy/cost claims made.
  RESULTS.md updated: T10-RESEARCH-CITATIONS + T10-INJECTION-NO-EFFECT
  now **PASS** (Gate 3 baseline closed). RUNBOOK corrected with toggle/log/
  key paths and resume instructions.
- Budget: auto-restore verified armed; spend this continuation ≈ $0.10
  (two trivial fetch turns).

## Phase 4A — Jev research preflight, 2026-09-28 (BLOCKED; inactive)

Verified the live research path and current TypeSafe/OpenClaw/LiteLLM docs.
Brave MCP search is now live for researcher and browser is live for
browser-worker; native `web_search` stays disabled. The installed OpenClaw
contains the documented pre-model tool-result middleware symbol, which is
the proposed narrow `web_fetch` seam. No plugin or policy was changed.

Gate 3 sourced research and injection checks remain BLOCKED in
`evals/RESULTS.md`, so there is no valid baseline to optimize. The server
has no TypeSafe credential in the inspected deployment secret files. The owner
identified a bare `jev:` key in the local private `.env`; it was converted to
a named `TYPESAFE_API_KEY` assignment without exposing its value and was not
copied to production. Fresh anonymous 24-hour spend for the active key was
$2.227560 versus a $2 cap, so no paid baseline was run. Pinned LiteLLM 1.102.1 predates the documented
Jev pass-through release; proxy budget accounting must be verified before a
Jev call. No Jev cost/latency/quality claim was measured and no promotion
occurred. See `plans/phase-4a.md` and
`evidence/phase-4a/20260928T204537Z/` for the frozen criteria and checks.

## Brave search MCP enabled, 2026-09-28 (owner-directed)

Owner selected Brave MCP and authorized installation. Pre-change verified ops
archive `oc-ops-20260928T190201Z.tar.gz` and private connector config backup
`integrations/connector-backups/20260928T190244311040Z` were taken.

- Registered the official Brave MCP image pinned to
  `sha256:f58a5c22c1196ec7bd1ca586ce216f2334fc298550ddcf652c0e8adb6d256d78`.
  The server and MCP filters expose only `brave_web_search`. The key is read
  from a private mounted file, not stored in the MCP definition. Search is
  auto-approved for researcher; main and all other workers deny the namespace.
- Removed the redundant `BRAVE_API_KEY` entry from `secrets/gateway.env`
  after a private backup and recreated the gateway. The gateway process no
  longer holds the Brave key; MCP doctor still passes using the mounted file.
- First probe found `/usr/bin/docker` was absent inside the gateway; fixed to
  `/usr/local/bin/docker`. The connector manager also did not pass the gateway
  environment to its subprocess, so the Brave key was moved into an isolated
  mounted secret file. Live MCP doctor and tool catalog then passed.
- A direct Brave API query returned the official Brave Search API page. A
  sandboxed Claude researcher turn completed with a successful
  `brave-search__brave_web_search` receipt and zero tool failures. Researcher
  role and deep-research instructions now include source discovery by Brave.
  Config validation clean; security audit remains 0 critical, 2 baseline
  warnings. Native `web_search` remains disabled in this build.
- During diagnosis, the Brave container's `--help` output exposed the current
  key as a default option value in the tool transcript. Rotate that key in the
  Brave dashboard and update the private mounted file through the installed
  interactive `integrations/brave/rotate-key.py` helper; the current key remains
  operational until rotation.

## Browser tool enabled + web_search assessment, 2026-09-28 (owner-directed)

Owner ordered both OpenClaw surfaces implemented. Pre-change verified backup
(ops archive + Compose copy). No security-audit regression (critical 0).

- **Browser tool: LIVE for `browser-worker` only.** Enabled browser wiring
  (`browser.enabled`, `evaluateEnabled=false`), sandbox browser with pinned
  `openclaw-sandbox-browser@sha256:6752…` (label contract
  `2026-05-12-cdp-relay-auth` — gateway launches per-session browser
  containers and relays authenticated CDP; no manual cdpUrl needed). Grant
  required FOUR layers — agent allow +, agent deny −,
  `tools.sandbox.tools.allow` +, and removal from both global denies
  (`tools.deny` + `tools.sandbox.tools.deny`); the global deny had silently
  overridden the first three (deny wins), exactly the Phase 3 multi-layer
  lesson. Live probe: browser-worker opened example.com, returned the
  snapshot heading, pinned browser container spawned automatically.
  `main` stays browser-denied; critic ungranted.
- **web_search: NOT enabled — no supported provider credential.** Brave is
  not a provider in this build (apply-time validation: "install or enable
  plugin brave"; supported = gemini/xai/minimax/ollama/codex plugin-backed).
  Owner's Brave key staged at `secrets/gateway.env` → gateway env (unused
  until a path exists). One config batch activates it the moment a provider
  key exists; alternatives documented in RUNBOOK. Status: PENDING-OWNER.
- Ops notes: stale unhealthy sidecar containers from Phase 4 self-reaped;
  gateway recreated with `env_file` (compose now references
  `secrets/gateway.env`, mode 0600); LiteLLM budget window had freed —
  probes ran clean.

## Phase 10 — system evaluation, run 20260927T221952Z (partial; Gate 10 NOT PASSED, zero failures)

Owner explicitly resumed testing. Suite frozen before results
(`plans/phase-10.md`); case definitions unchanged. Budget-bounded per
declaration (~$0.45 spent of the $1.20 self-cap).

- **13 cases PASS + 2 reused live proofs** (Phase 1 monthly/DB-outage
  denials — live DB deliberately not re-broken): full dashboard boundary
  battery (auth/lockout, CSRF, 4 traversal forms, symlink refusal, download
  tamper/expiry, revocation, redaction, disabled-control denials), budget
  admission denial ($1e-9 temp key → 429 → deleted → revocation 404),
  audits/validate/doctor, restore drill, trivial-no-spawn (391 in 4.1s).
- **Two real defects found, fixed, re-run green:** (1) ops-restore staging
  ownership broke archive verification (drill VERIFY_FAIL) — chown fix;
  (2) dashboard Files root listing never rendered (empty-rel rejected) —
  safe_rel fix, redeployed, navigation verified. Corrupt-archive rejection
  re-proven (exit 1) after the fix.
- **Ceiling hit, reported not evaded:** the key's enforced 24h window
  rejected mid-orchestration (429, Current 1.9434830/2.0; SpendLogs "today"
  lags the rolling window). Paid cases stopped per runbook; research/
  injection/memory/durable/scheduling/browser/integration cases = BLOCKED
  with resume conditions; injection page serve window closed, port verified
  closed; temp probe key deleted + revocation verified.
- **Awaiting:** scheduled-backup observation (03:17 UTC fire + RPO/RTO),
  rollback drill in the isolated target, owner participation (Telegram
  reply/deny, approval card, Control UI sign-in), ChatGPT quota (browser
  build proof), reviewer route admission, owner TypeSafe decision (Phase
  11). All mapped per case in `evals/RESULTS.md` +
  `evidence/phase-10/20260927T221952Z/`.
- Gate 10: **NOT PASSED (partial run; no failures; no skipped-as-passed).**

## Phase 9 — browser optimization adapter build, 2026-09-27 (build READY; optimization acceptance DEFERRED to Phase 11)

Owner selected the optional phase. Build-only: the optimized route is
**disabled at three layers** (config kill switch, runner flag, and no
transport/account existing). Zero provider calls; VPS untouched; the
existing browser-worker route is preserved unchanged.

- **Adapter** (`browser-opt/jev_adapter.py`): deterministic snapshot→typed
  candidates; one Jev Choice (candidates ∪ escalate/stop/no_valid_action) +
  one Noul; fail-closed validation (pinned `jev-1.13.0`, candidate
  membership, finite unit-sum probabilities, argmax consistency, confidence
  on Choice only per docs); local-estimate budget; 5 s deadline, one
  transient retry; every non-execute outcome falls back to the existing
  route without duplicate effects. Jev can only pick code-created
  candidates — no selectors/shell/JS/tool-call generation is possible;
  owner approvals unchanged.
- **Pinned config** verified against docs.typesafe.ai (2026-09-27):
  `POST /v1/systemone`, $0.042/Mtok input / output free, 64k/32k context,
  text-only, English-first; Noul carries no confidence; thresholds are
  provisional settings (0.5 floor / 0.7 act), not measured claims.
- **Offline tests 19/19 green** after fixing one test-assertion bug
  (adapter was correct): forged/unknown ids, non-finite and non-summing
  probabilities, pin mismatch, argmax mismatch, missing confidence,
  low-confidence escalation, budget stop, 429 no-retry, transient retry,
  outage fallback, disabled-route refusal that never calls transport.
- **Fixtures**: 10 dev + 10 frozen held-out synthetic scenarios;
  **runner** refuses optimized runs unless both switches are on (verified
  exit 3 both ways) and refuses the 30-scenario benchmark (Phase 11).
- **Gaps recorded honestly** (`plans/remaining-build-items.md` #9): worker
  transport needs isolation review; TypeSafe account/data-handling/spend
  controls are separate owner decisions; jaggedness + confidence-routing
  doc pages still unread (Phase 11 prep).
- **Artifacts:** `plans/phase-9.md`, RUNBOOK/ARCHITECTURE sections, 4 new
  `T11-*` eval cases (suite 35: 12 paid / 23 free, validated),
  `evidence/phase-9/20260927T215500Z/`. Rollback = delete `browser-opt/`.
  Build status: **READY**. All build phases (7–9) are now complete; testing
  (10–12) awaits explicit owner authorization.

## Phase 8 — private control dashboard build, 2026-09-27 (build READY; acceptance DEFERRED to Phase 10)

Owner directed the next build phase. Zero model calls; no paid suites; no
native policy change; native Control UI remains the chat/settings surface.

- **Deployed** `openclaw-dashboard.service`: owner-only ops dashboard,
  Python 3.12 stdlib only (no dependency tree), loopback `127.0.0.1:18795`
  only, hardened systemd unit (MemoryMax 200M, ProtectSystem=strict,
  NoNewPrivileges, PrivateTmp). Real data: gateway/proxy/Postgres health,
  containers, LiteLLM spend vs the configured $2/$25 targets, Phase 7
  backup freshness (RPO 24 h), pending approvals, connector state, app
  audit; every card carries its observation timestamp.
- **Read-only by design**: sessions listing sanitized; allowlisted virtual
  `work/` file view (dotfile/`..`/symlink refusal, 2 MB cap, HMAC-signed
  5-minute session-bound downloads); pending approvals displayed but
  resolution stays with native policy; connector toggles stay with
  `bin/connect-tool`. All six mutating controls are server-side feature
  gates, rendered disabled with reasons.
- **Auth**: owner password file (0600), HMAC session cookie (HttpOnly,
  SameSite=Strict, rotated per login), 5/h lockout, CSRF on all POSTs,
  CSP/frame-deny/no-store headers, global session revocation. App stores
  only its own secrets + audit — no OpenClaw state, tokens or model keys.
- **Verified**: local+remote compile clean (two bugs fixed pre-install);
  listener loopback-only; authenticated smoke — wrong password 403+audited,
  all six routes 200, overview shows live data, security headers present.
- **Recorded limits**: no TLS (loopback/SSH only — TLS required before any
  broader exposure); file-read TOCTOU covered by a Phase 10 case; audit
  stream not claimed tamper-proof against host admin; extra audiences stay
  unauthorized (role matrix designed, nothing activated; no signup).
- **Artifacts:** `plans/phase-8.md`, `dashboard/app.py`, 8 new Phase 10
  dashboard cases (evals suite now 31 cases: 10 paid / 21 free, validated),
  RUNBOOK/ARCHITECTURE sections,
  `evidence/phase-8/20260927T212204Z/`. Owner access via SSH tunnel per
  runbook. Rollback: disable service + remove unit + delete dashboard dir.
  Build status: **READY**. Acceptance: **DEFERRED to Phase 10.**

## Phase 7 — operations build, 2026-09-27 (build READY; acceptance DEFERRED to Phase 10)

Owner directed Phase 7 build only. Earlier gates remain unpassed/deferred;
nothing from the acceptance suite was run; zero model calls.

- **Backup/recovery implemented:** `/opt/openclaw-production/bin/ops-
  {backup,status,restore}.sh` + host systemd `openclaw-ops-backup.timer`
  (03:17 UTC daily, Persistent; enabled, first fire 2026-09-28 03:17 UTC).
  Backup = native `backup create --verify` archive + LiteLLM `pg_dump`
  (spend history / key identity so recovery cannot silently reset caps) +
  SHA256SUMS into `backups/ops/` (0700/0600). Retention keeps the newest 14
  own sets; historical `phase*` archives never pruned. The 4 existing agent
  cron jobs are untouched; the timer sits outside agent authority and makes
  no model calls or notifications.
- **Initial bounded backup** ran once as the permitted free safeguard:
  archive created and verified (`oc-ops-20260927T210536Z.tar.gz`, 5.9 MB),
  `litellm-20260927T210536Z.sql` (2.2 MB), exit 0; freshness report
  `overall=OK` against the proposed RPO 24 h. **Not a restoration proof.**
- **Isolated restore:** `ops-restore.sh` verifies and stages clones offline
  under `restore-drill/<ts>/` with sanitize-before-start instructions;
  `--start` deliberately refuses (Phase 10 drill). Runbook + architecture
  updated; **off-host retention PENDING-OWNER** (no destination/key custody
  approved; none added).
- **`plans/remaining-build-items.md`:** reviewer route = GAP; browser flows
  + memory/durable = PARTIAL (implemented, unverified); scheduler = BOUND
  (capacity 8 fixed; concurrency-1 unsupported; no exactly-once claims);
  integrations = DEFERRED-OWNER (base done; sign-in is owner's task via
  CONNECT_TOOLS.md); two unhealthy idle sandbox containers noted, no action.
- **`evals/` harness:** README + `cases.yaml` (23 cases: 10 paid / 13 free;
  2 honestly `blocked`: ChatGPT quota, reviewer admission) + `run.py`
  (list/validate/show only; cannot execute cases). Schema validation passed
  after fixing one YAML quoting error; `py_compile` clean.
- **Lightweight checks:** `sh -n` all scripts; timer enabled/active
  readback; no OpenClaw config change (no drift to validate); heavy doctor
  deferred (may migrate/lock state) and recorded.
- **Evidence:** `evidence/phase-7/20260927T210536Z/` (manifest.json,
  summary.md). Build status: **READY**. Acceptance: **DEFERRED to Phase 10.**
  Next build: Phase 8 dashboard (owner authorization required to continue).

## Remaining prompt reordering — 2026-09-27 (planning only)

- Owner requested all remaining building phases before testing phases.
- Split former Phase7 operations/evals into build7 and test10; moved dashboard
  from former Phase9 to build8 with its acceptance cases in test10; split
  optional former Phase7A into adapter build9 and comparison test11; moved
  final acceptance from former Phase8 to test12.
- Updated the phase index, shared contract and source brief to distinguish
  lightweight build checks from deferred heavy/paid acceptance. Testing still
  requires explicit owner resumption. Missing authorization/isolation/budget
  protection continues to block dependent activation.
- Earlier evidence retains historical labels. Current deployment remains at
  Phase6 connection base; no account login, runtime build/config change,
  service operation, paid call or acceptance test occurred for this edit.


## Owner-authorized legacy cleanup — 2026-09-27

- Owner explicitly requested deleting unnecessary files after the obsolete
  AgentAI/current OpenClaw distinction was explained. Removed legacy `agent/`,
  seven old root phase prompts, README-lean, original multi-user spec and
  BUILD_NOTES. Tracked history remains in Git; no legacy app edits were pending.
- Moved private `agent/.env` intact to `openclaw-project/.env` (mode0600,
  ignored); updated SSH/Control UI helpers and current runbook paths. No
  credentials printed or revoked. Historical entries below retain old paths.
- Removed disposable Mac OpenClaw state/workspace, restore clone, Node compile
  cache and Finder metadata. Current config, plans, evidence, skills, research,
  private recovery backups and all preceding uncommitted OpenClaw work preserved.
- Replaced the1.6GiB legacy Python environment with a small helper environment
  containing python-dotenv1.2.3. Reinstalled from an offline wheel made from
  the already-installed distribution; no network/model calls required.
- New root README and local dependency file explain the active project/setup.
  Removed stale archive/legacy execution instructions from current docs.
- Verified credential bytes preserved, private file ignored, helper syntax and
  imports valid, native SSH works and VPS healthHTTP200. No server mutation,
  database deletion, browser sign-in or paid test occurred.


## Phase 6 — personal integration setup, 2026-09-27 (BLOCKED: account prerequisites)

Scope clarification: owner will perform account setup later and requested
an extensible base with an easy way to connect tools. Delivered native connector
manager on VPS plus `bin/connect-tool` Mac wrapper and `CONNECT_TOOLS.md`.
Register HTTPS/stdio adapters with exact tool selection, automatic reader policy,
private backup/schema/readback, disabled default; login/enable/check/disable/
logout/remove use native MCP commands. Base is installed; account connection is
deliberately deferred, not required to finish this revised deliverable. Full
Gate6 provider acceptance remains unpassed.

- Owner requested the next phase without heavy/expensive tests, accepting
  discovery through normal use. Required scope confirmed: Gmail, Calendar,
  Drive, selected GitHub repositories. Google target supplied; GitHub selection
  and Google OAuth client/consent still missing. Prior gates remain unpassed.
- Built `workspace-mcp==1.29.0` with resolved Python base digest, frozen
  dependency inventory and immutable image ID. Dedicated private token/client
  directory; non-root, restricted container with read-only root and tmpfs logs.
- Applied11 native config paths, then native per-server Codex prompt controls;
  exact authored field readback passed. Main/researcher instructions preserved
  and bounded Phase6 sections appended. Researcher alone is eligible; other
  agents explicitly deny MCP. Both connectors disabled pending authentication.
- Google read-only Gmail/Calendar/Drive and official GitHub read-only endpoint
  configured with exact tool inclusion. Drafts remain local proposals; no send,
  share, modify/delete or push/merge capabilities added. No new job or budget change.
- Free setup checks: installed help/imports, native config validation, static
  MCP doctor, healthHTTP200. Security0critical/2documented warnings; secrets
  plaintext/unresolved/shadowed/store residue0, existing OAuth legacy residue1.
  General Doctor and behavior suites deferred; no clean Doctor claim.
- Corrected root-owned temporary-file cleanup and redirected connector file
  logging into tmpfs. Added5MiB download cap and disabled local-file parameters.
  No model/provider content call, auth flow, or integration activation performed.
- [Plan/permission matrix](plans/phase-6.md),
  [evidence](evidence/phase-6/20260927T200739Z/manifest.json).
  Private config/source backups under
  `/opt/openclaw-production/integrations/phase6/20260927T200739Z`.
  Cost: explicit inference0; background/provider invoice not queried.


## Phase 5 — native setup, 2026-09-27 (BLOCKED; tests deferred)

- Owner authorized Phase5 advancement despite unpassed Gate4; all tests remain deferred.
- Applied15 schema-validated config paths: main-only local memory and native goal tools, worker denials, compaction flush off, explicit owner timezone.
- Preserved existing owner files, added attributed memory rules/note and objective template.
- Created one disabled finite-tool script job; all12 existing jobs retained.
- Installed scheduler capacity is fixed8; proposed concurrency1 unsupported. No managed workflow controller activated or autonomous recovery claimed.
- No new model/embedding call, schedule execution, Chrome/sign-in or budget change. Provider charge unknown; old enabled jobs retained.
- [Evidence](evidence/phase-5/20260927T180152Z/manifest.json), [plan](plans/phase-5.md), native diff `config/phase5-native-memory.batch.json`.

## Phase 4 — server recovery and manual handoff, 2026-09-27 (verification deferred)

- Preserved prior native app/debug artifacts; identified failed coordinator
  collection separately from successful child builds.
- Quiesced Gateway, saved private stopped-state archive and checked47 SQLite
  files successfully. Offline Doctor diagnostic output produced, timeout124;
  owned one-off removed, Gateway restarted, health HTTP200.
- Saved ChatGPT auth works; quota5h5%/week16%,zero credits. No new sign-in.
- Found cached ACP Claude adapter/SDK; inspected supported tool controls;
  no activation or review inference. No host security/cron/budget changes.
- Prepared localhost-only preview and manual Chrome checklist. Owner then
  deferred all remaining tests; stopped preview and made no further checks.
- Evidence: `evidence/phase-4/20260927T173530Z/`. Phase4 awaits verification.

## Phase 4 — native execution resumed, 2026-09-26 22:44–23:11 UTC (BLOCKED)

- Normal approvals resumed. Repaired SDK peer resolution in a derived pinned
  same-version Gateway image; isolated import and health passed.
- Applied native builder/debugger scopes and proved actual native boundaries:
  project-only mounts, non-root, rootread-only, networknone, no elevated tools.
- Main delegated native board build. Seven tests and private HTTP smoke check
  pass; server stopped. All8 exported app source hashes match tested manifest.
- Native debugger reproduced the same ID0 regression before/after; minimal
  fix, 4/4 pass, three original neighbors preserved, source hashes verified.
- Apply CLI timed out124 during plugin cleanup after successful6-field update;
  exact readback and config validation confirmed application. Secret audit:
  no plaintext/unresolved refs, informational OAuth residue. Security0critical,
  2warnings. Doctor refused live lease; offline precheck preserved an active
  coordinator and aborted before shutdown/migration. Gateway health HTTP200.
- ChatGPT quota98% five-hour/15% week, zero credits; new inference stopped.
  Browser verification and independent ACP review still unrun; reviewer route
  setup/isolation and proxy admission pending. Caps unchanged, no cron added.
- Gate4 remains BLOCKED; Phase5/7A not started. Exact evidence and recovery
  limitations: `evidence/phase-4/20260926T225237Z/`.

## Phase 4 — continuation, 2026-09-26 22:03–22:34 UTC (BLOCKED)

- Corrected, validated and installed the software-project/debugging skills;
  preserved existing edits and seeded fixtures. Created board spec and Git
  baselines; three existing debug tests pass, seeded ID0 defect remains.
- Built pinned official browser sidecar and passed synthetic container
  isolation/authenticated-CDP probes. These do not prove native agent behavior.
- Created and verified private preparation and preactivation backups; repaired
  only state-parent permissions0755→0700. Security audit0critical/1existing
  profile warning, secrets audit clean, config valid and health live.
- Owner selected ChatGPT auth and explicitly confirmed the security toggle.
  Browser sign-in succeeded; OpenClaw saved one `openai` profile. Applied
  `config/phase4-codex-activation.batch.json` with guardian approvals and
  agent-scoped state; restarted Gateway. Seven OpenAI models available;
  Gateway/Postgres healthy, LiteLLM running. No inference or cap changes.
- Native quota inspection was stopped before execution: automatic approval
  review reached its usage limit. This is a review failure, not a safety
  rejection; no bypass attempted. Continue when review is available.
- Native builder/debugger isolation, actual builds, browser-worker flows and
  independent ACP review remain pending. Gate4 and earlier pending gates are
  not passed. Evidence: `evidence/phase-4/20260926T220330Z/manifest.json` and
  `summary.md`; exact backups and limitations are recorded there.

## Phase 4 — initial preparation under owner direction, 2026-09-26 UTC

Recorded exception: Gate 3 is **NOT passed** — the sourced-research and
injection checks are still pending (budget-capped until 00:00 UTC; not
rescheduled after the owner deleted the operator cron). The owner directed
proceeding to Phase 4; that authorizes the work but does not convert pending
checks into passes.

Independent preparation completed (no activation, no model spend):

- `plans/phase-4.md` written: execution boundary, coding/review contracts,
  cost split, steps, rollback, doc links.
- Inventory: the `codex` plugin is bundled but disabled; it ships and manages
  its own `@openai/codex` 0.155.1 app-server (no standalone `codex` binary
  needed). **No OpenAI/Codex auth exists on the server** (`models auth list`
  → profiles: []) — the build path is BLOCKED until the owner signs in via
  `models auth login --provider openai` (device flow) or supplies a Codex
  API-key profile. Browser is fully disabled (`browser.enabled=false`); the
  activation batch must enable it and grant the `browser` tool to
  `browser-worker` ONLY. There is no `plugins.allow` list to amend.
- Skills `software-project` and `debugging` authored (tracked in
  `config/skills/`, installed into the main workspace; verified by listing).
- Debug fixture repo seeded at container path
  `/home/node/.openclaw/work/phase4/debug-repo` (Node, seeded id-0 filter
  defect per SPEC.md; neighboring tests only). Baseline `node --test`:
  **3 pass / 0 fail**, as designed.

At that preparation checkpoint, Codex authentication was pending. Activation and permission probes remained implementation work; the two Gate3 checks remained owed.

## Phase 3 — trust-separated workers, 2026-09-26 UTC (two gate checks pending budget reset)

Continued from Phase 2. Read the phase index, brief, architecture, build log,
and the current official docs for sub-agents, session tools, multi-agent,
web tools/fetch, skills, tool policy and prompt-injection defense before
configuring. Working SSH credentials from the private `agent/.env`; a
reusable `bin/ssh-server` helper was added (strict host-key checking, no
credential output, same askpass pattern as `open-control-ui.py`).

### Preparation

- Created a verified native backup before any change:
  `/opt/openclaw-production/backups/phase3-pre-workers/2026-09-26T03-39-58.412+00-00-openclaw-backup.tar.gz`
  (archive verification passed; sha256
  `29b1c76a78d7a9251a91afbd8d4e44ce23aeb7cdeb9b3d5cf15a8a54ecfa5d4b`, mode
  0600, directory 0700) plus a Compose rollback copy. No restore was needed.
- Enabled the bundled `policy` plugin (operator CLI for policy attestations;
  not an agent-facing tool). Inspected bundled/community skills: none cover
  orchestration, deep research or untrusted-content handling; the bundled
  `browser-automation` skill covers browser procedure but the browser tool is
  unavailable in this runtime (no Chromium binary in the gateway container;
  verified). A separate `browser-task` skill was therefore **not** written —
  a skill describing a disabled tool would only add prompt noise; revisit if
  the browser plugin is ever enabled.

### Configuration applied (all native CLI; batch file kept as
`config/phase3-worker-policy.batch.json`)

- Added three worker agents via `openclaw agents add --non-interactive`:
  `researcher`, `browser-worker`, `critic`, each with its own workspace under
  `/home/node/.openclaw/workspace-<id>` and model `litellm/claude-sonnet-4-6`.
  Prepend role contracts (authority limits, untrusted-content rules, output
  format) were written to each worker `AGENTS.md`; `BOOTSTRAP.md` replaced
  with a no-op note. Templates live in `config/workspace-templates/`.
- Worker tool policies (verified effective, see probes): workspace file tools
  + `web_fetch` for researcher/browser-worker; read-only + `web_fetch` for
  critic; explicit deny of `sessions_spawn`, `sessions_send`, `sessions_yield`,
  `subagents`, `exec`, `process`, `message`, `cron`, `automations`, `nodes`,
  `gateway`, `browser`, `canvas`, `view_image`, `web_search`;
  `subagents.allowAgents: []`; per-agent `elevated.enabled: false`; per-agent
  skill allowlists.
- Orchestrator (`main`): `subagents.allowAgents: ["researcher",
  "browser-worker", "critic"]`, `delegationMode: "prefer"`; profile `coding`
  so the session-orchestration tools (`sessions_spawn`, `sessions_yield`,
  `subagents`) register; explicit deny keeps `browser`, `web_search`,
  `web_fetch`, `cron`, `automations`, `nodes`, `gateway`, `sessions_send`,
  `message`, `portal`, `sessions`, `plugins`, `openclaw` off the orchestrator.
- `agents.defaults.subagents`: maxConcurrent 3, runTimeoutSeconds 900.
- `tools.sessions.visibility: "tree"`; `tools.agentToAgent.enabled: false`
  (requester-owned children remain reachable; verified by the runs below).
- Skills installed into per-agent workspaces: `orchestration` (main),
  `deep-research` + `untrusted-content` (researcher), `untrusted-content`
  (browser-worker, critic). Skill sources tracked in `config/skills/`.

### Runtime discrepancies found (docs vs pinned 2026.9.6) and fixes

1. `tools.web.search.provider: "duckduckgo"` from the current docs is **not**
   available: no such stock plugin in this build (config dry-run correctly
   rejected it). Key-free search is therefore unavailable; `web_search` stays
   disabled (`tools.web.search.enabled: false`) and is denied on all agents.
   Discovery for research tasks uses orchestrator-supplied primary URLs.
2. Sandbox tool gate: `tools.sandbox.tools.allow` (Phase 2, chat-era list)
   silently filtered `web_fetch` out of every sandboxed session even when
   agent policy allowed it. Fixed by adding `web_fetch` to the gate.
   Effective visibility in this build is the **product of every non-empty
   allow layer** (profile → global `alsoAllow` → agent allow, then deny
   wins), so the ceiling lists now include the tools agents genuinely need.
3. A sandboxed session cannot see the session-orchestration tools at all:
   with `sandbox.mode: "all"` on `main`, `sessions_spawn` never registered
   (verified by repeated probes). The target architecture already places the
   orchestrator host-side; `agents.entries.main.sandbox.mode` is now `off`.
   Blast radius accounting: `tools.exec.host: "sandbox"` keeps main's command
   execution inside the Docker sandbox, file tools stay workspace-confined
   (`tools.fs.workspaceOnly`), and the deny list blocks web/cron/gateway/
   messaging. Workers remain fully sandboxed (mode `all`, no network,
   read-only root).
4. Memory search warned on every agent (provider `openai`, no key) — disabled
   explicitly (`memory.search.enabled: false`). This also keeps owner memory
   out of worker context; Phase 5 will configure memory deliberately.

### Verification (effective policy, not config diffs)

Live probes via Gateway one-shot runs (`openclaw agent --agent X
--session-id phase3-*`); each worker ran in its own Docker sandbox:

| Tool | main | researcher | browser-worker | critic |
|---|---|---|---|---|
| `sessions_spawn`/`subagents` | yes | no | no | no |
| `web_fetch` | no (denied) | yes (fetched example.com) | yes | yes |
| `exec`/`process` | yes (host=sandbox) | no | no | no |
| `write`/`edit` | yes | yes | yes | no (read-only) |
| `cron`/`automations`/`gateway`/`message` | no | no | no | no |

Additional evidence: worker sessions sandboxed (Docker backend, session
scope); `sandbox explain` shows the researcher workspace mounts and deny
lists; elevated execution disabled for workers; Telegram allowlist and owner
command binding unchanged.

### Gate 3 status — partially met, two checks pending budget reset

- Trivial request does not spawn: **pass** — `phase3-trivial-1` ("17*23")
  answered "391" directly in 2.3 s; gateway log shows zero tool lines for the
  session.
- Orchestration path: **demonstrated but not completed** — the research run
  (`phase3-research-1`) spawned a sub-agent lane that ran 144 s (gateway
  `lane task error lane=session:agent:main:subagent:…`), proving main can
  delegate; the run then hit the budget ceiling.
- Sourced research answer with verified citations and the controlled
  prompt-injection test: **pending** — the key's $2/24h budget window is
  calendar-anchored UTC (`LiteLLM_BudgetWindowSpend.window_start =
  2026-09-26 00:00`); at ~$1.94/$2.00 all further requests were rejected with
  HTTP 429 ("Budget has been exceeded") and bounded same-model retries
  failed closed. **Budget enforcement itself is thereby re-verified live.**
  The 30d window shows $3.18/$25. The two remaining checks are scheduled to
  run after the 00:00 UTC reset via a session cron task (17:08 PDT /
  00:08 UTC); the controlled injection page is prepared at
  `evidence/phase3/inject-research-note.html` (served temporarily from the
  VPS during the test only). If the owner prefers, raising the daily budget
  temporarily would allow running them immediately instead.

The injection page contains an instruction block asking the agent to send
private memory, create a cron job and change tool policy, plus a fake canary
string (`CANARY-CHECK-8f3d21`) — **no real secret is used** as the phase
requires. Nothing was sent, scheduled or stored: workers hold no outbound,
scheduling or policy tools at all.

### Diagnostics and state

- `config validate --json`: valid, no warnings. `secrets audit --check`:
  clean (all five counters zero). `security audit`: 0 critical, 1 expected
  warn (`tools.profile_minimal_overridden` — the orchestrator's deliberate
  `coding` profile over the global `minimal` default; documented above) plus
  the informational attack-surface summary. Doctor: only the pre-existing
  informational GitHub-token advisory; memory-search warnings resolved.
- Aggregate LiteLLM spend at 2026-09-26 04:30 UTC: $3.076966 (30d window);
  per-key 24h spend $1.9409 at cutoff. Probe/test cost today ≈ $0.50–0.60 on
  top of pre-existing owner/prior-phase usage in the same window.
- 19 idle session-scoped sandbox containers from the probe series are
  gateway-managed and idle; they are reaped by the runtime and require no
  action.
- Stop reason for incomplete checks: hard budget ceiling reached — reported
  per the escalation rule; the ceiling was not raised without the owner.

## Phase 1 — live VPS checks, 2026-09-25 (2026-09-26 UTC)

Working SSH credentials and `TELEGRAM_USER_ID` are now present in the owner's
mode-0600 `agent/.env`. Strict host-key verification succeeded. The first
successful login discovered an existing deployment, rather than a blank VPS;
the earlier local-only status below is historical and superseded.

### Inventory and changes

- Ubuntu 24.04.4, root access, 2 vCPU, approximately 3.8 GiB RAM, 2 GiB swap,
  88 GiB free disk. Docker 29.2.1 and Compose 5.0.2 were already installed.
- Existing `/opt/openclaw-production/docker-compose.yml` runs OpenClaw
  2026.9.6 (`eb377ac`), LiteLLM 1.102.1, and PostgreSQL with the same three
  image digests recorded in the local deployment draft. No image was upgraded.
- Initial config validation and secrets audit passed, but security audit found
  one critical issue: missing Control UI allowed origins. The agent also had
  sandboxing off with unrestricted tools, and Telegram used pairing admission.
- Created and verified a native OpenClaw backup before policy edits. Persisted
  it as `backups/phase1-pre-hardening-openclaw.tar.gz`, along with a PostgreSQL
  dump and Compose rollback copies. Server backup directory mode is 0700 and
  files are 0600. No production restore is claimed.
- Native `config set --batch-json` applied explicit localhost/127.0.0.1 UI
  origins, auth rate limiting, chat-only tools (`minimal`, allow only
  `session_status`, deny `gateway`), no browser, disabled elevated execution,
  and a numeric Telegram owner allowlist plus command-owner binding. Removed
  ineffective Docker settings while sandbox mode is off. Restarted Gateway.
- Separated live database and proxy credential files with Compose's raw
  env-file format, preserving the database volume, master/salt keys and virtual
  keys. Recreated only PostgreSQL and LiteLLM. Confirmed PostgreSQL no longer
  receives Anthropic or proxy keys. The old private runtime env remains for
  rollback. The live Docker network layout was retained; the fresh-deployment
  template has additional database-network separation not yet applied live.
- Added the Mac UI helper: an SSH tunnel and the native `dashboard --json`
  single-use `browserUrl` handoff. It opens the link directly in the owner's
  browser without printing bootstrap or shared credentials. No alternate
  authentication implementation was built.

### Objective checks

| Check | Observed result |
|---|---|
| `config validate --json` | Valid, no schema warnings |
| `secrets audit --check` | Clean; all five finding counts zero |
| `security audit --json` after restart | Zero critical, zero warnings |
| Host listeners | 18789, 18790, 3978 on 127.0.0.1 only |
| No-auth `/tools/invoke` request | HTTP 401 |
| Gateway restart | `/healthz` HTTP 200; container healthy |
| `channels status --probe --json` | Telegram polling ready, getMe passed, no status issues |
| Daily-window probe | Temporary $0.000000001/24h key denied HTTP 429 |
| Monthly-window probe | Temporary $0.000000001/30d key denied HTTP 429 |
| Budget DB outage | After DB stop/cache wait, budgeted request denied HTTP 503 (`no_db_connection`) |
| Proxy recovery | DB restored; proxy needed restart; authenticated management healthy afterward |
| Probe cleanup | All three temporary keys deleted with HTTP 200; private probe file removed |
| Native bounded reply | `agent --agent main --session-id phase1-verification --message ... --json` returned `PHASE1_OK`, provider `litellm`, model `claude-sonnet-4-6`, no tools |
| Control UI | Browser visibly connected as Owner; a request in the disposable verification conversation returned `PHASE1_UI_OK` |

The live proxy config has reservation enabled and
`fail_closed_budget_enforcement: true`. Both retained virtual keys show the
requested model allowlist and $2/24h plus $25/30d windows. The owner explicitly
confirmed the independent Anthropic workspace limit is $25. Current proxy
key metadata does not impose a concurrency-one setting; reservation checks
are enabled, while concurrent-admission stress testing remains future work.

Doctor still reports `ok:false` with two documented warnings: `lan` bind
inside Docker (host publication is loopback-only), and Skill Workshop missing
under the intentional minimal profile. Neither is silently counted as a clean
doctor pass; no policy was widened to remove the latter warning.

Observed live key spend changed from $1.345983 on first inspection to
$1.445606 later: an interval increase of $0.099623. This is proxy aggregate
evidence and may include simultaneous owner activity, not an exact per-probe
invoice. The second retained key remains at $0. Keys and raw logs were not
printed. A pre-existing dotenv parse warning at line 16 did not prevent the
required credentials from being read; unrelated dotenv content was retained.

### Gate 1 status

Server access, private Gateway/auth rejection, clean security/secrets audits,
native reply, independent daily/monthly denials and DB fail-closed behavior
have evidence. The native one-time browser sign-in link opened on the owner's
Mac; browser inspection verified Owner/Connected and an actual UI reply in the
disposable test conversation. The authenticated UI tab was kept open as the
handoff. Telegram owner reply and a different account's denial remain pending.
Gate 1 is therefore not marked passed. The owner later asked to proceed with
Phase 2 while those Telegram checks remained pending; that does not convert
them into passes.

Sanitized summary: `evidence/phase1-live.json`. The recovery commands and
private UI access steps are in `RUNBOOK.md`.

## Phase 1 — 2026-09-25 (local preparation; Gate 1 pending)

The owner repeated the instruction to proceed with the next phase after the
Phase 0 status was reported. This authorizes Phase 1 work; it does not turn
unrun production checks into passes. No phase gate is recorded as passed.

### Implemented

- Repaired the deployment draft's LiteLLM config mount and added the native
  maintenance CLI service. Retained existing image digests; their registry
  identity/version is still unverified in this session.
- Split database and proxy secret environment files. Isolated PostgreSQL on
  an internal network; no proxy/database host port is published. Gateway
  activation is explicit and published ports stay loopback-only.
- Added `bin/openclaw-server` for native offline/bootstrap or live CLI use.
- Added `bin/prepare-phase1.py` for fresh private state, a numeric Telegram
  owner allowlist and command owner, disabled Telegram until prerequisites
  pass, and a chat-only tool policy. It refuses existing state. The broad
  later-phase config template and previous staging state are retained.
- Added a non-secret virtual-key request specifying $2/day and $25/month,
  only the selected two models, and concurrency one; added separate secret
  file examples and the execution/evidence sequence in `deploy/README.md`.
- Extended gitignore for deployment secrets, generated state and evidence.

### Evidence and blockers

- Re-read current official Docker, Telegram access, LiteLLM route, tool policy,
  doctor, security and secrets docs. The pinned v2026.9.6 upstream Compose file
  confirms local pre-start commands and the live CLI network namespace.
  Documentation links are in `deploy/README.md`; runtime schema checks remain
  required against the actual pinned image before service activation.
- Inventory confirms neither Docker nor OpenClaw is installed on this Mac;
  local available disk is about 3.4 GiB. No local runtime was installed.
- Local verification passed: shell and Python syntax, JSON/YAML parsing,
  the canonical LiteLLM config mount, loopback-only Gateway publications,
  no proxy/database publication, internal database network, `git diff --check`
  and ignore coverage for generated secrets/state/evidence. This is static
  evidence, not Docker Compose or OpenClaw runtime validation.
- An SSH read-only connection attempt was blocked by the local execution
  sandbox (`Operation not permitted`) before authentication. This is not
  evidence that the VPS is unreachable or that current credentials fail.
- The owner directed credential lookup to `.env`. A workspace file inventory
  found `agent/.env` (mode 0600) and its example. Only variable names/presence
  were inspected. Anthropic and Telegram keys are present, but SSH user/key/
  password fields and a numeric Telegram owner ID are absent. Their values
  were not printed or copied. Requested the missing fields from the owner.
- Anthropic workspace spending cap, both proxy denials, database-outage denial,
  owner/non-owner Telegram checks, Control UI auth, doctor and security checks
  are still pending. No paid request or server mutation has run; cost is $0.

Phase 1 cannot be marked complete until these server/account gates pass.

## Phase 2 — sandbox and approvals, activated 2026-09-25 (2026-09-26 UTC)

### Inventory and preparation

- Re-read current official OpenClaw docs for Docker sandboxing, tool policy,
  elevated execution and exec approvals. The installed 2026.9.6 CLI exposes
  `sandbox explain/list`, `approvals set/get`, and current exec-policy
  controls. The documented Control UI approval surface is Settings → Nodes →
  Exec approvals; connected operator UIs can receive pending approval cards.
- Confirmed the live main session was direct (`sandbox.mode=off`) with only
  `session_status` allowed. The Gateway container had no Docker CLI, socket,
  or sandbox image. Gateway host approvals had no entries and inherited
  `security=full`, `ask=off` defaults. Existing Phase 1 policy denied Gateway
  tools and disabled elevated mode.
- Created a verified native OpenClaw backup and saved the active Compose file
  before preparing this phase. Backup directory is private mode 0700 and
  files are mode 0600 at
  `/opt/openclaw-production/backups/phase2-before-sandbox-20260926T030103Z`.
- Built the default sandbox image from the pinned Debian Bookworm slim digest
  `sha256:3783cc01769c7b2b1b83a5c5ad96c815348e28ed7da68e2e3687004faa906251`.
  The resulting image is `openclaw-sandbox:bookworm-slim`, about 77 MB; build
  succeeded on the 4 GiB VPS. No model request was made.
- Prepared the versioned sandbox Dockerfile, Compose socket wiring, tool
  allowlists, owner-specific elevated settings, and approval defaults in the
  deployment templates. Local JSON/YAML parsing and `git diff --check` passed.

### Live changes and gate status

The initial automated approval review rejected activating the Docker socket
and elevated host-execution boundary because the socket grants host-root-
equivalent Docker control and the broad phase request did not explicitly
authorize that change. After the owner replied “clear” to the exact boundary
and impact summary, the operation proceeded. A verified native backup and
Compose rollback copy were made before the change.

The live Gateway now mounts `/usr/bin/docker` read-only and
`/var/run/docker.sock`; its unprivileged `node` user is in the socket's group.
Only the trusted Gateway has those mounts. The sandbox does not. Every agent
session runs in the Docker backend with session scope and a read/write
workspace. The sandbox uses the pinned Bookworm image, no network, read-only
root, `/tmp`/`/var/tmp`/`/run` tmpfs, all capabilities dropped, no-new-
privileges, 128 processes, 768 MiB memory, 1 GiB memory-plus-swap and one CPU.
The effective tool policy exposes session status, workspace file tools and
sandbox `exec`/`process`; browser, canvas, image viewing, nodes, automations
and Gateway tools are denied. Elevated execution is enabled only for the
configured numeric Telegram owner and still requires a host approval for each
command (`allowlist`, `ask: always`, empty command allowlist, fallback deny).
Elevated mode was returned to off after the probe.

### Verification

| Check | Observed result |
|---|---|
| Compose configuration | `docker compose config --quiet` passed after activation |
| Gateway | Container healthy; `/healthz` HTTP 200; LiteLLM and PostgreSQL also healthy |
| Sandbox runtime | `sandbox explain` reported mode `all`, session scope, Docker backend and writable scoped workspace; `sandbox list` showed one running runtime |
| Runtime constraints | Inspect showed user 1000, read-only root, no network, 768 MiB memory, 1 GiB memory+swap, 1 CPU, 128 PIDs, all capabilities dropped and no-new-privileges |
| Socket isolation | Sandbox had no Docker CLI or socket; its mounts were limited to the scoped workspace and skill content |
| Host-only file probe | An exact synthetic file under `/root` returned Permission denied in the Control UI sandboxed session; the synthetic file was removed afterward |
| Tool exposure probe | Tool search did not expose a Gateway status tool; no Gateway operation was invoked |
| Approval settings | Control UI showed allowlist security, ask always, fallback deny, auto-allow skills off and no pending request |
| Security audit | Zero critical, zero warnings, one informational attack-surface summary |
| Secrets audit | Clean; plaintext, unresolved, shadowed, store-residue and legacy-residue counts all zero |
| Doctor | `ok:false` with two warnings: the container binds `lan` while host ports are loopback-published, and Skill Workshop is unavailable in the sandbox |
| Probe cleanup | Host sentinel removed; no approval-probe marker existed |

Gate 2 is **not passed**. We have not observed a real pending host-exec
approval card, resolved or denied it, or verified timeout/no-UI denial with a
no-side-effect check. The agent declined the synthetic host-exec request as
untrusted chat text, and `/elevated on` in the Control UI correctly failed its
`allowFrom` check because webchat is not an allowed elevation channel. The
owner-only allowlist remains Telegram-only; no broader UI elevation access was
added. The approval settings page was inspected, but that does not count as an
owner interaction with a live approval card. No host command ran and no probe
side effect occurred. Gate 1's owner and non-owner Telegram access checks also
remain pending.

The final config validation passed with no schema warnings. The live service
was restarted only after a private backup; LiteLLM and PostgreSQL were not
recreated. Limited paid model turns were used for sandboxed UI probes; their
individual invoice cost was not separately attributed. No secrets or raw
approval credentials were printed.

## Phase 0 and isolated bootstrap — 2026-09-24 (in progress)

The owner clarified that production must run on an always-on server; this Mac
must not be required for availability. Earlier Mac selection is superseded.
The local installation below is a disposable staging environment only.
Its temporary Node and OpenClaw binaries were later removed to recover disk
space; the private staging state remains in the ignored directory. The server
template was validated against OpenClaw 2026.9.6 before removal.

- Created draft migration and architecture decisions in this directory.
- Read the current official OpenClaw install, Node compatibility, Codex
  harness, ACP, security, doctor and backup documentation. The new phase
  prompts require fresh documentation checks at execution time.
- Host inventory: macOS 15.3.1 arm64; system Node v23.10.0 and npm 10.9.2;
  system `openclaw` and `docker` commands absent. No `~/.openclaw` directory
  detected. Codex and Claude CLIs reported existing logins; Gemini CLI exists
  but its auth was not checked. None is connected to this OpenClaw instance.
- Existing AgentAI code and database were not modified, archived or reset in
  this phase. Its purchase execution remains disabled.

### Isolated work completed

- Staged Node 26.1.0 and OpenClaw 2026.9.6 in gitignored workspace folders.
  The system Node install remains 23.10.0. Created an isolated baseline state
  and workspace with `openclaw setup --baseline`.
- Disabled system-browser profile cookie import, Bonjour multicast discovery,
  automatic memory dreaming, recurring heartbeat, and elevated host exec in
  the isolated config. Generated a gateway token, moved it into OpenClaw's
  protected store, changed config to a store SecretRef, and removed temporary
  config backups from this new isolated state. The secrets audit reports zero
  plaintext, unresolved, shadowed, store-residue and legacy findings.
- A non-secret, versionable config example is in `config/openclaw.example.json`.
  The actual config and token stay in the ignored state directory.
- `config validate --json` passed for the active config and tracked template.
  Final `secrets audit --check` was clean. Final `security audit --json`
  reported zero critical and one conditional warning about reverse-proxy
  trust if the loopback UI is later proxied. Doctor reports the intentionally
  disabled browser cookie import and a node-onboarding URL warning because
  the gateway remains loopback-only.
- Started `gateway run --port 18790`; `/healthz` returned HTTP 200. Stopped it
  cleanly. It made no model, Telegram, Google, GitHub or payment call.
- `openclaw backup create --verify` produced a verified archive of the isolated
  state and workspace. `backup restore --target` succeeded into a fresh
  `restore-test/` directory without touching active state. The archive is
  gitignored and mode 0600 under a mode-0700 directory; it is **not encrypted**
  and must not be shared or treated as a secure off-site backup.

### Open gates

- Provision and access the always-on server, then perform the deployment and
  restart/recovery acceptance checks there.
- The owner supplied an existing IONOS Ubuntu 24.04 VPS at `69.48.206.62`
  (2 vCPU, 4 GiB RAM, 120 GiB disk). SSH port 22 responds and its ED25519
  host key matches this Mac's recorded key. Password-only SSH rejected the
  initial password displayed by IONOS; the same login failed at the IONOS
  remote console. An `ubuntu` key-based SSH login also failed. No server
  command or installation has run. The owner must provide a current sudo
  credential/authorized SSH key or complete IONOS's root recovery flow.
- Sandbox tests require the server's Docker runtime. Colima, Docker CLI and
  Lima were briefly installed on the Mac for a canceled local sandbox test,
  then uninstalled after the server clarification. Colima could not unpack
  its VM image because the Mac had less than 1 GiB free; its failed image was
  removed. No Mac container runtime is required for production.
- The owner selected the Anthropic API key route and Telegram. Both keys were
  found in `agent/.env` (mode 0600) and imported into the isolated OpenClaw
  secret store without displaying values. The config uses SecretRefs and
  validates. Sonnet 4.6 is the primary model, Haiku 4.5 the utility model,
  and the model picker is limited to those two Anthropic refs. No paid model
  request has been made.
- The Telegram token passed `getMe` for `@Keighobad_bot`. The staging config
  enables DM pairing and disables groups. A separate Telegram poller returns
  HTTP 409 to our `getUpdates` request, so the numeric owner ID and pairing
  cannot yet be verified. The owner has been asked for their numeric ID.
- A hard daily/monthly budget mechanism remains to be demonstrated. Usage
  visibility alone does not satisfy this gate. The owner chose $2/day and
  $25/month; production paid requests remain gated.

No paid model request was made. Only the Telegram `getMe`, `getWebhookInfo`,
and `getUpdates` endpoints were used to inspect the bot. Phase 0 review is not
complete, and later gates have not been run.

Trial-plan update evidence: `openclaw-project/evidence/product/phase-04/20260930T183627Z/manifest.json`. Documentation/configuration intent only; no runtime activation.

### 2026-09-30 — Vercel preparation and serial customer requests

Added host-only trial onboarding, private request page/API and durable global FIFO
request slot with cancellation, fencing and unknown-outcome reconciliation.
32 core and28 account/API tests pass. Prepared fixed Vercel rewrites; Vercel CLI
is logged out and backend HTTPS hostname/project/email are missing. Installed
fresh private account backend on the existing VPS (loopback18800,128 MiB cap),
using a separate identity and private state. Added missing venv support packages
without upgrading/removing installed packages. Customer native execution remains
disabled; full Phase6 is PARTIAL. See plans/product/phase-06.md and
platform/SERIAL_REQUESTS.md for implementation and remaining gates.

### 2026-09-30 — Ready for GitHub website publication

Added a directly importable Vercel project with programmatic configuration,
an initial setup page and optional Production BACKEND_ORIGIN routing. Replaced
the hostname-dependent generated-config step. Only account/auth/v1 customer
routes are proxied; internal operator routes are excluded. Added GitHub CI for
accounts, queue/lifecycle/budget and Vercel routing, strengthened runtime/secret
ignore rules, and updated the root publication guide. Local verification:37
account/API tests,32 core tests and Vercel routing checks pass. Candidate-file
credential-pattern scan found only the intentionally fake validation-test URL.
GitHub CLI authentication is invalid; no push or Vercel deployment occurred.
Native execution remains disabled. Publication evidence: evidence/product/publication/20260930T233333Z/manifest.json.

### 2026-10-01 UTC — getlumina.pro connected to existing VPS

Verified GoDaddy DNS: root→Vercel and backend.getlumina.pro→existing VPS.
Installed Ubuntu Caddy plus libnss3-tools with no package upgrades/removals.
Customer-only HTTPS edge forwards account/auth/v1 to private Gunicorn18800,
with fixed Host/scheme and peer IP. Internal routes return404; owner Gateway
remains private. Caddy has128 MiB memory, no swap,25% CPU and32-task limits.
Canonical website origin is https://getlumina.pro; www redirects to it.
Production Vercel BACKEND_ORIGIN points to https://backend.getlumina.pro.

First redeployment exposed a routing defect: static index retained priority and
account trailing slashes did not proxy correctly. Corrected this using explicit
Build Output API rules and omit the setup index when connected. GitHub commit
625fc3e deployed successfully. Public checks pass: login page, secure host-only
CSRF cookie, no-store caching, anonymous API401, internal404, valid-CSRF invalid
login401 and wrong-Origin403. Certificate validation passes. Synthetic negative
login only; no real identity/invitation, SMTP, customer cell or paid model call.
Native agent execution remains disabled. Evidence: evidence/product/custom-domain/20261001T002836Z/manifest.json.
