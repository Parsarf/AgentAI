# Continuation prompt — AgentAI / Lumina

You are continuing an existing implementation, not planning a replacement.
Work in `/Users/parsa/AgentAI` (or a clone of `https://github.com/Parsarf/AgentAI`).
Read this entire handoff, the relevant repository instructions, and the referenced
files before making changes. Preserve the canonical phase numbering, order,
requirements, acceptance gates and existing working deployment.

## Immediate assignment and phase order

**Resume Phase 4 — Isolated customer agent lifecycle.** It is not complete.
Do not restart Phase 1 or jump to Phase 7. Independent pieces of Phases 5 and 6
were built while native provisioning remained blocked; reuse them and close their
missing integration gates in order: **4 → 5 → 6**, then follow the existing index.
Follow each phase's own scope and close-out instructions; don't interpret this
handoff as permission to run all later phases or deferred paid evaluations.

The canonical order is:
1. Product contract; 2. Platform foundation; 3. Customer accounts;
4. Tenant provisioning; 5. Usage admission; 6. Dashboard chat;
7. Telegram linking; 8. Files/artifacts; 9. Live work;
10. Native capabilities; 11. Integrations; 12. Optional optimization build;
13. Billing; 14. Operations; 15. System acceptance;
16. Optional optimization evaluation; 17. Private beta; 18. Launch;
19. Optional customer-funded purchases.

Use the existing complete prompt in
`phase-prompts/openclaw/phase-04-tenant-provisioning.md`. Do not replace, merge,
renumber or drop phases. Preserve all 121 requirement ledger entries and legacy
acceptance cases. Build readiness and full acceptance are separate.

## Read in this order

1. Applicable `AGENTS.md` / repository instructions, then root `README.md`.
2. `phase-prompts/openclaw/README.md`, `execution-contract.md`,
   `coverage-ledger.md`, and the full Phase 4 prompt. Read Phase 5 and 6 prompts
   to understand integration dependencies, not to skip Phase 4.
3. `product/CONTRACT.md`, `plan.json`, `deployment-policy.json`,
   `EXISTING_VPS_TRIAL.md`, `COST_CAPACITY.md` and `cost-inputs.json`.
4. `openclaw-project/BUILD_LOG.md` (especially its latest appended entries),
   `ARCHITECTURE.md`, `MIGRATION_DECISIONS.md`, and `RUNBOOK.md`.
5. `openclaw-project/plans/product/requirements.json` / `requirements.md`,
   `phase-04.md`, `phase-04-single-vps-assessment.md`, `phase-04-capacity.json`,
   `phase-04-resume-host.json`, `phase-05.md`, and `phase-06.md`.
6. `openclaw-project/platform/README.md`, `ARCHITECTURE.md`, `THREAT_MODEL.md`,
   `API_MATRIX.md`, `openapi.json`, `BUDGET.md`, `SERIAL_REQUESTS.md`,
   `accounts/README.md`, `agentai_platform/lifecycle/README.md`,
   `deploy/README.md`, `deploy/caddy/README.md`, and `deploy/vercel/README.md`.
7. Inspect actual source and sanitized evidence relevant to the next change.
   Start with `agentai_platform/lifecycle/{coordinator,fleet_plan,types}.py`,
   `capacity.py`, `budget.py`, `request_queue.py`, `store.py`, `adapters.py`,
   and `accounts/{settings,middleware,views,requests,lifecycle,usage,services}.py`.
   Also inspect management commands, immutable SQL/Django migrations and tests.

Some phase records/index paragraphs describe historical snapshots and still say
mail/public ingress were disabled. Later BUILD_LOG entries, deployment evidence,
source and this handoff supersede those historical status claims. Preserve the
historical evidence; append current findings instead of rewriting old manifests.

## User decisions — keep these

- Use the existing service-operated IONOS VPS first: approximately 2 vCPU,
  4 GiB RAM, 120 GiB disk. Customers supply no servers or domains.
- Do not require an upgrade or dedicated customer VMs to finish implementation.
  A later resize changes throughput, not accounts/domain/product features.
- Invite-only beta: at most two trial account records; **one global running
  customer task/cell**, with other users waiting. Separate every customer's
  chats, memory, files, workspace, secrets, tools, credentials and budgets.
- Bounded per-account intake: three waiting requests. Stop idle cells only after
  safe drain; preserve durable state. Worker stages are sequential and isolated.
- Keep every planned feature in scope; enable it only after its actual gates pass.
- Selected proposed paid plan: $79/month, $25 included provider usage,
  $5 task cap, no automatic overage. Trial: seven days, $1 total provider usage,
  one project. Read plan.json for the remaining exact limits. Billing is not live.
- Preserve owner runtime and its existing $2/day and $25/30-day backstops.
  Never stop owner work to admit a customer, or borrow owner credentials/budgets.

## What is actually implemented

