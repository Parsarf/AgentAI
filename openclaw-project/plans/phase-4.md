# Phase 4 — plan (codex-review)

Owner directed Phase 4 on 2026-09-26 while Gate 3 checks remain
pending. Per the contract this is a **recorded exception, not a pass**: Gate 3
stays NOT PASSED until the sourced-research and injection checks actually run
and are verified.

## Objective

The orchestrator gives native Codex a scoped build task, verifies the artifact
with real tests and browser interaction, obtains independent ACP review, fixes
valid findings, and separately proves focused debugging on a seeded repo.

## Latest checkpoint — 2026-09-27 17:43 UTC (owner verification deferred)

Native board build and debug proof remain complete, with prior test evidence
preserved. Owner asked to perform sign-in/Chrome actions personally, then
explicitly deferred all remaining tests. No further tests or review inference
started after that direction. Phase4 remains awaiting verification, not PASS.

Completed offline stopped-state backup:47 SQLite checks pass; hash/path in
`evidence/phase-4/20260927T173530Z/manifest.json`. Offline Doctor emitted findings
then timed out124; not a clean pass. Gateway restarted and healthy. No host
security weakening or unrelated automation fix. Prior coordinator ultimately
failed after its child completed; successful result collection not claimed.

Saved ChatGPT profile works; current5h5%/week16%,zero credits. No new login
needed. Local-only preview helper and Chrome checklist prepared, then preview
stopped at owner request. Independent ACP setup/review remains pending; cached
Claude adapter/SDK discovered, no reviewer model call or activation. Earlier
native browser-worker proof remains deferred under the manual-browser handoff.

## Inventory facts (verified live, 2026-09-26)

- Gateway: OpenClaw 2026.9.6 (eb377ac), Docker Compose, container
  `openclaw-production-openclaw-gateway-1`; 88 GiB free disk; ~1.1 GiB RAM
  headroom (tight — run browser + app-server one at a time).
- `codex` plugin: bundled, **disabled**. The plugin ships and manages
  `@openai/codex` 0.155.1 (managed stdio app-server) — no standalone `codex`
  binary needed. Docs: https://docs.openclaw.ai/plugins/codex-harness ,
  …-reference , approval/sandbox and auth child pages.
- **OpenAI/Codex auth: ABSENT**, confirmed at 22:06 UTC: the OpenClaw
  profile list is empty, bundled Codex `login status` says `Not logged in`,
  no `auth.json` was found under `/home/node`, and no OpenAI/Codex env-key
  names were present. Build is BLOCKED until the owner completes
  `models auth login --provider openai --method device-code
  --profile-id openai:default --agent main` or supplies an API-key profile
  with an independently verified OpenAI budget. This is a
  separate billing route from the LiteLLM proxy; the $2/24h + $25/30d
  LiteLLM caps do NOT cover Codex.
- Reviewer: use ACP/acpx's `claude` adapter, not the Anthropic CLI backend
  (different integration). The CLI and its login were absent from the inventory.
  Routing Claude through LiteLLM is a proposal, not a verified integration.
  Prove endpoint/model compatibility, protected auth, budget enforcement and
  source read-only isolation before activation. ACP `approve-reads` plus
  noninteractive `deny` is a permission layer, not an OS filesystem boundary.
  Independent: fresh session, tested snapshot, no builder conversation.
- Browser: `browser.enabled=false` (Phase 1 hardening). Phase 4 requires real
  browser verification → activation batch must enable browser, grant the
  `browser` tool ONLY to `browser-worker` (main stays denied), and satisfy
  readiness/isolation checks. Browser doctor currently fails because browser
  control is disabled. The earlier missing-binary claim was incomplete:
  `/home/node/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome`
  exists and reports Chrome for Testing 153.0.8010.12. A runnable binary does
  not prove a working browser or a safe worker sidecar.
  The official `v2026.9.6` sidecar image is now built as
  `openclaw-sandbox-browser:phase4-2026.9.6` (image ID
  `sha256:67526310a29737631880f6a1af93c7953587a20c484725351dcab1160c3c11cd`).
  A disposable probe returned HTTP 401 for absent/wrong auth, succeeded with
  the synthetic token, bound CDP only to loopback and had no Gateway state or
  socket. The probe was removed. Browser-worker activation is still pending.
- Skills: corrected `software-project` and `debugging` are installed and
  verified eligible/model-visible for main. Main has no explicit skill filter;
  the previous worker filters remain. Both pass the skill schema validator.
  Recovery preserves existing edits; UI tasks require actual browser actions
  and phase-required fresh ACP review. Known baseline defects do not prevent
  authorized debugging.
- Gate 3 status: trivial-no-spawn PASS; research + injection checks pending
  (budget-capped until 00:00 UTC). NOT re-scheduled after owner asked to
  delete the operator cron; to be run manually or on owner instruction.

## Execution boundary (to verify at activation, before any build)

