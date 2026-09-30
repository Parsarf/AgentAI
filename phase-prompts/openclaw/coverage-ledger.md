# Coverage ledger — old requirements and new customer work

This is a planning coverage map, not a new acceptance report. Baseline sources:
BUILD_LOG (latest dashboard 8B and research 4A entries), existing Phase 0–12
prompts before replacement, source brief, `plans/remaining-build-items.md`,
Phase 4/4A/5/6/7/8/8B/9/10 records and `evals/cases.yaml`/RESULTS.md.
Current user scope supersedes old personal-only restrictions on accounts/billing.

Phase 1 must seed an actionable requirement ledger with one row per assertion
and retain all existing case IDs. Read full source records when implementing;
this summary does not overwrite them. More recent BUILD_LOG evidence takes
precedence over stale plans. Historical phase labels remain historical.

## Ten requested customer workstreams

| Requested workstream | New implementation phase(s) | Acceptance phase(s) | Starting position |
|---|---|---|---|
| 1 Offer, supported work/files/plans/live/retention/failure, screens and example | 1 | 15, 17, 18 | Missing customer contract; owner capabilities exist |
| 2 Accounts/recovery/roles/audit/account→deployment/server-only credentials | 2, 3 | 3 targeted, 15 | Owner sessions/audit reusable; customer identity/mapping missing |
| 3 Create/start/stop/upgrade/backup/restore/delete; tenant resources/secrets/budgets | 2, 4, 5, 14 | 4 targeted, 15 | Single deployment exists; customer lifecycle/isolation missing |
| 4 Chat/projects/send/stream/history/retry/cancel | 6 | 15, 17 | Viewer exists; customer chat adapter/native controls unverified |
| 5 One bot ingress, numeric identity, expiring single-use codes, project selection/shared history | 7 | 15, 17 | Owner bot exists; customer routing/linking missing |
| 6 Projects/files/versioned outputs/preview/download/provenance/ZIP/object denial | 6, 8 | 8 targeted, 15, 17 | Owner file view reusable; product artifacts/uploads/bundles missing |
| 7 Plan/sources/files/commands/tests/approvals/errors/result/pause/reconnect/private-reasoning exclusion | 9 | 15, 17 | Owner audit SSE exists; scoped durable product events/control gaps |
| 8 Every-route tokens/cost, estimated/final usage, plans/admission/checkout/invoices/cancel/failure/webhook retries | 5, 13 | 15, 17, 18 | Owner proxy caps exist; per-task attribution/customer ledger/billing missing |
| 9 Encrypted off-host backup/tenant restore/monitor/alerts/incidents/rates/rotation/rollback/review | 2–5, 14 | 15, 18 | Operator tooling/partial proofs reusable; customer recovery gaps |
| 10 Controlled real beta/tasks/support/payments then open paid signup | 17, 18 | 17, 18 | Not implemented/accepted |

## Every old executable phase has a new home

