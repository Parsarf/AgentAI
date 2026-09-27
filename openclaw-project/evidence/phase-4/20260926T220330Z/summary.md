# Phase 4 continuation evidence

**Status: BLOCKED — authentication and guardian plugin activation complete; native build/review/debug gates remain open.**

Run began 2026-09-26 22:03:30 UTC. Phase3 remains unpassed under the recorded owner exception. No inference request or cap increase occurred.

## Observed checks

| Check | Status | Result |
|---|---|---|
| skills_schema | pass | Both skills valid. |
| skills_installed | pass | Both eligible, modelVisible, unblocked; installed SHA-256 matches local source. |
| backup | pass | Verified archive copied privately with Compose backup; archive 0600, parent0700. |
| config | pass | valid=true; no schema warnings. |
| codex_guardian_draft | pass | One update validated; not applied; plugin remains disabled. |
| codex_auth | pass | Owner confirmed enabling device-code sign-in; toggle on; browser shows Signed in to Codex; persisted OpenClaw main profile count1, provider openai. No auth values retained. |
| browser_readiness_initial | blocked | Browser control disabled by existing policy; not counted as working native browser. |
| browser_image | pass | Official v2026.9.6 source; expected authenticated CDP contract label. |
| coding_container_boundary | pass | Inside write succeeds, outside write denied, canary read absent, host canary unchanged, state and Docker socket absent; Node24.19.0. |
| browser_container_boundary | pass | Authenticated CDP200, absent/wrong auth401, loopback-only binding; no state/socket; Chrome154.0.8037.57; container removed. |
| fixture_baseline | pass | Three existing debugging tests pass in read-only isolated Node container; seeded defect preserved. |
| secrets | pass | clean; three refs resolved; zero plaintext, unresolved, shadowed or residue findings. |
| security | pass | State0755 warning repaired to0700; final zero critical, one existing minimal-profile override warning. |
| doctor | pass | Completed; optional unused skill prerequisites missing and memory search intentionally disabled; not a warning-free pass. |
| health | pass | HTTP200; ok=true status=live. |
| native_builder_boundary | blocked | No authenticated native turn yet; container probes do not substitute. |
| native_build | blocked | Auth saved and guardian plugin enabled; isolated builder not yet configured; account quota and native boundary probes unverified. |
| app_acceptance_browser | not_run | No app implemented yet; worker access remains disabled. |
| independent_acp_review | blocked | No delivered source; reviewer auth/isolation not configured or proved; existing Anthropic daily window exhausted per Phase3 evidence. |
| native_debug_regression | not_run | Seeded baseline retained; regression and fix must come from native coding path. |
| codex_activation | pass | One update validated and applied; guardian/on-request/auto_review/workspace-write; agent-scoped home, cleared credential env, discovery enabled, session catalog disabled. Config valid without warnings. |
| codex_catalog | pass | Hosted catalog unchanged,1069 models/44 providers; seven available OpenAI models: gpt-6-astra, gpt-6-sol, gpt-6-luna, gpt-5.6-sol, gpt-5.6-terra, gpt-5.6-luna, gpt-5.5. No inference or quota proof. |
| health_after_activation | pass | HTTP200 live; Gateway/Postgres healthy and LiteLLM running;2017MiB available memory,606MiB swap used; only loopback Gateway ports. |
| approval_review_availability | blocked | Command not executed: automatic approval review reached usage limit. This was a review failure, not an unsafe-action determination. No bypass attempted. |

Changed-artifact known-secret scan passed; `git diff --check` clean.

## Reproduction and limits

Run scripts under `openclaw-project/bin/phase4/` on the VPS as the operator. They use disposable, bounded containers with synthetic inputs. The browser probe needs the built official image. Raw backups and login traces stay private.

The first browser probe encountered an uncaught startup connection reset. The second exposed a missing probe environment variable (`OPENCLAW_BROWSER_CDP_PORT`), which the Gateway normally supplies. With that supplied and bounded readiness polling, authenticated control passed. No protection was relaxed to repair these probe setup errors.

Both installed skill hashes match local files. Recovery now preserves pre-existing staged/unstaged/untracked edits, and UI/review evidence cannot be inferred from a plan. Fixtures have starting commits; the three neighboring tests pass without an ID0 regression, deliberately preserving the debugging task.

The native builder must still execute the same isolation probes through OpenClaw. The browser worker must still perform the actual app flows. An operator container or endpoint response does not prove either model-mediated path.

## Owner authentication

ChatGPT device sign-in was enabled after explicit owner confirmation. The browser showed “Signed in to Codex”; OpenClaw persisted one main profile for provider `openai`. The CLI process ended137 during the subsequent deliberate Gateway restart, after persistence was verified. The authenticated catalog remains available. No login code, account identifier, token or credential is stored here.

The native guardian plugin is enabled; no builder agent or model inference has run. The next read of the native quota RPC schema was not executed because automatic approval review reached its usage limit. This was a review failure, not an unsafe-action determination. Further VPS work must await review availability; do not bypass it.

## Backup and cleanup

Verified backup: `/opt/openclaw-production/backups/phase4-preparation-20260926T220832Z/openclaw.tar.gz`. SHA-256: `c97f0d0ee1b4445c075e4dff27b2c77e4170b5a41e0ec365d85a8e9db7adade6`. Mode0600 in a0700 directory; not encrypted; no restore performed. Probe containers and synthetic browser auth file were removed. Only this run’s synthetic canary files remain.

A second verified preactivation archive including the new login is `/opt/openclaw-production/backups/phase4-codex-activation-20260926T222626Z/openclaw.tar.gz`, SHA-256 `419839566f6ed4329ceb6b3d219d1016e5ed9fa0cf616da5e72aa5ca7255759d`,0600 in a0700 directory. A copied activation batch initially had root-only ownership inside the Gateway; only that temporary file was changed to1000:1000 before dry-run/apply succeeded.

See [manifest.json](manifest.json) for exact versions, fixture revisions, checks, billing routes, warnings and blockers.