Phases 1–2: product contract/screens/cost worksheet and private metadata foundation
with targeted proof. Phase 3: Django verified accounts, activation/recovery,
session rotation/revocation, scoped roles/operator MFA grants, audit and tenant
API ownership. Real owner test customer has now activated and successfully signed
in, as confirmed by the user. Do not onboard them again or reset their trial.
Their test identity is a **customer**, not an existing public admin account.
`/admin` UI has not been implemented; internal operator APIs remain private.

Phase 4 PARTIAL: durable lifecycle coordination, target-bound operation receipts,
generations/fences/leases, safe retry/reconciliation, global slot and prepared
fixed Fleet plans. Native driver remains `DisabledDriver`. FleetPlanner plans
commands; it does not execute them or prove runtime isolation. Stronger runtime,
worker broker, native credentials/outputs, quotas/network/egress and measured
capacity profile remain missing. No customer cell has been activated.

Phase 5 PARTIAL: append-only budget/usage receipts, atomic reservations/admission,
entitlements, late/uncertain liability handling, seed_trial and scoped usage
views. Real per-provider/task attribution, prices/upper bounds, virtual-key
backstops, per-call fences and reconciliation remain missing. Unknown service
allocation defaults to None and denies; don't fake a funded allocation or cost.

Phase 6 PARTIAL: server-rendered request page/API and persisted FIFO intake,
idempotency, waiting cancellation, active cancellation intent, claim/heartbeat/
reconciliation/terminal-receipt handling. Global request slot survives uncertainty
and restarts. Lifecycle cannot hand off to another account while it is held.
`DisabledRequestDriver` remains the production default; request_worker --once
refuses dispatch. Saved requests **wait**, not run. Native conversations,
send/history/stream/abort and full dashboard execution are not connected.

The adapter must admit the task using request_id as task identity and reserve all
route costs before wake/model effects. Recheck authorization and heartbeat;
respect cancellation/revocation. Release the global slot only after target/fence
receipt, confirmed native quiescence, stopped lifecycle slot and settled known
reservation. Expired leases/unknown effects require reconciliation, never resend.
See SERIAL_REQUESTS.md rather than improvising another scheduler.

## Live infrastructure and private access

- GitHub: `https://github.com/Parsarf/AgentAI`, branch `main`.
- Handoff baseline code commit: `2c2914afbd74f0a27a00b86380c4bf4cfc2d7f7d`.
  Later handoff/documentation commits may be present. Start with git status/log;
  preserve unrelated work and never force-push.
- Website: `https://getlumina.pro`; www and the original
  `agentai-vercel-ten.vercel.app` redirect to it.
- GoDaddy DNS: root→Vercel; backend.getlumina.pro→VPS `69.48.206.62`.
  Preserve existing email DNS records; no nameserver migration was required.
- Vercel scope `parsarfs-projects`, project `agentai-vercel`, ID
  `prj_ba5SLYoypaCXvS7ZJ1jaZla7ZsxO`, root directory
  `openclaw-project/platform/deploy/vercel`.
- Vercel Production BACKEND_ORIGIN=https://backend.getlumina.pro.
  Dependency-free node build.mjs emits Build Output API v3 routing. Keep
  output-directory override disabled. When configured, omit static setup index;
  preserve Django account trailing slashes. Only account/auth/v1 are proxied.
  Without BACKEND_ORIGIN, deploy the setup page. Do not reintroduce the earlier
  vercel.mjs/static-rewrite approach that failed real routing.
- VPS customer identity: Linux user/group `agentai-platform`.
  Code: `/opt/agentai-platform/current` → root-owned release.
  Current deployed code release at handoff:
  `/opt/agentai-platform/releases/20261001T005331Z-activation`.
  Its venv links to the prior release's dependency environment; preserve that
  dependency chain until a properly pinned replacement/rollback is prepared.
- Private DB: `/var/lib/agentai-platform/platform.sqlite3` (0600; directory0700).
  Private settings: `/etc/agentai-platform/accounts.env` (root-owned0600).
  App origin: AGENTAI_PUBLIC_ORIGIN=https://getlumina.pro.
  Private /readyz reports foundation/identity/mail readiness true, but
  customer_ready and execution_enabled false. These do not mean the owner
  login is broken; native product execution gates remain intentionally closed.
  Do not simply flip flags to claim execution is implemented.
- `agentai-platform-app.service`: Gunicorn on127.0.0.1:18800;128 MiB cap,
  no swap,25% CPU. Owner Gateway remains on private loopback18789.
- Caddy terminates trusted automatic HTTPS on80/443 for backend.getlumina.pro.
  Configuration: platform/deploy/caddy/Caddyfile.getlumina; actual
  `/etc/caddy/Caddyfile`, preserved backup Caddyfile.before-agentai.
  Caddy128 MiB/no swap/25% CPU. Host/scheme/peer IP are overwritten; internal
  routes return404. Vercel peer IPs may share rate limits; don't trust arbitrary
  forwarded client IP headers to bypass that limitation.