| Historical phase | Requirements retained | New phases |
|---|---|---|
| 0 Research/migration | Installed capability/version matrix; architecture/data retention/cost/native-gap decisions; always-on server; retired code not ported | 1, 2; final consistency 18 |
| 1 Secure owner agent | Private Gateway/auth; secret custody; model access; independent daily/monthly and store-outage denial; owner/non-owner Telegram and UI auth | 2, 5, 7; 15 |
| 2 Sandbox/approvals | Host sentinel/tool denial; exact approval/deny/expiry/no-effect; authority classes; stricter unattended; effective policy | 2, 4, 9, 10; 15 |
| 3 Trust workers | Orchestrator/researcher/browser/critic, restricted effective tools, sourced primary research/injection/no-instruction-storage, trivial-no-spawn, skills | 2, 10; 15 |
| 4 Codex/review/debug | Native builder vs independent ACP reviewer; verified process/credential/billing boundaries; board/browser/review/fix and ID-zero failing-before/passing-after regression | 4, 5, 10; 15, 17 |
| 5 Memory/durable/scheduling | Source/date/confidence/confirmation; selective recall+12 unrelated facts/correction/delete; native states/controllers/checkpoints/restart/cancel; timezone/no-change/approval/reconciliation | 5, 9, 10; 15, 17 |
| 6 Integrations | Google/GitHub permission/identity/scopes/refresh/revoke; restricted readers; draft-only vs writes; uncertain-write receipts; auth/injection/outage/unauthorized-account checks | 11; 15, 17 for selected connected services |
| 7 Operations build | Remaining gaps inventory; native backup+DB consistency/schedule/freshness; encrypted off-host; isolated restore/rollback; fixtures/runner/evidence | 1, 10, 14; 15 |
| 8 Dashboard build | Real status/account/work/files/decisions/integrations/cost/audit; API roles/auth/native compatibility; app no Docker socket; safe file boundaries; accessible UI; scoped identity/provisioning | 1–9, 11, 13, 14; 15 |
| 9 Optional browser build | Typed action candidates/schema/confidence; stale/injection/outage/budget/fallback/transport; separate calibration/held-out; disabled adapter | 12; 16 optional |
| 10 Full evaluation | Reasoning/coding/research/browser/memory/durability/delegation/failure/budget/security; direct auth/file/stream/approval/audit tests; scheduled backup/restore/restart/rollback/RPO/RTO; independent review | 15 |
| 11 Optional comparison | 30×3 paired runs/route costs/failures/latency/confidence; frozen reliability/savings; mid-task kill switch/canary/rollback | 16 optional |
| 12 Acceptance/handoff | Real Telegram research→design→native build→tests→browser→independent review→fix→reproduce/handoff; one native agent runtime; budgets and runbooks | 17, 18 |
| Later 4A research optimization | Brave/native baseline, actual middleware loading defect, private pass-through/key/budget boundaries, separate research correctness/citation/savings/promotion proof | 11, 12, 16 optional |
| Later 8B dashboard | Dotted/root filenames, hashed/expiring/revocable sessions, single-use version downloads, SSE cursor/pause/filters/tree, truthful status/cost, specialized views, unverified HTTP/controls and intermediate-path race | 3, 6, 8, 9; 15 |
| Source brief not isolated into a phase | Model roles/fallback; meaningful skills/self-improvement proposals; autonomy classes; project context/artifact summaries; verification before claims; no agent purchases; maintainability/git/runbooks | Contract, 1, 2, 5, 10, 11, 14, 18 |

## Unfinished acceptance and implementation — explicit carry-forward

| Item / existing case ID family | Last recorded situation to verify | New home |
|---|---|---|
| T10-OWNER-TELEGRAM-REPLY / DENY; T10-UI-OWNER-AUTH | Owner participation pending in partial suite; do not erase because customer UI is new | 15 |
| T10-APPROVAL-HOST-EXEC-CARD / TIMEOUT-DENY | Real card/deny/expiry proof pending; native/UI scope cannot be invented | 9, 10, 15 |
| T10-NATIVE-BUILD-BOARD / INDEPENDENT-ACP-REVIEW; debug/browser fixtures | Harness build evidence exists; quota/reviewer admission/complete browser acceptance unresolved | 5, 10, 15, 17 |
| T10-MEMORY-SELECTIVE-RECALL / CORRECTION-DELETION | Native setup exists; meaningful retrieval/correction/deletion proof deferred | 10, 15 |
| T10-DURABLE-RESUME-CANCELLATION | Persisted goals/tasks are not an activated managed recovery controller | 10 implementation, 15 proof |
| T10-SCHEDULING-ADMISSION | Unsupported historical concurrency-one setting; stricter/quiet/timezone/restart/approval proofs still needed | 5, 10, 15 |
| T10-INTEGRATION-AUTH-FAIL-CLOSED; live Google/GitHub acceptance | Disabled read-only definitions; owner sign-ins deliberately deferred | 11, 15; required connected scope remains blocked |
| T10-RESEARCH-CITATIONS / INJECTION-NO-EFFECT | Updated PASS from 2026-09-28 baseline; recheck applicability to new tenant architecture | 10 reuse, 15 affected boundaries |
| T10-BUDGET-DAILY-CAP / MONTHLY-CAP / DB-OUTAGE / SECURITY-BUDGET-PROOF | Prior live/partial proof; every new paid route and task attribution still need proof | 5, 15 |
| T10-DASH-* incl AUDIT-FAIL | Many owner boundaries passed; audit failure not induced; customer paths need full direct-object tests | 3, 8, 9, 15 |
| T10-DASH2-* | 8B regression/SSE evidence exists; residual intermediate symlink race and native HTTP token/endpoint probe unverified | 6, 8, 9, 15 |
| T10-OPS-SCHEDULED-BACKUP-FIRES | Schedule configured; actual fire/archive/RPO/RTO observation pending in recorded suite | 14, 15 |
| T10-OPS-* restore/restart/rollback | Isolated restore/corrupt rejection partly proved; full rollback and tenant-selective encrypted off-host restore remain | 4, 14, 15 |
| T11-* calibration/comparison | Disabled browser adapter built; live transport/account/separate billing evaluation unfinished | 12, 16 optional |
| Phase 4A middleware loader | Config-enabled but absent startup registration; toggle left OFF, NOT PROMOTED | 12 repair; 16 separate research proof |
| Brave key exposure | Rotation obligation recorded in BUILD_LOG; never repeat key in prompt/evidence | 11 custody; 14 rotation; 18 check |
| Final owner-channel workflow | Required stages and handoff not all accepted; product adds customer accounts/artifacts/payment proof | 17, 18 |

