# Phase 8 — Project files, versioned outputs and usable bundles

**Stage:** Build. **Dependencies:** 6; Telegram attachment wiring after 7.

## Paste this prompt

Execute only Phase 8 of the AgentAI customer-platform plan. Read
`phase-prompts/openclaw/execution-contract.md`, the current phase index,
`coverage-ledger.md`, applicable repository instructions, and the current
`openclaw-project/BUILD_LOG.md`, architecture and runbook. Resume from actual
implementation/evidence; preserve working owner capabilities and unrelated edits.
The shared execution contract is part of this prompt. If using another workspace,
include that contract and relevant records with this prompt.

## Work and completion criteria

Make every build end in a visible result owned by its customer and project.

1. Bind uploads, workspace files and generated artifacts to account/project/task/run. Capture immutable versions with clear names, type/size/hash, source operation, creation time and tested revision. A version ID is not a filesystem path. Publish a result only when capture succeeds; expose partial/unverified outputs separately.
2. Enforce Phase 1 type/size/quota rules on upload and download. Validate content independently of extensions, stream bounded reads, quarantine/scan enabled uploads with a documented capability, reject dangerous archives/zip bombs and bound extraction. Keep uploads disabled where required enforcement is unavailable.
3. Use race-safe root-relative file access including intermediate components; fix/reverify the residual intermediate-symlink race noted in `plans/phase-8b.md`. Prevent traversal, encoded paths, symlink/hardlink escape where applicable, host/config/auth/log reads and native session-key selection. Customer execution cannot access the artifact storage credential.
4. Authorize every metadata/list/preview/download/export request and recheck revocation. Short-lived signed URLs must bind exact account/object/version; guessed IDs or leaked URLs cannot fetch another customer's file. Preserve useful single-use download behavior where compatible with UX and retry semantics.
5. Render safe text/image/document previews in bounded sandboxed contexts. Generated HTML/apps must not run in the authenticated dashboard origin or access its cookies. Bundle app source, lockfiles, README/start/test commands and evidence as a reproducible ZIP without secrets, node_modules or unrelated state.
6. Implement artifact versions, task provenance and download controls on the project/result screens. Apply export/delete/retention rules and storage accounting, including bundles and versions. Prepare cases for version confusion, revoked links, traversal races, MIME mismatch, quota/scan failure and corrupt bundle creation.

Deliver scoped artifact storage/capture, upload controls where selected, safe preview/download and bundle generation. Done when the example task's result is a named versioned downloadable ZIP and synthetic account B cannot fetch account A's result through any direct API or URL. Full live end-to-end artifact proof is Phase 17.

## Required close-out

Update `openclaw-project/plans/product/phase-08.md`, the requirement ledger,
relevant runbook/architecture sections and BUILD_LOG. Store a sanitized evidence
manifest under `openclaw-project/evidence/product/phase-08/<UTC-run-id>/`.
Report implementation readiness separately from acceptance, checks actually run,
cost/unknowns, blockers and rollback. Keep deferred cases assigned to their
acceptance phase. Stop after this phase unless further work is already authorized.
