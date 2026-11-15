# Roadmap Phase 0 - ship what is written and remove the launch blockers

**Status (2026-11-14): PARTIAL.** The repository work is done and tested; every remaining item is a server step or a merge that needs the owner.

## What passed (live)
- **Live assistant key no longer expires and has no lifetime budget** (done by the owner's run of the key script on 2026-11-14; verified read-only: expires never, budget none, 4,000,000 tokens and 120 requests a minute).

## Diagnosed (read-only, on the server)
- **Why every automatic deploy is refused (exit 30).** The installed `/usr/local/sbin/agentai-deploy` is the 1 November version (hash `665e43ca…`); the repository's is newer (`2ba5d839…`). The installed one has no `forget_manual`, so the hand-release record written on 13 November (528 files in the app tree's `RELEASE.json`, 521 in the supervisor's) was never cleared, and every later commit that touches one of those files is counted as "undoing a manual release": 312, 331, 367, then 379 files.
- **Why manual runs "succeeded" without changing the server.** They were dry runs. The workflow's "Run workflow" form defaults to `dry_run: true`; the server log shows `deploy-dry … dry run passed` for 3157506 and 77e2d46. Nothing was wrong; nothing was deployed.
- **The supervisor tree is deployed automatically** (step 2 of the deploy program copies the new code over it). What the deploy did not do is restart the lifecycle worker or the supervisor, so new supervisor-side code waited for their next restart.

## Built, not yet proven on the server
| Item | What | Proof missing |
|---|---|---|
| 0.2 | The deploy program now replaces its own installed copy after a successful deploy (`install_self`), so it can never again fall behind the repository; it also restarts `agentai-lifecycle-worker` with the other services. Tests in `tests/test_auto_deploy.py` (now in the blocking list) | One real deploy with the new program |
| 0.4 | Timing marks are per thread (`timing.py`), so they stay correct when several requests run at once. `deploy/latency_report.py` already exists | `AGENTAI_TIMING=1` on the server and a week of data |
| 0.1 | PR #39 and this phase's pull request are green | Merge and deploy |

## Not passed
- **BLOCKED P0-DEPLOY** (owner): merge PR #39 and the Phase 0-1 pull request; install the repository's deploy program once; run the deploy workflow with *Dry run* unticked and *Overwrite manual changes* ticked. Commands: `platform/deploy/PENDING_DEPLOY.md`.
- **BLOCKED P0-CACHE** (owner, after P0-DEPLOY): remove the `index: -1` cache point from the server's LiteLLM config and restart LiteLLM. Then verify cache reads grow with the conversation.
- **BLOCKED P0-TIMING** (owner): set `AGENTAI_TIMING=1` in the unit environments.
- **NOT_RUN P0-PUSH**: the push gateway stays off; the open question (who may read the signing secret) is the owner's. The remaining polling in `Chat.tsx` and `useActivity.ts` was left as it is until the stream is on.
- **NOT_RUN P0-LATENCY (0.7)**: the history pre-check, the mirror cursor, cold start and runtime start-up were deliberately not changed. The prompt requires a timing baseline first, and the pre-check is on a correctness path (it decides whether another run owns the session).
- **NOT_RUN P0-OWNER (0.5)**: off-server backup, SSH keys only, Stripe, legal pages, support address, search key, OAuth apps. Unchanged; see `LAUNCH.md`.

## Decisions taken
- The deploy program updates itself rather than relying on someone reinstalling it. The commit's code already runs as root during a deploy (`release.py`), so this grants nothing new; a program that does not parse is never installed, and a failed deploy never changes it.
- The supervisor itself is still not restarted by a deploy: it holds the control socket the cells depend on.

## Needs the owner
1. Merge the two pull requests.
2. The three server steps above (deploy program install and first real deploy, LiteLLM config, timing).
3. The push secret decision.

## Cost, unknowns, rollback
No spend. Unknown: whether the first real deploy of 130+ changed files passes its canary on the server (it passed as a dry run for 77e2d46). Rollback: the deploy program rolls the app back itself on failed probes; the supervisor tree goes back with the `ln -sfn` line it prints.
