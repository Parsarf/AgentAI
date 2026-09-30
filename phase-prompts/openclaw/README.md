# AgentAI customer platform — canonical phase prompts

Start with **Phase 1**. This is the single replacement plan requested on
2026-09-29: **19 phases: 16 baseline phases, 2 optional optimization phases and 1 optional follow-on purchase release**. It combines
all ten customer-product workstreams with unfinished personal-agent builds,
integrations, operations and evaluation. The old Phase 0–12 executable prompts
and personal-only source brief have been replaced. Git retains their history.
Historical implementation plans/evidence remain intact and keep old labels.

## Use one phase at a time

Open the linked phase and paste its complete prompt with repository access.
The [execution contract](execution-contract.md) supplies the shared rules;
[coverage ledger](coverage-ledger.md) maps every previous requirement to its new
home. Each phase specifies dependencies, deliverables, assertions and close-out.
Start from actual implementation; rebuilding proven capabilities is unnecessary.

Builds prepare runnable acceptance cases and use relevant inexpensive checks.
Full/paid evaluation remains deferred until explicitly resumed. Finishing builds
or rewriting prompts does not authorize new tests, invitations, live payments
or public launch. Boundary checks needed to enable a feature remain mandatory.
Independent build work may continue while an activation prerequisite is blocked.

| Phase | Prompt | Stage | Dependencies |
|---|---|---|---|
| 1 | [Product contract, screens and cost model](phase-01-product-contract.md) | Design | None |
| 2 | [Platform architecture and secure runtime boundary](phase-02-platform-foundation.md) | Build | 1 |
| 3 | [Customer accounts, recovery, roles and audit](phase-03-customer-accounts.md) | Build | 2 |
| 4 | [Isolated customer agent lifecycle](phase-04-tenant-provisioning.md) | Build | 3 |
| 5 | [Usage ledger, entitlements and task budget admission](phase-05-usage-admission.md) | Build | 4 |
| 6 | [Projects, conversations and dashboard chat](phase-06-dashboard-chat.md) | Build | 5 |
| 7 | [One Telegram ingress with secure account linking](phase-07-telegram-linking.md) | Build | 6 |
| 8 | [Project files, versioned outputs and usable bundles](phase-08-files-artifacts.md) | Build | 6; Telegram attachment wiring after 7 |
| 9 | [Durable live work timeline and task controls](phase-09-live-work.md) | Build | 8 |
| 10 | [Coding, research, memory and durable agent work](phase-10-native-capabilities.md) | Build | 9 |
| 11 | [Scoped customer integrations and account setup](phase-11-integrations.md) | Build | 10 |
| 12 | [Optional Jev/browser and research adapter completion](phase-12-optional-optimization-build.md) | Optional build | 10; 11 when connector transport is needed |
| 13 | [Hosted billing, invoices and access reconciliation](phase-13-billing.md) | Build | 5; consumes the product built in 6–11 |
| 14 | [Backups, recovery, monitoring and security operations](phase-14-operations.md) | Build | 4–13 |
| 15 | [System, tenant, security, budget and recovery evaluation](phase-15-system-acceptance.md) | Evaluation | All required builds 1–14; optional 12 only if selected |
| 16 | [Optional paired optimization evaluation and rollout](phase-16-optional-optimization-evaluation.md) | Optional evaluation | 15 baseline PASS; selected 12 track; explicit paid-test resumption |
| 17 | [Private beta and complete customer workflow](phase-17-private-beta.md) | Beta acceptance | 15 PASS; 16 PASS only for an enabled optimization; invite/payment authorization |
| 18 | [Launch readiness, controlled paid signup and handoff](phase-18-launch.md) | Launch | 17 PASS; launch approval for the concrete release |

| 19 | [Customer-funded purchases — later release](phase-19-optional-purchases.md) | Optional follow-on build/evaluation | Accepted baseline, separate selection/provider/authorization |

Optional phases 12 and 16 may be excluded together; baseline stays available.
Phase 16 evaluates only selected optimization tracks. Phase 15 can test baseline
without optimization acceptance. Phase 17 uses only accepted enabled routes.

## Executed product phases

2026-09-29: Phase1 design READY/PASS and Phase2 foundation READY/PASS for
targeted private checks. [Product phase records](../../openclaw-project/plans/product/phase-01.md)
and [Phase2 record](../../openclaw-project/plans/product/phase-02.md) distinguish
this from customer runtime acceptance. Owner selected the $79/$25/$5 plan.
Phase3 account build is READY with targeted boundaries PASS; real onboarding/customer activation and dependent native retention remain gated. [Phase3 record](../../openclaw-project/plans/product/phase-03.md).
Next implementation phase is4. Existing owner runtime and budget caps preserved.

