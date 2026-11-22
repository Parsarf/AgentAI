# Roadmap Phase 7 - tasks, automation and notifications

**Status (2026-11-20): READY, NOT STARTED.** Nothing of Phase 7 is built yet. This file holds the starting point checked on the live stack, the audit (one line per
feature), the build order and the owner's questions, so that the run of `phases-06-07.md` can start building once the questions are answered. The prompt's rules
apply unchanged: one batch of questions, then build, merge, deploy, and pass the one-week soak on the live stack.

## Starting point (checked on the live stack, 2026-11-20)

- **Release.** Server `/var/lib/agentai-deploy/last` = `origin/main` = `3bc1f30` (PR #82), deployed 09:46 UTC, live acceptance passed; Vercel built the same commit.
  Since then (2026-11-21 00:55 UTC): `a7cd3cf` (PR #84, the policy naming Microsoft), live acceptance passed, and the Microsoft keys installed (`phase-06.md`).
  Every long-running `agentai-*` service is active; no error-level journal line from them since that deploy; disk 136 GB free, memory 9 GB available.
- **Tests.** `ci/run.sh all` on `3bc1f30`: 8 of 8 blocking parts pass (130 s, local).
- **Phase 6.** Built; Google proven live and on for every account; Microsoft configured and open for reading (2026-11-21); exit gate 8 (one Google and one
  Microsoft account) waits for the owner's test run (`roadmap/phase-06.md`, "Needs the owner"). Phase 7 depends on it only for Microsoft's change notifications in #76 (question 1).
- **Switches** (server, 2026-11-20): on: `customer_execution`, `browse_tasks`, `open_access`, `mail_calendar_dashboard`, `customer_uploads`, `customer_knowledge`,
  `mail_calendar_writes`. Off: `connector_writes`, `synthetic_connector`, `jev_routing`. `customer_schedules` has no entry (off) and is **locked in code**
  (`switches.py`: "Locked until the safety checks for unattended work have been run (Phase 15)"; the old `plans/product/phase-15.md` ended PARTIAL on 2026-10-13).
  The engine's proof is Phase 1 (`roadmap/phase-01.md`, rows 78e and 79e): #78 replaces the lock with a precondition that links that evidence, as the prompt says.
- **Data on the server.** schedules 0, watchers 0, commitments 0, Telegram links 0, MCP connections 2. Migrations applied through `0054`; the next is `0055`.
- **Notification channels.** In-app: the push gateway (`agentai-push`, `live/push.py`) is running. Email: SMTP host, user and password are set, `AGENTAI_MAIL_ENABLED`
  is set, the mail timer is active. Telegram: **no bot is configured** (no `AGENTAI_TELEGRAM_*` line in `accounts.env`), so a Telegram channel needs a bot (question 3).
  Browser push: nothing exists.
- **Latency reference for exit gate 4** (`deploy/latency_report.py --last 60 --summary`, read only):

  | | requests | wait for a turn (accepted to claimed) | accepted to finished |
  |---|---|---|---|
  | warm | 52 | median 0.55 s, 90th percentile 0.87 s | median 40 s, 90th percentile 76 s |
  | cold (cell started) | 8 | median 19.8 s (cell start about 82 s) | median 166 s, 90th percentile 437 s |

  Phase 0's reference was a warm wait of 1.5 s and 103 s to finish. Background work in Phase 7 must not raise the warm wait above this.

## Audit (one line per feature; label from the inventory)

| # | Feature | Label right? | Exists (code) | Missing |
|---|---|---|---|---|
| 80 | Notification preferences | M: yes | Nothing (no per-person preferences, quiet hours or digests) | Preferences per person and kind, quiet hours with timezone, immediate or digest, an urgent override, a settings card |
| 81 | Reminders and notifications | M: yes | Three separate senders, no shared outbox: the push stream (`live/push.py` `PushGateway`), account mail (`accounts/delivery.py`, `agentai-platform-mail` timer), `telegram_outbox` with receipts (`telegram.py`) | One outbox (kind, account, person, urgency, dedup key, attempts, receipts), a channel adapter per kind, an unsubscribe per kind, the "subject only" content rule |
| 70 | Project boards | P: yes | Asana in the MCP directory (`mcp_connections/directory.py`, official remote server); a refused tool is dropped per tool with its reason logged (`mcp_connections/service.py` `schema_problems`, `log_schema_rejection`) | The common task model; a board connector on the Phase 3 contract; a live connect to see whether Asana's tools now pass; GitHub Issues as the second board (owner, 2026-11-20) |
| 71 | Task creation and assignment | M: yes | The action pipeline (`actions.py`) | The board write kind (preview, once, verify, undo); link to a commitment both ways |
| 72 | Deadline tracking | M: yes | Commitments carry `due_on` and `zone` (`commitments.py`) | Board due dates with timezone and the date-only rule, change history from sync, reminders through #81 |
| 73 | Milestones | M: yes | Nothing | Milestone = a group of tasks with a date and a computed state; provider milestones or sections where they exist |
| 74 | Blocker detection | M: yes | Nothing | Derived blockers with their cause (prerequisite, overdue, stale, failed run, waiting approval, connection needing the customer) |
| 75 | Status reporting | M: yes | The render service (`render/`), citations from Phase 4 and 5 | The report workflow; a fixture board for the exact-match evaluation |
| 76 | Webhook processing | M: yes | Webhooks only for single integrations: Stripe (`accounts/billing.py` `webhook`), Telegram (`accounts/telegram.py` `webhook`, secret header); secret rotation (`ops/rotation.py` `add_webhook_secret`); the push gateway as the model of a small service; `HubCaps.push` is False for every provider; hub sync is timer-only (`hub_sync.py`) | The `/v1/hooks/<id>` ingress as its own service (signing, replay, limits, queue, event log), a Caddy route, provider push (Gmail through Pub/Sub, Calendar watch channels; Microsoft change notifications after gate 8) |
| 77 | Event-triggered automation | M: yes | Durable objectives (`durable.py`), background slots (Phase 1), the action pipeline | Trigger model (source, filter, workflow, limits, approval rule), loop protection, self-pause, the Triggers page |
| 78 | Scheduled execution | P: yes | `schedules.py` (`ScheduleService.create`, `due`: daily at a local time only; `ENFORCEMENT_PROVEN = True`); `schedule_engine.py` `ScheduleEngine.tick`, run by the request worker behind `customer_schedules`; `schedule_runs` table; proven in Phase 1 | Weekdays, weekly, monthly, a date, every N hours, the clock-change rule; a missed-run rule per schedule; the Schedules page; `/v1/schedules` is still `v.disabled` (`accounts/urls.py`); the switch lock; the morning brief (reuses `KnowledgeTools._meeting_brief`, #58) |
| 79 | Change monitoring | P: yes | `watchers.py` (`ensure`, `observe` with a caller-supplied hash, `mark_delivered`), `watcher_notifications` table | Check kinds (page through the destination guard, file, search, board, calendar, mailbox filter), the "what changed" run, noise controls |
| 82 | Follow-up tracking | M: yes | `commitments.py` `CommitmentService` (record, change, list; live since Phase 4) | A check and an action on a commitment, closing by itself on a reply or a finished task |

## Build order (from the prompt) and the pull requests planned

1. #80 and #81: the outbox, the channel adapters, preferences (one PR). Exercise the reusable delivery contract with a fake channel and canonical links. The iOS phase will add its own device delivery adapter.
2. #70 to #75: boards read with the task model, then the write kind with deadlines, milestones, blockers and the report (two PRs).
3. #76 and #77: the ingress service and triggers, then provider push for Google (two PRs; Microsoft's push after gate 8).
4. #78 and #79: schedules with the switch precondition and the morning brief, then watchers (two PRs).
5. #82: follow-ups (one PR).

Then the exit gate: a **one-week soak** on two accounts (two schedules, a page watcher, a webhook trigger, a follow-up, quiet hours). The phase cannot pass sooner
than seven days after its last part is live. New migrations start at `0055`; the ingress needs a unit file and a Caddy route (`/v1/hooks/`).

## Defaults I will take (not questions)

- Quiet hours: none until the customer sets them; "urgent" by default = an approval that expires within an hour, or a failed run the customer must act on.
- Delivery per kind: immediate for approvals and failures, a daily digest for watcher changes and status reports; the morning brief off until the customer turns it on.
- Notification email content: the subject and a link back, never the item's body.
- Webhook event bodies kept 30 days (like activity records), then deleted by the retention sweep.

## Questions for the owner (one batch, before building; recommended default each)

1. **Order.** Start Phase 7 while Phase 6 exit gate 8 waits for the owner's Microsoft test run? Recommended: **yes**; Microsoft's change notifications (#76) are added when gate 8 passes.
2. **Rollout.** Turn each Phase 7 switch (`customer_schedules` and the new ones) on for every account once its live proof passed and the policy is published, as in
   Phase 6? Recommended: **yes**.
3. **Channels.** In-app and email are ready. Telegram needs a bot (BotFather: token, webhook secret, username). Browser push sends through the browser makers' push
   services (a new outside recipient, payloads encrypted). Recommended: **in-app and email now; Telegram only if you create a bot; browser push later.**
4. **Gmail push.** Needs a Pub/Sub topic in Lumina's Google Cloud project (enable the Pub/Sub API, create a topic, give `gmail-api-push@system.gserviceaccount.com`
   the Publisher role on it, a push subscription to the address I give once the ingress exists). A notice carries no mail content. Recommended: **yes**.
5. **Test accounts for boards and the soak.** An Asana workspace with a test project (you sign in when I connect it), a private GitHub repository for Issues and its
   webhooks (the real signed sender for #76 and #77), and the two Google test accounts from Phase 5 for the soak. Recommended: **yes, these.**
6. **Budget.** The Phase 6-7 budget is $25. Recommended: **up to $10 of it for Phase 7** (proofs and the week of schedules; an idle week should cost close to nothing).

The policy text for notifications, webhook events, board data, schedules and triggers is prepared with the pull requests and shown to you as a diff before it is
published (as for PRs #74 and #81).

## Known before starting

- The report-only CI part `browse` fails on every pull request (PR #82, PR #84): `ci/run.sh browse` runs `node --test test/`, and the Node in CI treats `test/`
  as a file ("Cannot find module .../browse/test"). Use `node --test 'test/*.test.mjs'`. It blocks nothing today, but the browser tests are not being run in CI.

## Repository housekeeping (waiting for the owner's go-ahead; not needed to start)

- 77 local branches already merged into `main` can be deleted; 12 worktree records point at folders that no longer exist (`git worktree prune`); the worktrees
  `.claude/worktrees/fastclick` and `live-view` hold only `node_modules`; `worktree-product-images` is a local-only branch whose work is in `main` (`accounts/media.py` `card_image`).
- Pull requests #29 (styles for `ToolApproval.tsx`, which `work/Permission.tsx` replaced) and #15 (the old handoff) can be closed.
- Two pieces of work never reached `main`, for the owner to keep or drop: `own-model-switch` (PR #31, switch between your own model and Lumina's without removing
  the key) and the local-only branch `native-ui-tools` (`lumina_ui_describe`, `lumina_ui_compose`).
