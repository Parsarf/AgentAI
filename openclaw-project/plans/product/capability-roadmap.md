# Capability roadmap: 148 features in build order

**Status (2026-11-20):** Phase 0 and Phase 1 **DONE AND LIVE** (#1-11, the engines of #78 and #79). Phase 2 and Phase 3 **DONE AND LIVE** (#12-29, #83; owner switches off; all eight live gates passed, the handoff gate only in its few-seconds form). Phase 4 **DONE AND LIVE** (#30-48; release `b0a5dd7`; installed on the host; `customer_uploads` and `customer_knowledge` on for every account; all four exit gates passed live with `deploy/phase45_live.py`; the policy describing it published 2026-11-19). Phase 5 **DONE AND LIVE** (#49-58 and D1-D5, switch on; the policy for the copy published 2026-11-19; every exit gate passed, gate 1 live with two real Google accounts on 2026-11-20). Phase 6 is **BUILT; GOOGLE LIVE** (#59-67, D6, D7, D9 on for every account with the policy published; #68 and #69 skipped by the owner; D8 Microsoft configured and open for reading since 2026-11-21, its changes waiting for the owner's live test (exit gate 8); `roadmap/phase-06.md`). Phase 7 is **READY, NOT STARTED** (`roadmap/phase-07.md`). Phases 8 to 12 are **NOT STARTED**. Evidence and open items: `roadmap/phase-00.md` to `roadmap/phase-07.md`.
It orders the 148 features of the supplied inventory, says what each one is, and gives the approach to build it on top of what Lumina already has.

- **P / M** are the inventory's own labels (partly built / missing). They were not re-audited feature by feature. Where this plan relies on existing code, the module is named and was read on 2026-11-14 at commit `51a89e9`.
- **#** is the feature's number in the supplied inventory, kept so the two lists can be compared.
- **Size** is relative: S (a few days of focused work), M (one to two weeks), L (several weeks or a new service). These are judgments, not measurements.
- Vendor and tool names in this plan come from a short web survey (sources at the end). Most of those sources are vendor blogs. Treat each named tool as the first candidate to test, not as a decision.

---

## 1. Where Lumina starts

What exists today and is reused below:

| Area | What exists | State |
|---|---|---|
| Execution | One isolated assistant per customer (OpenClaw runtime in a gVisor cell), request queue, chat driver, run supervision, stop, park-on-a-person, crash recovery | Live. **One request at a time for the whole host, one running cell** (`request_queue.py`, `lifecycle/`) |
| Long work | Session goals with a 20-turn chain (`goals.py`), plans with phases (`genui/`), durable objectives with checkpoints and sticky cancel (`durable.py`) | Goals and plans live; `durable.py` is built and tested but resume is explicit-only by design |
| Automation | Schedules (`schedules.py`), quiet watchers (`watchers.py`) | Built; creation refused until enforcement is proven; owner switch `customer_schedules` off |
| Tools | Lumina tool relay over MCP (browser, files, display, memory), remote MCP connections with OAuth and registry search (`mcp_connections/`), per-tool approval | Live |
| Connectors | Google/GitHub connector service with token custody, read-only gating, drafts and operation receipts (`connectors.py`) | Built; custody backend disabled by default; owner switch `connectors_linking` off; no write kinds exist |
| Knowledge | Long-term memory with a ledger and a Hindsight index (`longterm_memory.py`), project memory with correction (`memory.py`), reusable skills with approved revisions (`skills.py`) | Long-term memory live per account; the other two built, not all exposed |
| Files | Uploads with validation and quarantine (`files.py`, off by default), versioned artifacts, conversion to PDF/Word/Excel/PowerPoint (`render/`), generated apps in a player (`apps.py`) | Artifacts and conversion live; uploads off |
| Browser | Lumina browser tool with payment and sign-in stops, saved logins vault, live view, side panel in the customer's Chrome | Live; `credentialed_browsing` off |
| Money and access | Budget ledger, customer-set spending limits (PR #39), Stripe test-mode billing, safety switches per account, operator grants with MFA | Live except billing checkout |
| Operations | Backup and restore, monitor, feature switches, privacy record wired to tests, timing marks | Live |

Three constraints shape the whole order:

1. **Concurrency is one.** Every feature that runs in the background (schedules, webhooks, monitoring, delegation) competes with interactive chat for a single slot. Parallel execution (#8) is therefore a foundation, not a later feature.
2. **An account is one person.** There is one role (`customer`) per account and no organization. Roles, resource permissions and organization policy (#12-15) need an organization model first.
3. **Nothing writes to a customer's systems yet.** The connector catalog has no writable kind. Every write feature below goes through one shared action pipeline that does not exist yet.

---

## 2. The approach: seven decisions that apply to every phase

**D1. One action pipeline for every external write.**
Every change to a system outside Lumina (send, create, edit, delete, publish, deploy) goes through the same six steps: build the exact proposed change, show it as a preview, bind the customer's approval to that exact change, execute with an idempotency key, record a receipt, read the result back to verify it. No connector implements its own approval or its own retry. Three rules come from current practice with durable agents:
- The idempotency key is derived from the workflow and step (`<request id>-<step>`), never from the model's arguments, so a reworded retry cannot act twice. The chat driver already does this for runs.
- The way to reverse a change is written down **before** the change is made, so a crash mid-step still leaves a recovery path.
- Reversal steps are defined in code per action kind. The model never improvises a rollback.

**D2. MCP first for integrations, with Lumina owning custody and permissions.**
Use a provider's official remote MCP server where one exists, behind the existing `mcp_connections` service. Build a first-party connector only where there is no official server, where it is not generally available, or where Lumina needs something the server does not give (complete pagination, sync state, change tokens). Google publishes remote MCP servers for Gmail, Calendar, Drive and others, but the survey found them still in developer preview in October 2026; plan on first-party Google connectors through `connectors.py` for launch and switch per product when the official servers are generally available. Microsoft 365 goes through Microsoft Graph. Either way the token lives in Lumina's custody backend and every call passes Lumina's permission check.

**D3. Workflow state lives in the database, not in the model's context.**
A long task is a durable objective with ordered checkpoints (`durable.py`). A restart, a crash or a cell going to sleep loses nothing. Resume stays an explicit decision (the customer's, or a policy they set), and is refused while any effect is uncertain.

**D4. One knowledge pipeline.**
Every source (upload, attachment, connected drive, web page kept by the customer) goes through the same steps: parse to structured text with positions, split into passages, index per account with a permission scope, keep a pointer back to the source and page. Search, comparison, verification and meeting preparation all read this one index. Memory (Hindsight) stays separate: it holds what the customer told the assistant, not documents.

**D5. An evaluation suite gates every phase.**
Each customer workflow gets a recorded acceptance case. The suite runs before any change to shared infrastructure ships. A phase is done when its cases pass on the live stack, not when the code merges.

**D6. Read before write, one provider before many.**
Each integration ships read-only first, on one provider (Google), behind an owner switch and a per-account rollout list. Writes come one phase later through D1.

**D7. Privacy record first.**
A new recipient of customer data, a new kind of stored data or a new retention time updates `privacy/facts.json` and the public policy before the switch is turned on (`privacy/README.md`). This applies to almost every phase from 3 onward.

**What "ready for launch" means in this plan.** Recommendation: launch after Phase 5. That gives a product that runs reliably for several customers at once, respects permissions and deletion, reads a customer's files, email and calendar, and drafts but does not send. Phases 6 and 7 (writes, automation) are the first releases after launch. Phases 8 to 12 follow demand. Launching with external writes on day one is possible but puts the riskiest features in front of the least-tested system.

---

## 3. Changes to the supplied order

The supplied dependency order is kept. Five changes, with reasons:

| Change | Reason |
|---|---|
| New **Phase 0** before everything | Fixes already written are not deployed, and one request at a time cannot support a launch. Nothing else is measurable until this is done. |
| **Parallel task execution (#8)** moves to the front of Phase 1 | It is the capacity limit for every background feature. Building schedules, webhooks or delegation on a single slot would have to be redone. |
| **Capability evaluation (#3) and regression detection (#4)** move ahead of the other Phase 1 items | They are how the rest of Phase 1 is proven. |
| **Scheduled execution (#78), change monitoring (#79) and notifications (#80, #81)** are split: the engine is finished in Phase 1, the customer features stay in Phase 7 | The engine is shared infrastructure (it depends on #8 and #6); the customer features depend on tasks and commitments. |
| **Human handoff (#83)** moves to Phase 3 | Action previews and approvals are a handoff. Building them twice would diverge. |

---

## Phase 0. Ship what is written and remove the launch blockers

**Goal:** the server runs current code, and the measurements this plan depends on exist.

| Step | What | Done when |
|---|---|---|
| 0.1 | Merge PR #39 and deploy app, supervisor and web app (see `platform/deploy/PENDING_DEPLOY.md`) | `/var/lib/agentai-deploy/last` equals `origin/main`; migration 0037 applied |
| 0.2 | Fix the automatic deploy, which refuses every merge ("379 files released by hand") | A merge to main deploys without a manual run |
| 0.3 | Bring the prompt-cache fix to the server and remove the `index: -1` cache point from the server's LiteLLM config | Cache reads grow with the conversation in the spend logs; cost per call falls |
| 0.4 | Turn on timing marks (`AGENTAI_TIMING=1`) and keep one week of data | Per-stage latency for every request is in the journal |
| 0.5 | Finish the owner-only launch items in `LAUNCH.md`: off-server backup copy, SSH keys only, Stripe account, legal pages, support address, dedicated search key | Each is ticked in `LAUNCH.md` |
| 0.6 | Turn on the push gateway so tabs stop polling | Open tabs hold one stream instead of about three requests a second |

**Exit gate:** production equals main, and a week of timing data exists.

---

## Phase 1. Stabilize execution and recovery

**Goal:** several customers can work at once, long tasks survive restarts, and every later change can be checked against recorded workflows.

**Build order inside the phase:** 3, 4, then 8, then 1, 2, 5, then 6, 7, then 9, 10, 11, then the engines for 78 and 79.

| # | Feature | Status | What it is | Approach | Done when | Size |
|---|---|---|---|---|---|---|
| 3 | Capability evaluation | **Done** (live 2026-11-15, `roadmap/phase-01.md`) | Repeatable acceptance checks for the workflows customers already use | Extend `evals/` and the Phase 15 acceptance cases into one suite of recorded cases: chat answer, file delivery, plan run, browser task, goal chain, stop, recovery after a cell restart. Each case has a fixed input, a checkable outcome (from `outcome.py` facts, not prose) and a cost ceiling | The suite runs with one command against a disposable account on the live stack and reports pass, fail, cost and time per case | M |
| 4 | Regression detection | **Done** (live 2026-11-15, `roadmap/phase-01.md`) | Running those checks whenever shared infrastructure changes | Run the cheap cases in CI against the synthetic gateway; run the live cases before each deploy from the deploy workflow; keep results per commit | A deploy is refused when a case that passed on the previous release fails | S |
| 8 | Parallel task execution | **Done** (live 2026-11-15, `roadmap/phase-01.md`) | More than one request running at a time, isolated per customer | Replace the global `request_slot` with one slot per account and the single cell slot with a pool sized from live host capacity (`lifecycle/profiles.py`). Start with a larger host; keep the design able to place cells on a second host. Limits per customer: one interactive run plus a small number of background runs, each with its own time limit. Move the platform database from SQLite to PostgreSQL before a second worker host exists | Two accounts run tasks at the same moment with no shared state; a second request of one account queues behind its first; capacity refusals are visible to the customer as "waiting for a free assistant" | L |
| 1 | Rate-limit handling | **Done** (live 2026-11-15, `roadmap/phase-01.md`) | Shared request budgets, backoff and retry | One limiter per (account, provider) in the model relay and in the connector layer, fed by the provider's own reset headers. Retry with jittered backoff only on errors the provider marks temporary; a budget or permission refusal is never retried. The customer sees "waiting for the provider" instead of a failed task | No task fails on a temporary 429; the timeline shows the wait; refusals that are permanent fail once with a clear message | M |
| 2 | Large-task execution | **Done** (live 2026-11-15, `roadmap/phase-01.md`) | Long outputs fail at the model's output limit | Teach the assistant (skill plus rules) to write large files in parts with the file tool and to checkpoint after each part; the driver records each part as a checkpoint so a cut-off reply resumes from the last part instead of starting over. Add an evaluation case for a 50-page document and a multi-file app | The two cases pass three times in a row | M |
| 5 | Tool and workflow versioning | **Done** (live 2026-11-15, `roadmap/phase-01.md`) | Knowing which implementation each run used | Stamp every request with the release commit, the model, the rules and skills hash and the tool list version; store it with the request and show it in the operator view | Any past request can be traced to an exact release and prompt set | S |
| 6 | Durable objectives | **Done** (live 2026-11-15, `roadmap/phase-01.md`) | Checkpoint, restart and explicit resume | Wire `durable.py` into the chat driver: a goal or a plan creates an objective; each finished turn, phase and tool effect writes a checkpoint; a restart marks it "interrupted" and offers Resume. Resume policy is per objective: ask me (default) or continue automatically within the customer's limits | An objective survives a cell restart and a worker restart with no repeated effect, proven by an evaluation case that kills the cell mid-run | M |
| 7 | Long-running workflow management | **Done** (live 2026-11-15, `roadmap/phase-01.md`) | Bounded runs chained through checkpoints | Replace the fixed 20-turn chain with a budget the customer sees (time, turns, spend from their own limits) and a visible checkpoint list. Each turn is a normal admitted request, so stop, limits and recovery keep working | A multi-hour job runs as a chain of bounded runs, can be stopped at any checkpoint and reports where it stopped | M |
| 9 | Time and resource estimation | **Done** (live 2026-11-15, `roadmap/phase-01.md`) | Telling the customer roughly how long and how much before a task starts | Record duration, model calls and cost per finished request by task kind; estimate from the median and the 90th percentile of similar past requests; show a range, never a single number, and say when there is too little history | Estimates are shown for plan phases and scheduled runs and are within the stated range for most runs in the evaluation set | M |
| 10 | Dependency management for plans | **Done** (live 2026-11-15, `roadmap/phase-01.md`) | Prerequisites beyond a fixed sequence | Extend the plan schema (`genui/schema.py`) with `depends_on` between phases; the plan runner starts a phase when its prerequisites are done and runs independent phases in parallel once #8 exists | A plan with a diamond of dependencies runs in a valid order and shows why a phase is waiting | M |
| 11 | Plan adaptation | **Done** (live 2026-11-15, `roadmap/phase-01.md`) | Replanning when results or instructions change | A replan is a proposed plan revision shown as a difference against the current plan; finished phases are never redone; the customer approves it unless they chose automatic replanning within limits | A failed prerequisite or a new instruction produces a revised plan that keeps completed work | M |
| 78e | Scheduled execution (engine) | **Done** (live 2026-11-15, `roadmap/phase-01.md`) | The engine behind schedules | Prove enforcement for `schedules.py` (time limit, budget, unattended approval rules) with evaluation cases; define missed-run behaviour (run once on recovery, or skip, per schedule); schedules use background slots from #8 | The enforcement flag can be set truthfully and the cases pass | M |
| 79e | Change monitoring (engine) | **Done** (live 2026-11-15, `roadmap/phase-01.md`) | The engine behind watchers | Finish `watchers.py` state handling: a cheap deterministic check first, a model run only on a real change, one notification per change | An unchanged source costs no model call over a week of checks | S |

**Exit gate:** the evaluation suite passes with two accounts running at once; a killed cell loses no work; no evaluation case fails on a rate limit.

---

## Phase 2. Permissions and account lifecycle

**Goal:** it is clear who may do what, customers can see and end every access, and an account can leave completely. This comes before any new access to customer systems.

**Build order:** organization model, then 12, 13, 14, 15, then 16, 17, then 18, 19, 20, 21.

| # | Feature | Status | What it is | Approach | Done when | Size |
|---|---|---|---|---|---|---|
| 12 | Role-based access control | **Done** (live 2026-11-16, release `8327634`, switches off; `roadmap/phase-02.md`) | Who can connect, read, approve and execute | Add an organization above accounts with members and four roles: owner, admin, member, viewer. Every permission check goes through one function in `security.py` that takes (person, action, resource). A single-person account is an organization of one, so nothing changes for today's customers | Every route and tool call names an action that the role table allows or refuses; the table is one file with a test per row | L |
| 13 | Resource-level permissions | **Done** (live 2026-11-16, release `8327634`, switches off; `roadmap/phase-02.md`) | Limiting access to chosen files, calendars, projects and records | A grant is (connection, resource kind, resource id or "all", read or write). Connectors and the knowledge index filter by grants before returning anything. Default for a new connection is nothing selected | A connection limited to two calendars cannot read a third, proven by a test at the connector boundary | M |
| 14 | Permission visibility | **Done** (live 2026-11-16, release `8327634`, switches off; `roadmap/phase-02.md`) | Showing what each assistant and connection can reach | One Settings page listing every connection, its grants, the tools the assistant has, saved logins and when each was last used, with a remove button on each line | Everything the assistant can reach is on that page and nothing else is reachable | M |
| 15 | Organization policy enforcement | **Done** (live 2026-11-16, release `8327634`, switches off; `roadmap/phase-02.md`) | Organization-wide limits on tools and actions | Reuse the safety switch design (`safety.py`): an organization row overrides member settings for tool use, connectors allowed, write actions, spending limits. Enforced where switches are enforced today | An admin can forbid a tool or a write kind for all members and a member cannot turn it back on | M |
| 16 | Credential refresh | **Done** (live 2026-11-16, release `8327634`, switches off; `roadmap/phase-02.md`) | Keeping connections alive without asking again | Refresh tokens ahead of expiry in a background job with a lock per connection; store only in custody; a failed refresh marks the connection "needs you" and notifies once | A connection stays usable for 30 days with no customer action in a soak test | S |
| 17 | Credential revocation lifecycle | **Done** (live 2026-11-16, release `8327634`, switches off; `roadmap/phase-02.md`) | What happens when access ends | Revocation (by the customer, an admin or the provider) stops new calls at once, cancels or parks running work that needs the connection with a clear reason, and purges tokens (`ConnectorService.disconnect`, `purge_revoked`) | Revoking mid-task stops the task at its next call and nothing uses the token afterwards | M |
| 18 | Data retention management | **Done** (live 2026-11-16, release `8327634`, switches off; `roadmap/phase-02.md`) | One set of rules for stored content, logs and artifacts | A retention table: one row per data kind with how long it is kept and what deletes it; one sweeper that enforces it; the privacy record reads the same table | Every table and file store has a row, and the privacy test fails if one is missing | M |
| 19 | Customer data export | **Done** (live 2026-11-16, release `8327634`, switches off; `roadmap/phase-02.md`) | Giving a customer their data and settings | A background export job that writes one archive: conversations, files and artifacts, memory, plans, schedules, connections (names and scopes, never tokens), settings. Download with a signed, expiring link | The archive of a test account contains every kind in the retention table that belongs to the customer | M |
| 20 | Customer data deletion | **Done** (live 2026-11-16, release `8327634`, switches off; `roadmap/phase-02.md`) | Deleting across storage, indexes and derived records | One deletion routine driven by the retention table: database rows, file storage, the memory index, the document index, the cell's workspace and volume, the model key. Backups age out on their stated schedule | After deletion a scan of every store finds nothing for the account except the audit tombstone | M |
| 21 | Complete account offboarding | **Done** (live 2026-11-16, release `8327634`, switches off; `roadmap/phase-02.md`) | Leaving in one guided flow | Sequence: stop schedules and running work, offer the export, revoke every connection, delete, confirm by email. Each step is a checkpoint so a failure resumes instead of restarting | One button offboards a test account end to end and the report lists each step | S |

**Exit gate:** the role table is enforced on every route; offboarding a test account leaves nothing behind; the privacy record matches.

---

## Phase 3. Shared integration and action infrastructure

**Goal:** one way to read from, and one way to write to, any outside system. Email, calendars, projects and business systems are built on this and nothing else.

| # | Feature | Status | What it is | Approach | Done when | Size |
|---|---|---|---|---|---|---|
| 22 | API integration | **Done** (live 2026-11-16, release `8327634`, switches off; `roadmap/phase-03.md`) | One connector contract | A connector declares its capabilities (read kinds, write kinds, search, change tokens), its auth and its error map. Official remote MCP servers are wrapped to the same contract (D2). Errors are one of: retry later, needs the customer, refused, not found | A new connector is a declaration plus adapters, with no new approval, retry or permission code | L |
| 23 | General pagination handling | **Done** (live 2026-11-16, release `8327634`, switches off; `roadmap/phase-03.md`) | Getting complete result sets within limits | One paging helper with a hard cap on pages, items and time; a result always says whether it is complete and how to continue; the assistant is told when it saw only part | A 5,000-message search returns "first 500 of about 5,000" rather than a silent partial answer | S |
| 24 | Data freshness tracking | **Done** (live 2026-11-16, release `8327634`, switches off; `roadmap/phase-03.md`) | Knowing how current the data is | Per connection and resource: last successful sync, coverage (date range, count) and the last error. Shown beside every answer that used the data | An answer from data older than its freshness limit says so | S |
| 25 | Concurrent edit detection | **Done** (live 2026-11-16, release `8327634`, switches off; `roadmap/phase-03.md`) | Noticing a record changed after it was read | Keep the provider's version token (ETag, sequence, updated time) with every record read; send it on write; a mismatch stops the action and shows both versions | An edit to an event changed elsewhere in the meantime is refused and explained | S |
| 26 | Action previews | **Done** (live 2026-11-16, release `8327634`, switches off; `roadmap/phase-03.md`) | Showing the real proposed change and where it goes | The preview is rendered from the exact payload that would be sent (D1), using the display tool: recipient or destination, before and after, what cannot be undone. Approval stores a hash of that payload | The executed payload always equals the approved one; a changed payload needs a new approval | M |
| 83 | Human handoff | **Done** (live 2026-11-16, release `8327634`, switches off; `roadmap/phase-03.md`) | Handing a decision to a person with context | Generalize the browser's park-on-a-person: any workflow can park with a question, the evidence, the options and a resume path; the request gives up its slot while it waits | A parked approval can be answered hours later from web, panel or phone and the work continues from its checkpoint | M |
| 27 | Undo mechanisms | **Done** (live 2026-11-16, release `8327634`, switches off; `roadmap/phase-03.md`) | Reversing supported changes | Each write kind registers its inverse (delete the created event, restore the previous text, move the message back). Undo is offered for a stated time and is itself an action with a receipt | Every write kind either has a tested undo or is labelled "cannot be undone" in its preview | M |
| 28 | Compensating actions | **Done** (live 2026-11-16, release `8327634`, switches off; `roadmap/phase-03.md`) | Recovering when undo is impossible | For actions with no inverse (a sent email, a published post), register a follow-up (send a correction, unpublish, notify attendees). The compensation is recorded before the action runs and is safe to repeat | A workflow that fails after an irreversible step offers the registered follow-up and never an invented one | M |
| 29 | Cross-application workflows | **Done** (live 2026-11-16, release `8327634`, switches off; `roadmap/phase-03.md`) | Coordinating several connectors | A workflow is a durable objective whose steps are actions from different connectors, with irreversible steps ordered last and a compensation per step (a saga) | A three-system workflow that fails at step three leaves steps one and two reversed or reported | M |

**Exit gate:** a synthetic connector passes a full write cycle: preview, approval, execute once under retry, verify, undo, compensation after a forced failure.

---

## Phase 4. Customer knowledge

**Goal:** the assistant can find, read and cite the customer's own material, and says what it does not know.

**Build order:** 30, then 31 to 34, then 36 and 37, then 35, 38 to 41, then 42 to 48.

| # | Feature | Status | What it is | Approach | Done when | Size |
|---|---|---|---|---|---|---|
| 30 | File organization | **Live** (2026-11-16, PR #50; `customer_uploads` on for every account since 2026-11-19; `roadmap/phase-04.md`) | Stable identifiers, folders, metadata, ownership | Turn uploads on (needs the content scan in `files.py`); give every file an id, owner, project, folder, source and content hash; artifacts and uploads share one catalogue | Any file can be named, moved and found by id; a duplicate upload is recognized | M |
| 31 | Optical character recognition | **Live** (2026-11-19, on for every account; `roadmap/phase-04.md`) | Text from scans and images | Add a parsing service beside the render service. First candidate: Docling (open source, runs on CPU). Test a vision-model parser on the hardest pages before choosing. A scanned page keeps a confidence value | Text from a scanned contract is searchable and each passage points to its page | M |
| 32 | Document understanding | **Live** (2026-11-19, on for every account; `roadmap/phase-04.md`) | Keeping structure and source links | The parser output is structured: headings, paragraphs, lists, tables, figures, each with page and position. That structure is what gets indexed (D4) | An answer about a document cites page and section and the citation opens there | M |
| 33 | Table extraction | **Live** (2026-11-19, on for every account; `roadmap/phase-04.md`) | Usable structured data from tables | Tables come out as rows and columns with header detection and a link to the page; numeric cells are validated (totals, column types) and flagged when they do not add up | A table from a PDF invoice exports to a spreadsheet with correct totals in the evaluation set | M |
| 34 | Chart extraction | **Live** (2026-11-19, on for every account; `roadmap/phase-04.md`) | Telling visible labels from estimated values | Read charts with the vision model; mark every value as "printed on the chart" or "estimated from the picture"; never present an estimate as data | A chart answer shows which numbers were read and which were estimated | S |
| 36 | Document and attachment search | **Live** (2026-11-19, on for every account; `roadmap/phase-04.md`) | Indexing the customer's files | Index parsed passages per account with keyword and meaning-based search, filtered by resource grants (#13) before ranking. Start with PostgreSQL full-text plus vectors in the same database to avoid a new service | Search over 1,000 documents returns in under a second and never returns a passage the person may not read | L |
| 37 | Semantic search beyond memory | **Live** (2026-11-19, on for every account; `roadmap/phase-04.md`) | Finding passages by meaning | Same index as #36; combine keyword and meaning scores, then re-rank the top results | The retrieval evaluation set meets a recall target set from its first measured run | M |
| 35 | Document comparison | **Live** (2026-11-19, on for every account; `roadmap/phase-04.md`) | Changes between versions with references | Align two parsed documents by section, then by sentence; report added, removed and changed text with both locations; a table of changes for long documents | Two versions of a contract produce a change list where every item opens both sources | M |
| 38 | Internal knowledge search | **Live** (2026-11-19, on for every account; `roadmap/phase-04.md`) | Searching connected systems with permissions | Federated search through connectors that support search, merged with the index; the person's own permissions at the source always apply | A search spanning Drive and uploads returns one ranked list with source and freshness per item | M |
| 39 | Project knowledge | **Live** (2026-11-19, on for every account; `roadmap/phase-04.md`) | Sources and context per project | A project has pinned sources and instructions; retrieval in that project searches them first; `memory.py` holds project facts | The same question in two projects answers from each project's own sources | S |
| 40 | Organization-wide knowledge | **Live** (2026-11-19, on for every account; `roadmap/phase-04.md`) | Shared sources with scoped access | An organization space in the index with grants by role or group (#12, #13) | A member finds shared sources and cannot find another team's restricted ones | M |
| 41 | Knowledge base management | **Live** (2026-11-19, on for every account; `roadmap/phase-04.md`) | Ingestion, updates, provenance, removal | A sources page: what is indexed, from where, when it was last updated, who added it; re-index on change; removal deletes passages and derived records | Removing a source removes every passage from search within a minute | M |
| 42 | Memory correction | **Live** (2026-11-19, on for every account; `roadmap/phase-04.md`) | Editing remembered facts with history | Expose `memory.py` correct and confirm in the Memory settings card; a correction supersedes the old entry and keeps its origin and date | A corrected fact is used from the next message and the old one is visible in history | S |
| 43 | Decision and commitment tracking | **Live** (2026-11-19, on for every account; `roadmap/phase-04.md`) | Owners, dates, decisions, open commitments | A commitments table (what, who, due, source, state) filled by the assistant with a tool call and always confirmed by the customer when it comes from outside content | Commitments from a conversation appear in one list with their source and can be closed | M |
| 44 | Explicit assumption tracking | **Live** (2026-11-19, on for every account; `roadmap/phase-04.md`) | Separating assumptions from retrieved facts | Answers carry a short list of assumptions as structured data (display tool), each marked assumed, retrieved or told by the customer | An answer built on a guess shows the guess as an assumption the customer can correct | S |
| 45 | Explicit contradiction detection | **Live** (2026-11-19, on for every account; `roadmap/phase-04.md`) | Conflicts between sources, memory and instructions | When retrieved passages or memories disagree on the same fact, show both with their sources and dates instead of choosing silently | A test set of planted conflicts is reported, not resolved quietly | M |
| 46 | Source evaluation | **Live** (2026-11-19, on for every account; `roadmap/phase-04.md`) | Authority, relevance, freshness | Each source gets a small record: kind (customer's own, official, third party), date, and why it was used; shown with citations | Citations show kind and date; an old source is flagged | S |
| 47 | Fact verification | **Live** (2026-11-19, on for every account; `roadmap/phase-04.md`) | Checking consequential claims | For claims with numbers, dates, names or legal and financial weight, a second pass checks each against the cited passage and marks it supported, partly supported or not found | Unsupported claims are marked in the evaluation set rather than stated plainly | M |
| 48 | Uncertainty assessment | **Live** (2026-11-19, on for every account; `roadmap/phase-04.md`) | Reporting gaps and confidence | Extend `outcome.py` verdicts with what was checked, what could not be checked and what is missing | A task's result says what it could not verify, in plain words | S |

**Exit gate:** the knowledge evaluation set (retrieval, citation, comparison, planted contradictions, unsupported claims) passes; deletion of a source is proven complete.

---

## Phase 5. Read-only calendars and email (launch line)

**Goal:** useful connected-data work with no external writes. One provider first (Google), Microsoft second.

| # | Feature | Status | What it is | Approach | Done when | Size |
|---|---|---|---|---|---|---|
| 49 | Calendar account connection | **Live** (2026-11-16, `mail_calendar_dashboard` on; `roadmap/phase-05.md`) | Finishing the connection flows | Turn on a real custody backend for `connectors.py`; register the OAuth app (a separate client for the assistant, as Google advises); read-only scopes only | A customer connects and disconnects a calendar from Settings, and the permission page shows it | M |
| 50 | Multiple calendar support | **Live** (2026-11-16, `mail_calendar_dashboard` on; `roadmap/phase-05.md`) | Several accounts and chosen calendars | Several connections per person; calendar selection is a resource grant (#13) | Two Google accounts with a chosen subset of calendars work side by side | S |
| 51 | Recurring-event handling | **Live** (2026-11-16, `mail_calendar_dashboard` on; `roadmap/phase-05.md`) | Occurrences, exceptions, cancellations | Read expanded instances from the provider instead of expanding rules locally; keep the series id and the exception flag on each instance | A weekly meeting with one moved and one cancelled occurrence is read correctly | S |
| 52 | Calendar viewing | **Live** (2026-11-16, `mail_calendar_dashboard` on; `roadmap/phase-05.md`) | Any date range with sync status | Range queries through the paging helper; show freshness (#24); render with the display tool | "Show March" and "next two weeks" are right in the customer's timezone | S |
| 53 | Event search | **Live** (2026-11-16, `mail_calendar_dashboard` on; `roadmap/phase-05.md`) | Search across calendars and history | Provider search plus a local index of event titles, people and notes within the granted range | A search by attendee finds past and future events | S |
| 54 | Calendar question answering | **Live** (2026-11-17, PR #60: a citation selects the event in the page; `roadmap/phase-05.md`) | Answers from retrieved events with references | Answers cite the events they used and link to them | "When did I last meet X" answers with the event and date | S |
| 55 | Email reading | **Live** (2026-11-16, `mail_calendar_dashboard` on; `roadmap/phase-05.md`) | Access, retrieval, attachments | Read-only scope; attachments go through the knowledge pipeline (D4); mail content is always treated as data, never as instructions | A thread with a PDF attachment is read and the attachment is searchable | M |
| 56 | Email search | **Live** (2026-11-16, `mail_calendar_dashboard` on; `roadmap/phase-05.md`) | Complete, permission-scoped search | Provider search with complete paging (#23) and explicit result counts | "All invoices from X this year" states the count and whether it is complete | S |
| 57 | Email drafting | **Live** (2026-11-17, PR #60; `roadmap/phase-05.md`) | Editable drafts aware of the destination | Drafts are stored in Lumina (`propose_draft`), shown with recipient, thread and tone; nothing is created in the mailbox until Phase 6 | A reply draft opens in an editor with the thread beside it | S |
| 58 | Meeting preparation workflow | **Live** (2026-11-17, PR #60; `roadmap/phase-05.md`) | Events, people, emails and documents together | A workflow: the event, who attends, the recent threads with them, the documents linked or relevant, open commitments (#43). The output is a brief with a citation per item | A brief for tomorrow's meeting is right on the evaluation account and cites every source | M |
| D1 | Provider-neutral mail and calendar model | **Live** (2026-11-16, PR #50; `roadmap/phase-05.md`) | One canonical message, thread, calendar and event shape; a capability table per provider | Pure conversion at each adapter; a test-only second provider in every test; no provider name in any screen or tool condition (a test searches for it). Shapes and table in `platform/CONNECTORS.md` | Two different providers in one list with nothing provider-specific above the adapter | M |
| D2 | Connected accounts and sync | **Live** (2026-11-17, PR #60: the service no longer grows; `roadmap/phase-05.md`) | Several accounts per person, each with its grants, cursor and freshness | A background service with checkpoints and provider cursors; faults as the six Phase 3 kinds; removal deletes every copy. Owner's choice: everything in the chosen labels, events from the past to two years ahead | A 50,000-message mailbox fills and stays current without hurting interactive work | M |
| D3 | Unified inbox | **Live** (2026-11-16; `roadmap/phase-05.md`) | One inbox across accounts, read only | Keyset-paged list, safe HTML, remote pictures on request, local then live search with counts | First page under 300 ms (measured 349-419 ms) | M |
| D4 | Unified calendar | **Live** (2026-11-16; `roadmap/phase-05.md`) | Day, week, month and agenda across every chosen calendar | Customer's timezone; overlaps side by side; busy-only events as busy | "Next two weeks" right across two accounts | M |
| D5 | The assistant in the dashboard | **Live** (2026-11-17, PR #60; `roadmap/phase-05.md`) | The same assistant beside the Inbox and Calendar, aware of the selection | `surface='dashboard'` with ids only; one-click questions; citations as in-app links that select the thread or event | "What is this about" answers from the open thread and cites it | M |

**Exit gate (launch):** the read-only suite passes on Google; the privacy policy names the new recipients; a second provider is not required for launch.

---

## Phase 6. Controlled communication and scheduling (first release after launch)

**Goal:** the assistant acts in calendars and mail, one approved action at a time, through D1.

| # | Feature | Status | What it is | Approach | Done when | Size |
|---|---|---|---|---|---|---|
| 59 | Availability checking | **Live** (2026-11-20, PR #67; `roadmap/phase-06.md`) | Free time across permitted calendars | Use the provider's free/busy query across granted calendars; working hours and timezone from the customer's settings | Free slots match the calendar on the evaluation account | S |
| 60 | Scheduling conflict detection | **Live** (2026-11-20, PR #67; `roadmap/phase-06.md`) | Overlaps, recurrence, timezone edges | Check a proposed time against expanded instances and all-day events, across daylight-saving changes | Planted conflicts, including one across a clock change, are all found | S |
| 61 | Event creation | **Live** (2026-11-20, PR #67; `roadmap/phase-06.md`) | Create and verify | First write kind: preview, approve, create with an idempotency key, read back | A retried create never makes a second event | M |
| 62 | Event modification | **Live** (2026-11-20, PR #76; `roadmap/phase-06.md`) | Concurrent changes and series scope | Version token on write (#25); the preview asks "this event, this and following, or all" | An edit to one occurrence leaves the series intact | M |
| 63 | Event cancellation | **Live** (2026-11-20, PR #67 one event, PR #76 parts of a series; `roadmap/phase-06.md`) | Making affected events and people explicit | The preview lists every attendee who will be notified; undo within the window re-creates the event and says attendees were already told | Cancelling a series shows the count of occurrences and attendees first | S |
| 64 | Invitation responses | **Live** (2026-11-20, PR #68; `roadmap/phase-06.md`) | Accept, decline, tentative | A write kind with read-back verification | The response shows in the organizer's view on the test account | S |
| 65 | Meeting scheduling | **Live** (2026-11-20, PR #77; `roadmap/phase-06.md`) | Availability, people, invitations | A workflow over #59 to #61: propose times, the customer picks, create and invite; with outside attendees it offers times by a draft email | A meeting with two internal attendees is scheduled from one request and one approval | M |
| 66 | Authorized email sending | **Live** (2026-11-20, PRs #78, #79; `roadmap/phase-06.md`) | Approved sending with no duplicates | Send only an approved draft; idempotency by draft id; a receipt with the provider's message id; compensation is a correction email | A send retried after a timeout delivers once | M |
| 67 | Inbox organization | **Live** (2026-11-20, PRs #78, #79; `roadmap/phase-06.md`) | Labels, folders, message state | Reversible write kinds with batch previews ("apply to 43 messages") and batch undo | A labelling of 100 messages can be undone in one step | M |
| 68 | Messaging integration | **Skipped by the owner** (2026-11-20: Telegram stays record only, Slack not built; `roadmap/phase-06.md`) | Beyond Telegram chat | Decide whether Telegram messages may run tasks (today they are recorded only); add Slack through the connector contract | A message in a linked channel starts a task with the same limits as the web app | M |
| 69 | Authorized message sending to others | **Skipped by the owner** (2026-11-20, with Slack; `roadmap/phase-06.md`) | Recipient, destination and approval controls | A write kind with an allow-list of destinations per connection and a preview naming the audience size | A message can go only to an approved channel or person | M |
| D6 | Managing mail from the dashboard | **Live** (2026-11-20, PRs #78, #79; `roadmap/phase-06.md`) | Send, reply, reply all, forward and organize from the Inbox, each with undo | Every control is a write kind of #66 or #67 through the action pipeline; the customer's own press is the approval; Undo send waits 10 s | One message in Sent under a forced retry; 40 threads archived and undone; a cancelled send leaves nothing | M |
| D7 | Managing events from the dashboard | **Live** (2026-11-20, PRs #67, #68, #76; `roadmap/phase-06.md`) | Create, change, drag, cancel and answer from the Calendar | The write kinds of #61 to #64, used directly or prepared by the assistant; the series scope is always asked | Each once under a forced retry; a series edit changes only the chosen scope | M |
| D8 | Microsoft as the second provider | **Live for reading** (2026-11-21: PR #82, the owner's Entra app configured, policy PR #84); every write kind stays in `proving` until `deploy/phase6_microsoft_live.py` passes on the owner's test accounts (exit gate 8) | Outlook mail and calendar through Microsoft Graph | A new adapter and declaration on the provider-neutral model, no change to screens, tools or workflows | The Phase 5 read suite and the Phase 6 write cycle pass with one Google and one Microsoft account connected | L |
| D9 | Calendar feeds and standard-protocol accounts | **Live** (2026-11-20, PR #80; IMAP, SMTP and CalDAV later, owner; `roadmap/phase-06.md`) | A calendar feed by address, read only | ICS through the destination guard, the address in custody; what password-based accounts would need is in `platform/CONNECTORS.md` | A public feed shows in the Calendar with no controls | S |

**Exit gate:** each write kind passes the Phase 3 write cycle on the live provider; no evaluation case produces a duplicate.

---

## Phase 7. Tasks, automation and notifications

**Goal:** work continues between conversations.

| # | Feature | Status | What it is | Approach | Done when | Size |
|---|---|---|---|---|---|---|
| 70 | Project board integration | P | Projects, tasks and statuses in one shape | A common task model (title, owner, status, due, links) over official MCP servers (Asana is already in the directory; add Linear, Jira, Trello, GitHub Issues) | The same question works across two boards | M |
| 71 | Task creation and assignment | M | Creating work with an owner and a place | A write kind through D1 | A task is created once and verified | S |
| 72 | Deadline tracking | M | Due dates, timezones, changes | Store due dates with timezone and whether a time was given; record changes | A deadline moved at the source is noticed at the next sync | S |
| 73 | Milestone tracking | M | Tasks tied to deliverables | A milestone is a group of tasks with a date and a computed state | Milestone state follows its tasks | S |
| 74 | Blocker detection | M | From dependencies, failures and missing inputs | Derived from task dependencies, overdue prerequisites, failed runs and open questions | Planted blockers are reported with their cause | M |
| 75 | Project status reporting | M | Actual state with evidence | A report workflow that cites tasks, dates and changes since the last report | A weekly report matches the board on the evaluation project | S |
| 76 | Webhook processing | M | Authenticate, deduplicate, route incoming events | One ingress with a signing secret per endpoint, replay protection by event id, a size limit and a queue; events are data, never instructions | A replayed or unsigned event is refused; a valid one is delivered once | M |
| 77 | Event-triggered automation | M | Accepted events start controlled workflows | A trigger is (event filter, workflow, limits, approval rule), run in a background slot under the customer's own spending limits | A new-ticket event starts a triage workflow within a minute | M |
| 78 | Scheduled execution | P | The customer feature | Turn on `customer_schedules` after the Phase 1 proof; a schedules page with next run, last result and cost | A daily brief runs for a week, including one missed run handled as configured | S |
| 79 | Change monitoring | P | The customer feature | Watch a page, a file, a search or a board; say what changed, not only that something did | A watched page reports the changed part | S |
| 80 | Notification preferences | M | Channels, quiet hours, frequency | Per person: channels (web, email, Telegram, push), quiet hours with timezone, digest or immediate, per kind | Nothing is delivered in quiet hours except what the customer marked urgent | S |
| 81 | Reminders and notifications | M | Delivering workflow updates | One outbox with deduplication and delivery receipts, used by every feature | A reminder arrives once on the chosen channel | M |
| 82 | Follow-up tracking | M | Commitments, messages, deadlines, triggers together | Built on #43: a follow-up is a commitment with a check ("no reply in three days") and an action (remind me, or draft a nudge) | An unanswered email produces a draft follow-up on the due day | M |

**Exit gate:** a week-long soak with schedules, a watcher and a webhook trigger on two accounts, with no missed or duplicate run.

---

## Phase 8. Human and agent collaboration

| # | Feature | Status | What it is | Approach | Done when | Size |
|---|---|---|---|---|---|---|
| 84 | Human collaboration | P | Shared work with ownership | Shared projects in an organization: members see conversations, files and tasks by role; every item has an owner | Two members work in one project with correct visibility | M |
| 85 | Task delegation | M | Bounded work with inputs and completion criteria | A delegation is a child objective with stated inputs, a budget, a time limit and a checkable definition of done, run in a background slot | A delegated research task returns a result judged against its own criteria | M |
| 86 | Multi-agent coordination | P | Shared state, budgets, dependencies, conflicting results | The parent holds the plan and the budget; children write results to a shared record; conflicts are shown to the parent (and the customer), never merged silently. Use the runtime's own subagents inside one cell before adding cells | Three parallel children finish within the parent's budget and their disagreement is reported | L |
| 87 | Specialist review | P | Independent checks before consequential actions | An optional review step in D1 for chosen action kinds: a separate run with only the proposed action and its evidence returns pass or concerns | A planted error in a proposed email is caught by review in the evaluation set | M |

---

## Phase 9. Analysis and reusable content

| # | Feature | Status | What it is | Approach | Done when | Size |
|---|---|---|---|---|---|---|
| 88 | External database querying | P | Scoped database connectors | Read-only connections to PostgreSQL, MySQL, BigQuery and Snowflake with a dedicated read-only role, a row limit, a time limit and a table allow-list | A query cannot write and cannot read an unlisted table | M |
| 89 | Trend detection | P | Repeatable analysis with stated metrics | A skill plus a metric definition record (what is counted, over what period); results name the definition used | The same question next week uses the same definition | S |
| 90 | Anomaly detection | P | Baselines and validated alerts | Baseline per metric with seasonality; an alert states the baseline and the size of the change; feed alerts into #79 | Planted anomalies are found and normal weekly swings are not | M |
| 91 | Forecasting | P | Evaluation, assumptions, uncertainty | Simple, explainable models first, tested against held-back history; show a range and the assumptions (#44) | Forecasts report their error on past data | M |
| 92 | Diagram creation | P | Reliable rendering and export | Diagrams as text (Mermaid or similar) rendered by the render service to SVG and PNG, validated before delivery | A diagram that fails to render is repaired or reported, never delivered broken | S |
| 93 | Template management | M | Reusable document and workflow structures | Templates as versioned artifacts with named fields; workflow templates build on `skills.py` | A proposal template fills from customer data and keeps its layout | M |
| 94 | Brand asset management | M | Approved logos, styles, assets | A brand kit per organization: logos, colours, fonts, approved imagery, with versions | Generated documents use the current kit | S |
| 95 | Tone and brand adaptation | P | Applying organization guidance | A brand voice record (rules plus approved examples) loaded as a skill; a check pass against banned phrases | Content follows the voice rules in the evaluation set | S |
| 96 | Content publishing workflows | M | Destination-specific previews and publishing | Publishing is a write kind (D1) per destination, with the preview rendered as the destination would show it; compensation is unpublish | A post is published once and can be unpublished | M |
| 97 | Publishing generated apps to public URLs | M | Package, deploy, verify, manage access | Static hosting per app on a separate domain from the product, with a content scan, an owner, an access setting (private link, public) and takedown | An app is public at its own address and can be taken down in one step | M |

---

## Phase 10. Software development workflows

Runs inside the customer's cell; `claude_code_for_customers` is the existing switch.

| # | Feature | Status | What it is | Approach | Done when | Size |
|---|---|---|---|---|---|---|
| 98 | Codebase navigation | P | Repository-scale search and context | A code index per repository in the cell (symbols, references, text search), refreshed on change | Questions about a large repository cite files and lines | M |
| 99 | Development environment management | P | Reproducible, isolated environments | A declared environment per repository (runtime versions, services) built in the cell's sandbox; larger cells for coding accounts | A fresh cell reaches a passing test run from the declaration alone | M |
| 100 | Software dependency management | P | Inspect, install, update safely | Lockfile-respecting installs through an allow-listed registry proxy; updates as a proposed change with test results | An update is proposed with its diff and test outcome | S |
| 101 | Code generation and editing | P | Reliable incremental changes | Small, reviewable edits with a checkpoint per change (#2, #6) | Multi-file changes survive an interrupted run | S |
| 102 | Debugging | P | Reproduce and verify | A workflow: reproduce with a failing test, fix, show the test passing | Fixes come with the reproduction | S |
| 103 | Test creation and execution | P | Run relevant checks and keep results | Test runs stored as artifacts with the commit they ran on | Results are attached to every change | S |
| 104 | Code review | P | Actionable defects against intent | Review as a specialist review (#87) with the stated intent as input | Planted defects are found in the evaluation set | S |
| 105 | Application building and packaging | P | Complete, inspected build artifacts | Build in the cell; artifacts stored with a checksum and a content list | A build artifact is downloadable and verified | S |
| 106 | Version control integration | P | Branches, commits, pushes | Write kinds through D1 with a GitHub App scoped to chosen repositories; never push to a protected branch | A branch is pushed once under retry | M |
| 107 | Pull request management | M | Create, update, follow review | Create and update as write kinds; review comments arrive by webhook (#76) and start a follow-up | A pull request is opened and updated after a review comment | M |
| 108 | Log and metric analysis | P | Evidence tied to releases | Read-only connectors to the customer's log and metric tools | A question about an error rate cites the query and the release | M |
| 109 | Incident investigation | P | Reconstruct failures, list options | A workflow over #108 producing a timeline with evidence and options, taking no action | A planted incident is reconstructed in the right order | M |
| 110 | Authorized infrastructure management | M | Scoped environments and action controls | Write kinds limited to named environments with plan-then-apply previews; production always needs approval | A change outside the allowed environment is refused | L |
| 111 | Authorized deployment | M | Approved release procedures | Trigger the customer's own pipeline as a write kind; do not reimplement deployment | A deploy is started once and its run is tracked | M |
| 112 | Release verification | M | Checking deployed behaviour | Post-deploy checks defined by the customer (health, key pages, metrics) run after #111 | A bad release is detected by its checks | S |
| 113 | Rollback execution | M | Restore and verify | The registered compensation for #111: redeploy the previous version, then run #112 | A failed verification offers rollback and proves recovery | M |

---

## Phase 11. Audio, video and application control

| # | Feature | Status | What it is | Approach | Done when | Size |
|---|---|---|---|---|---|---|
| 114 | Audio understanding | M | Ingest and interpret audio | Audio is a file kind in the knowledge pipeline: transcribe, then index | An uploaded recording is searchable by what was said | M |
| 115 | Meeting transcription | M | Speaker-aware, timestamped transcripts | A transcription service. First candidate self-hosted: WhisperX (needs a GPU). A managed service is the alternative if a GPU host is not wanted; that adds a recipient of customer audio (D7) | A one-hour meeting yields a transcript with speakers and times | L |
| 116 | Meeting summarization | M | Summaries with references | Summaries cite transcript times | Every summary point opens its moment | S |
| 117 | Meeting action items | M | Commitments tied to tasks and follow-ups | Extract into #43 and offer tasks (#71) and follow-ups (#82) | Action items appear as confirmed commitments | S |
| 118 | Video understanding | M | Visual and audio content over time | Sample frames plus the transcript; index both with times | A question about a screen recording cites the time | M |
| 119 | General image generation | M | Usable assets | A provider behind one tool with the brand kit (#94) as input; new recipient (D7) | Generated images are stored as artifacts with their prompt | S |
| 120 | General image editing | M | Modify supplied assets | Same tool, edit mode, keeping the original as a version | An edit keeps the unchanged parts | S |
| 121 | Audio generation | M | Speech and other audio | A provider behind one tool; new recipient | A script becomes an audio file | S |
| 122 | Audio editing | M | Revise and export | Command-line audio tools in the cell for cut, join, level | An edited file exports in the asked format | S |
| 123 | Video generation | M | Video assets | A provider behind one tool, costed up front (#9) | A clip is delivered with its cost stated before the run | M |
| 124 | Video editing | M | Assemble, revise, export | Command-line video tools in the cell with a timeline description | An assembled video renders from the description | M |
| 125 | Native application operation | M | Desktop control with state checks and handoff | Extend the browser model (stops, live view, takeover) to a remote desktop in the cell; verify state after each step | A task in a desktop app completes with the same stops as the browser | L |

---

## Phase 12. Dedicated business workflows

These are **packages of skills, templates and connectors** on the phases above. None should add infrastructure. Each package is: the connector for its system of record, a small set of workflow templates, its evaluation cases and its Settings entry. Order follows the customers you choose; the order below groups those that share parts.

| # | Feature | Status | What it is | Built from |
|---|---|---|---|---|
| 126 | CRM management | M | Customer, contact and opportunity records | Connector contract (#22) to HubSpot or Salesforce, write kinds through D1 |
| 127 | Lead research and qualification | M | Research plus knowledge plus CRM | Web research, knowledge (#36), #126 |
| 128 | Sales opportunity management | M | CRM plus tasks plus follow-ups | #126, #71, #82 |
| 129 | Proposal workflows | M | Customer context, templates, approvals | #93, #94, #87, #126 |
| 130 | Support ticket management | M | Tickets, knowledge, communication, escalation | Ticket connector, #38, #66, #83 |
| 131 | Operational procedure management | M | Approved procedures as tracked workflows | #93, durable objectives (#6), #75 |
| 132 | Policy knowledge workflows | M | Answers from maintained sources | #40, #41, #47 |
| 133 | Marketing campaign workflows | M | Brand, content, publishing, analytics | #94, #95, #96, #89 |
| 134 | Contract review and obligations | M | Comparison, review, commitments | #35, #87, #43 |
| 135 | Invoice processing | M | Extraction, validation, accounting | #31, #33, accounting connector |
| 136 | Expense management | M | Receipts, policies, approval routing | #31, #132, #83 |
| 137 | Financial reconciliation | M | Match records, route exceptions | #88, #33, #83 |
| 138 | Budget management | M | Financial data, forecasts, approvals | #88, #91, #83 |
| 139 | Recruiting workflows | M | Candidates, communication, scheduling | Applicant-tracking connector, #66, #65 |
| 140 | Employee onboarding | M | Access, documents, tasks, policies | #71, #93, #132 |
| 141 | Supplier management | M | Supplier records and documents | #30, #36, a records connector |
| 142 | Procurement workflows | M | Suppliers, requests, budgets, approvals | #141, #138, #83 |
| 143 | Inventory management | M | Stock records and change events | Inventory connector, #76, #79 |
| 144 | Shipment management | M | Status and exceptions | Carrier connector, #76, #81 |
| 145 | Returns management | M | Communication, shipments, inventory | #130, #144, #143 |
| 146 | Learning material workflows | M | Trusted sources, templates, generation | #41, #93, #47 |
| 147 | Tutoring workflows | M | Learner state, assessment, feedback | #39, memory (#42), #146 |
| 148 | Industry-specific integrations | M | Specialized systems and rules | Connector contract (#22), organization policy (#15) |

**Done when (each package):** its evaluation cases pass on a test account of the real system, its permission page entry is complete, and the privacy record names its recipient.

---

## 4. Rules for every phase

1. **A phase starts only when the previous exit gate passed on the live stack.** NOT_RUN and BLOCKED are not PASS (same rule as Phase 15).
2. **Every feature ships behind an owner switch and a per-account rollout list** (`switches.py`, `rollout.py`), off by default.
3. **Every write kind is one row in one registry**: preview renderer, executor, verifier, undo or compensation, permission action. No row, no write.
4. **Every new data kind gets a retention row and a deletion step** before it stores anything (#18, #20).
5. **Every new recipient of customer data updates the privacy record first** (D7).
6. **Content from outside (mail, pages, documents, webhook bodies, tickets) is data, never instructions.** The existing neutralizing and origin checks apply to every new source.
7. **No fixed spending limits return.** Background work runs under the customer's own limits and the owner default (`spend_limits.py`).

## 5. Open decisions for the owner

| Decision | Options | Recommendation |
|---|---|---|
| Launch line | After Phase 5 (read and draft) or after Phase 6 (send and schedule) | After Phase 5 |
| Capacity for #8 | One larger host, or several hosts | One larger host first, with the database moved to PostgreSQL so a second host is possible |
| First provider | Google or Microsoft | Google, because `connectors.py` already targets it |
| Organizations | Launch with single-person accounts, or with teams | Build the organization model in Phase 2 but launch with accounts of one |
| Document parsing | Self-hosted (Docling first) or a managed service | Self-hosted, to avoid a new recipient of customer documents |
| Transcription | Self-hosted with a GPU, or a managed service | Decide when Phase 11 starts; it is the first feature that needs a GPU |
| Telegram | Record only (today) or allowed to run tasks | Decide in Phase 6 with #68 |

## 6. Sources for the tool survey

Consulted 2026-11-14. Most are vendor or aggregator pages; none replaces a test on Lumina's own data.

- Google Workspace remote MCP servers and their preview status: [Workspace developer updates](https://workspaceupdates.googleblog.com/2026/05/agent-tools-and-security-updates-for-workspace-developers.html?hl=en), [mcpservers.org listing](https://mcpservers.org/servers/google/mcp), [LibreChat notes](https://www.librechat.ai/llms.mdx/docs/mcp_servers/google_workspace)
- Durable execution, idempotency keys and compensation: [Durable agents and checkpoints](https://tianpan.co/blog/2026/04/23/durable-agents-async-queue-workflow-checkpoint), [Compensating transactions in agentic systems](https://tianpan.co/blog/2026/03/17/compensating-transactions-failure-recovery-agentic-systems), [Idempotency before checkpoints](https://rss.boorghani.com/durable-agent-workflows-need-idempotency-before-they-need-checkpoints), [When a retry wrapper is enough](https://www.softwareseni.com/what-durable-execution-guarantees-and-when-a-retry-wrapper-is-enough/)
- Document parsing and OCR: [Open-source OCR tools 2026](https://unstract.com/blog/best-opensource-ocr-tools/), [Open-source OCR models](https://blog.roboflow.com/best-open-source-ocr-models/), [Parser comparison](https://www.nutrient.io/blog/best-document-parser-llamaparse-unstructured-reducto/)
- Transcription with speakers: [WhisperX diarization](https://www.forasoft.com/learn/ai-for-video-engineering/articles-ai/whisperx-diarization-word-level-timestamps), [Self-hosted transcription tools](https://dev.to/zackriya/10-best-self-hosted-meeting-transcription-tools-in-2026-58oi)