- Gmail SMTP is configured with the owner's app password over STARTTLS587.
  `agentai-platform-mail.timer` runs bounded deliver_account_mail jobs every60s;
  service96 MiB/no swap/25% CPU. Codes are single-use and expire15 minutes.
  Running/uncertain mail jobs are never automatically resent. Don't resend the
  owner's invitation now that they are logged in.
- Local `openclaw-project/.env` holds private SSH references used by
  `.venv/bin/python openclaw-project/bin/ssh-server '<fixed command>'`.
  Strict host-key checking is already configured. Local
  `openclaw-project/platform/.env.mail.local` is0600 and Git-ignored.
  NEVER print, commit, expose through tool output, or copy credentials/codes,
  customer DB contents or private backups into public evidence. For credentials,
  inspect presence privately; use approved server-side custody/SSH stdin.
- GitHub and Vercel CLI logins were established on this Mac. Verify presence
  without revealing tokens; another machine may need its own login. Do not pull
  private environment values into tracked files.

## Recent defects already fixed — retain the fixes

1. Vercel static root and account trailing-slash routing: explicit Build Output
   API routes and no setup index in connected mode; native Django forms now load.
2. CSRF: no-referrer broke HTTPS Referer fallback for browsers without Origin.
   Policy is now same-origin. Keep CSRF cookie/token/origin checks enabled;
   never solve this using csrf_exempt, wildcard origins or insecure cookies.
   HTML failures have a retry page, API csrf_denied remains unchanged, logs expose
   fixed reason categories only (no raw headers/tokens/passwords).
3. Activation: pasted whitespace is normalized before purpose/epoch/expiry/hash
   checks; disable code autocapitalization/spellcheck. Invalid/expired/used codes
   and password validation now show readable HTML; API denial contracts remain.
   User confirms activation and login succeeded after these fixes.

## Evidence and checks

Review evidence/product/{phase-01,phase-02,phase-03,phase-04,phase-05,phase-06,
publication,custom-domain,account-mail,csrf-fix,activation-code} under
openclaw-project. Current targeted proof includes32 queue/lifecycle/budget checks,
37 aggregate account/API checks at publication,27 focused account checks for
CSRF and28 focused checks after code-paste fixes. These aren't native OS isolation
or real agent/provider task acceptance. Latest baseline GitHub workflow succeeded:
https://github.com/Parsarf/AgentAI/actions/runs/36798546862 .

Source check workflow: `.github/workflows/platform.yml`. Reuse its pinned Python
requirements.lock and disposable private settings for tests. Run meaningful
checks for your changes, not broad paid evaluation. Installed native runtime was
previously OpenClaw2026.9.6/Fleet experimental; recheck installed help/schema,
versions and safe source before choosing real operations. A whole private runtime
source export was previously rejected by automatic approval review; don't bypass
that rejection. Use bounded supported probes and primary documentation.

## Next concrete work and close-out

1. Establish current state read-only: git changes, service/readiness, native
   versions/runtime capabilities and fresh CPU/RAM/disk/headroom. Previous
   default2 GiB cell measurements admitted zero agents; that is historical proof,
   not a measured small-cell profile. Low memory/swap pressure remains a concern.
2. Write a bounded Phase4 plan tied to requirement IDs and the existing prompt.
   Implement a narrow host-owned supervisor/native lifecycle adapter, separate
   worker authority and registry, stronger untrusted-code runtime, tenant roots/
   secrets/networks/quotas, safe wake/drain/stop and measured atomic admission.
   Neither app nor Gateway gets the Docker socket. No client-controlled shell,
   path, URL, deployment ID or resource assertion may become provisioning authority.
3. Use disposable non-billable fixtures to verify true tenant boundaries and
   failure/retry/reconciliation. Keep live dispatch closed until isolation,
   usable capacity and budget/route gates pass. A metadata mock isn't proof.
4. Close Phase4 implementation gates before Phase5 real provider enforcement,
   then Phase6 actual send/history/events/results/cancel integration. Preserve
   the FIFO queue and global handoff semantics. Do not enable unrelated future
   features or call Phase6 complete because its intake UI works.
5. Update the relevant product phase record, ledger, architecture/runbook and
   BUILD_LOG; append sanitized UTC evidence with source hashes, actual checks,
   costs/unknowns, blockers and rollback. Preserve historical results. Report
   exactly what is built versus verified versus still disabled.

Existing user authorizations cover work on this VPS, the requested account/email
setup, and publication to this GitHub/Vercel project. Do not repeatedly request
those permissions. Ask only for genuinely missing choices/access or a new scope.
Do not buy infrastructure, change selected pricing, enable automatic overages,
start billing/public signup, resume deferred full/paid evaluation, or run another
customer's tools/credentials without the corresponding authorization. Preserve
owner services, customer identity/session state, trial lifetime spend, pending
requests, uncertain reservations and rollback paths throughout.