- Builder: use a dedicated OpenClaw agent with Docker sandbox mode `all`,
  workspace = its disposable repo, bounded tmpfs scratch, no network, no
  Docker socket or live-state/credential mounts. The local app-server retains
  protected OpenClaw auth; project file/shell tools run through the native
  sandbox-backed dynamic tools. Set guardian explicitly and clear inherited
  credential env names. Guardian alone does not restrict reads. The stable
  sandbox path disables host-side Code Mode/MCP/app tools; do not enable
  experimental exec-server unless stable execution cannot satisfy the task
  and a documented, separately probed change is warranted. These boundaries
  are planned, NOT yet demonstrated by a native turn. Probe an inside write,
  an outside synthetic canary read/write and socket/state absence.
  The pinned Gateway image supplies Node 24.19.0 and passed those checks in
  an isolated operator container with only a synthetic workspace mounted,
  root read-only, non-root user, no network, dropped capabilities and resource
  limits. Reuse this cached image for the dedicated builder instead of adding
  Node to every worker or installing packages during agent execution. This
  container probe does not pass the native-harness permission gate.
- Reviewer (claude-cli via ACP): read-only on the tested snapshot + own
  scratch; source writes denied; no builder conversation or reasoning.
- Repos live in container path `/home/node/.openclaw/work/phase4/`
  (`board/` builder repo, `debug-repo/` seeded fixture, `scratch/`). Path
  recorded; work/ is not a security boundary by itself — permissions above
  are.

## Cost allocation

- Codex build/debug: owner's ChatGPT/OpenAI route (new; caps unknown →
  record usage from `/codex status`, never report unknown cost as zero).
- Reviewer + any model turns: LiteLLM proxy (existing $2/day, $25/30d).
  Reserve ≥30% of remaining daily budget for verification/fixes.

## Steps

1. Activation batch (one backup → one config change → verify): enable codex
   plugin (after auth exists), enable browser, grant browser tool to
   browser-worker only, then `config validate`, `doctor`, `security audit`,
   `browser doctor`, codex diagnostics, and the §1 permission probes.
2. Author + install `software-project` and `debugging` skills (completed).
   The board spec and fresh-review request are installed from
   `config/phase4-fixtures/`; implementation must still come from native Codex.
3. Seed `debug-repo` (done at plan time; see SPEC.md inside).
4. Build: orchestrator → Codex builds task board per spec; orchestrator runs
   behavioral tests; browser-worker exercises every core action, empty/error
   states, keyboard, narrow viewport; sanitized screenshots.
5. Review: fresh ACP/Claude session on the snapshot; disposition every
   finding (fixed / disproved / deferred); fix valid ones via Codex; rerun
   affected checks.
6. Debug proof: Codex reproduces id-0 filter bug, adds regression test
   (fails before, passes after), minimal fix, neighbors still pass.
7. Evidence: `evidence/phase-4/<run-id>/` summary.md + manifest.json;
   BUILD_LOG update; secrets/security audits; changed-artifact secret scan.

## Rollback

Preparation backup (verified, 0600 under 0700):
`/opt/openclaw-production/backups/phase4-preparation-20260926T220832Z/openclaw.tar.gz`
with Compose copy in that directory; SHA-256
`c97f0d0ee1b4445c075e4dff27b2c77e4170b5a41e0ec365d85a8e9db7adade6`.
No runtime config or service change has been applied in this continuation.
The audit-confirmed state-directory mode was repaired from 0755 to 0700, keeping
its existing node ownership. Final audit: zero critical, one existing warning
that main's coding profile overrides the global minimal profile; secrets clean.

Before activation capture each authored field's presence and value privately.
Rollback only this phase's fields and own artifacts against that snapshot;
preserve newer unrelated edits. Disable the scoped capabilities, then validate
and verify health. Restore skill files from the verified archive into a separate
directory before copying specific files back. Never delete the whole phase work
directory or restore an entire backup over live state. Keep the seeded repo,
evidence and other contributors' changes. Actual recovery has not been run.

## Verified source references

- [OpenAI authentication](https://learn.chatgpt.com/docs/auth): ChatGPT and API
  login are different billing routes; headless device login needs owner action.
- [OpenClaw auth isolation](https://docs.openclaw.ai/plugins/codex-harness-reference/auth):
  agent-scoped profiles, ephemeral app-server auth and explicit device login.
- [Native sandbox behavior](https://docs.openclaw.ai/plugins/codex-harness-reference/approval-and-sandbox):
  guardian permissions and sandbox-backed dynamic tools; host process is separate.
- [ACP setup](https://docs.openclaw.ai/tools/acp-agents-setup): adapter aliases,
  read permission policy and separate tool bridges (keep bridges disabled).
- [Docker browser boundary](https://docs.openclaw.ai/gateway/sandboxing/docker-backend):
  dedicated sidecar and `allowHostControl: false`; CLI browser targets host,
  so an operator CLI screenshot does not prove browser-worker delegation.

Gate 4 remains BLOCKED until auth, native boundary probes, real builds,
browser flows, independent review and debugging evidence exist. No model call
was made during this continuation's preparation.