## Actual starting point — evidence, not phase completion

- Owner runtime, restricted workers, Brave search and browser have implementation
  and partial live proof; inspect BUILD_LOG for exact versions and boundaries.
- Owner dashboard, files and an audit-based SSE live viewer are deployed.
  The Gateway HTTP viewer path is gated/unverified; cancel and approval resolution
  lack verified dashboard-native paths. Owner proofs are not tenant proofs.
- Coding/reviewer, selective memory, durable autonomous resume, scheduling and
  integration acceptance have unresolved checks. Some capability gaps are real,
  including controller/transport/auth requirements; see the coverage ledger.
- Operator backups/isolated restore tools exist with partial drill proof.
  Off-host encryption, scheduled-fire observation and rollback/RPO/RTO remain
  requirements to recheck. Jev research was NOT PROMOTED due to runtime loading.
- Customer accounts, tenancy, shared customer Telegram ingress, task attribution,
  hosted billing and public paid onboarding require product implementation.

The older source brief excluded customers/payments. The user's present request
explicitly adds them; this plan supersedes that scope restriction while retaining
native-runtime and security discipline. Agent purchases remain separate/disabled through baseline launch; optional Phase 19 preserves their unfinished legacy requirements as a separately selected release.
The always-on server remains production; the Mac is an operator workspace.

## Effort, cost and capacity

No reliable calendar or spend total can be calculated from prompts alone.
Phase 1 must populate the [cost/capacity worksheet requirements](execution-contract.md#cost-and-capacity-calculations)
with measured usage, current prices and resource peaks. Phase 5 implements those
limits before paid work. Phase 16 preserves the previous **180 browser task-run**
comparison gate; calibration/adversarial/canary costs are additional.

The progress ledger records `REUSE`, `PARTIAL`, `MISSING`, `BLOCKED`,
`DEFERRED_TEST` and `OPTIONAL_LATER` per requirement, with evidence and case IDs.
A READY build is not an accepted phase. Consult the current build log rather
than inferring completion from a prompt's presence.

## Phase4 target clarification and assessment

Owner requires one service-operated VPS and one shared public domain; customers
supply no server/domain. ADR002's VM-per-customer target is superseded by ADR007.
[Phase4 assessment](../../openclaw-project/plans/product/phase-04-single-vps-assessment.md)
and reproducible capacity checks are complete. Current4GiB/2CPU host admits0
added agents. Native lifecycle/worker/isolation/quota build remains incomplete;
Phase4 is PARTIAL/BLOCKED for activation, not completed or a Phase5 handoff.
Resume Phase4 using the revised prompt after the concrete hardware/isolation
plan; retain full acceptance15. No host changes/customer agents were deployed.

## Existing-VPS trial clarification — 2026-09-30

Owner selected trying the existing server before any upgrade. The current target
is two invite-only accounts, one global running customer task, on-demand private
cells and sequential isolated worker stages. Keep every planned feature; no
hardware upgrade prerequisite for implementation. Default-profile zero-slot
measurements remain historical evidence, not proof of a smaller profile. Follow
`product/EXISTING_VPS_TRIAL.md` and deployment policy v2. Measure a fitting profile
and complete isolation/budget checks before execution. Account invitations do
not automatically start an agent; later resize changes capacity, not accounts,
domain or feature scope. No live deployment or feature activation in this update.

## Phase4/5 local continuation — 2026-09-30

Durable lifecycle metadata/coordinator and offline budget reservation/receipt core
are implemented, with scoped operation/usage read views and fixed MFA operator
queue routes. See platform/agentai_platform/lifecycle/README.md and platform/BUDGET.md
(paths relative to openclaw-project). Native lifecycle/worker dispatch, secrets,
stronger-runtime/quotas/network isolation, real route accounting and a fitting
existing-host profile remain incomplete; runtime/customer/payment/mail gates stay
off. No live migration or listener installed. Package new immutable SQL002/003
and Django004–007 with the release; explicit private bootstrap is required and
old releases reject the newer schema. Host-only lifecycle_status reads counts;
seed_trial prepares one seven-day/$1 entitlement without resetting one already
present. No account or invitation was created. Continue Phase4 native integration
and Phase5 provider enforcement before dependent chat activation.
