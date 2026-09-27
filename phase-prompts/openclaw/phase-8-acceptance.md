# Phase 8 — End-to-end owner acceptance and operational handoff

Demonstrate that the owner can give one product objective and receive a
working, verified result from one coherent agent. Test the configured system
through its actual owner channel, then hand over accurate capabilities,
evidence and recovery instructions. Avoid introducing new authority to make
the demonstration succeed.

Read [the execution contract](execution-contract.md), accepted Gate 7 evidence,
evaluation results, architecture, migration decisions and runbook. Recheck the
current release/configuration against the tested versions. Rerun affected
checks if they changed; a prior passing suite is not proof for a new policy.
If the selected browser route includes Jev, require accepted
[Gate 7A](phase-7a-jev-browser-optimization.md) evidence and use that final
tested route in this owner-channel run. If optimization failed or was excluded,
record the baseline route; do not activate Jev just for the acceptance demo.

## Required result

One real Telegram-initiated research → design → native Codex build → tests →
browser verification → independent ACP review → fix → handoff run. The
artifact works in its private project workspace, stays within the objective
budget and has a trace linking every required stage to actual evidence.
Existing personal integrations remain within their approved scope.
Verify that OpenClaw is the sole agent runtime serving this new workflow;
there must be no duplicate loop, router, approval engine or scheduler.

## 1. Define a bounded acceptance task

Use the owner's chosen product idea and budget if already supplied. Otherwise
select a small disposable private product, such as a reading-list manager:
add validated title/URL entries, tag/search/filter them, edit reading status
and notes, persist after reload, and export the fixture list as JSON. No public
deployment, production accounts, payments or messaging to other people is
needed. Define the final acceptance assertions and allocate research/build/
verification/fix budget within the existing ceilings before starting.

Prepare this request with concrete values and submit through the supported
owner Telegram path, or ask the owner to submit it if a manual start is
required. Do not forge an owner identity or approval.

> Research whether [specific product idea] already exists. Use primary sources
> to compare the most relevant alternatives and identify a useful, achievable
> improvement for [target user]. Choose a small scope and explain the tradeoffs.
> Build the agreed private app in [scoped project workspace] using native Codex.
> Verify the acceptance checklist with tests and real browser interactions,
> obtain independent ACP review, fix valid defects and give me the working
> project with start/test instructions, evidence and known limits. Keep the
> entire objective within [verified budget/time allocation]. Ask for an owner
> decision only if a real scope or authorization blocker remains.

After launch, let the runtime perform the workflow. Operator-side observation
and verification are allowed; do not secretly build the app outside OpenClaw
and present it as the agent's result. Owner intervention is limited to actual
decisions/approvals or a clearly reported dependency.

## 2. Inspect the actual workflow

Research workers must return verified primary-source references, relevant
competitor facts and clear uncertainty. Compare a bounded set of relevant
products; do not claim global novelty or proven market superiority from a few
searches. Separate evidence, inference and design choices. The chosen
improvement must trace to a user need and a feasible implementation decision.

Verify that the orchestrator produces a concrete spec/checklist before the
native build, uses the configured model/worker roles appropriately, and does
not ingest hostile raw content into a privileged instruction path. Codex
must write in the approved workspace; the ACP reviewer must be genuinely
independent and review the resulting snapshot. Test the acceptance checklist
and actual UI controls, then verify fixes on the delivered revision.

Capture the parent objective ID, worker/native/ACP run references, source
support, repo/diff or content hash, test commands/results, browser evidence,
review findings/dispositions and any approval IDs. Correlate these records;
the agent's narrative is not a substitute for a missing stage. Record real
usage for every billing route and distinguish unknown/inferred amounts.

Include a harmless status request during the run: it must report accurate
confirmed progress without duplicating work. Verify that no public deployment,
unsolicited message, policy widening, new schedule or credential exposure
occurred. If a restricted action is requested, inspect the actual native
approval result before any effect. Do not create an unnecessary external
effect just to demonstrate approval; link prior valid approval evidence.

## 3. Check service continuity and the final artifact

Start the delivered artifact using only its recorded setup instructions and
the declared dependencies; verify every core flow, reload persistence and
error handling. Keep the preview private and record its access/stop steps.
If it fails, route the concrete reproduction through the configured fix path
and reverify the affected checks rather than replacing it with a mock.

Run final runtime health, config validation, doctor and secrets/security
audits; reconcile known warnings with the accepted baseline. Check backup
freshness, budget enforcement evidence and approved connector health. Verify
server availability with the Mac UI tunnel closed or disconnected, then
restore owner access using the documented procedure. The Mac must not be an
availability dependency. Do not stop live services simply to simulate this.

## 4. Prepare a usable handoff

Update `RUNBOOK.md` with exact start/stop/restart and health procedures;
owner UI/Telegram access; updates/rollback; backup/restore with retention and
measured RPO/RTO; secret rotation; budget adjustments; connector revocation;
memory correction/deletion; task pause/cancel; schedule disable; skill review;
and failed-run investigation. Distinguish observed procedures from untested
instructions. Verify representative commands in an isolated target where
necessary, and state their required host/account.

Update `ARCHITECTURE.md`, `MIGRATION_DECISIONS.md` and `BUILD_LOG.md` to match
reality. Record old AgentAI retention separately; acceptance does not authorize
its deletion or stopping a separately retained service. State its observed
status rather than claiming it was retired. Keep secrets/backups out of git
and review the complete diff.
Produce `plans/phase-8.md`, the acceptance checklist, correlated run summary,
artifact instructions and execution-contract manifest.

## Gate 8 — Definition of done

PASS requires OpenClaw to serve the new workflow without a duplicate runtime;
the real owner-channel objective and every artifact acceptance assertion to
pass; sourced research, native build, tests, browser checks,
independent review and fixes to have trace evidence; the current trust/budget
and approved integration boundaries to hold; memory/durable-work/recovery
proof to remain valid; and the runbook to support server operation without the
Mac. Any missing required stage, unsafe effect or unresolved required earlier
gate blocks completion. Owner acceptance must be recorded as an actual owner
decision, never inferred from silence.

Give one concise handoff: what works, where the project is, how to run it,
evidence, observed spend, known limits and shutdown/recovery steps. Identify
optional follow-ups separately. Stop after Phase 8; the later dashboard is a
separate product phase, not a condition to retroactively claim this run passed.