## Required, deferred and optional are different

A later release keeps a requirement in the future ledger with an owner/reason,
dependencies and a new phase reference. A required launch item with missing
credential/budget/isolation/controller is BLOCKED. An optional adapter may be
excluded; its measured failure is still FAIL. No phase renumbering changes
historical results or authorizes previously deferred live account setup/tests.

## Source references

- [Implementation history](../../openclaw-project/BUILD_LOG.md)
- [Remaining-build inventory](../../openclaw-project/plans/remaining-build-items.md)
- [Existing case definitions](../../openclaw-project/evals/cases.yaml)
- [Partial evaluation results](../../openclaw-project/evals/RESULTS.md)
- [8B implementation/limits](../../openclaw-project/plans/phase-8b.md)
- [4A research decisions](../../openclaw-project/plans/phase-4a.md)

The historical prompt sources are recoverable from Git; superseded prompt
files are deliberately absent from the working tree. Do not create a second
competing execution sequence from those records.

## Retired multi-user prompt history — requirements recovered, runtime replaced

The older `phase-prompts/phase-1-*` through `phase-7-lean-tests-ops.md` and
README-lean at Git revision `5e6f3fa` were also inspected. They had already been
removed before this request; their source files are not restored. Native
OpenClaw replaces their custom-loop/router/vault/scheduler implementations.

| Older requirement | New home / disposition |
|---|---|
| Foundation/accounts/config/logs/tenant DB/events | 2, 3; direct tenant proof 15 |
| Core research/code/context/memory/approval/notify/dashboard/Telegram | 5–10; 15, 17 |
| Per-user jobs/watchers/reusable skill library | 10: unchanged zero-model checks, changed escalation, tenant skills/restart/notification fixtures; 15 |
| Login-gated browser/encrypted per-user vault/cookies/profiles | 4, 11: native custody, scoped browser auth/profile/revoke, SSRF/redirect boundaries; 14 backups, 15 proofs |
| Actual execution-path usage/cache prices/reservations/flat billing/plan gating | 5, 13; 15, 17; usage overage remains explicit later scope unless selected |
| Partially implemented disabled opt-in customer-funded payments | Optional follow-on 19: actual provider preflight, independent user funds, exact native approval, atomic caps, durable idempotency/unknown recovery, denial-first/sandbox proof; baseline disabled |
| Unfinished verification/deployment/backups/load | 2, 14, 15: disposable target guards/test result integrity, actual container boundaries, least-privilege DB, restart/shutdown, encrypted profiles/key custody, isolated restore/load/smoke |
| Old one-process/in-memory bus/custom SDK framework assumptions | Replaced by verified native runtime and durable product service contracts; do not port retired implementation |
| Deferred overage/multi-provider payments/disputes/recurring purchases | Explicit future ledger under 1/18/19; no implicit launch promise or funds movement |

Phase 19 is a separate follow-on release plan, satisfying the rule against
adding unplanned feature builds after baseline final acceptance. Selection,
provider capability, native enforcement and activation are separate gates;
its existence grants no payment authority.
