# Launch readiness (Lumina, getlumina.pro)

Status as of 2026-11-19. Production runs `main` (deployed by `.github/workflows/deploy.yml`; the server's `/var/lib/agentai-deploy/last` is the commit). Merge to `main` deploys the website through Vercel.

## Done and live
Sign-in and accounts, isolated per-customer assistants, chat with history, plans and forms, data cards, web search, files, Activity window, browser tasks (switch ON), JEV routing (switch ON, record-only), serial task queue, budget caps ($79/mo, $25 included, $5 task cap, 7-day $1 trial, no auto overage), nightly backups on the server, monitor every 5 minutes.

## Owner items before real customers (state on 2026-11-15)
Each needs an account, a credential or a decision only the owner has. What the code and the server can do is done; what is left is written as the exact step.

| # | Item | State | What is left, and who |
|---|---|---|---|
| 1 | Publish the website | Done: merging to `main` publishes it (Vercel). | Nothing. |
| 2 | **SSH key-only login** | **Done 2026-11-15.** `/etc/ssh/sshd_config.d/10-lumina-hardening.conf` (`PasswordAuthentication no`, `PermitRootLogin prohibit-password`); checked: a key login works, a password login is refused. | Owner: the root password printed in an old session transcript is still the account's password (it can no longer be used over SSH). Change it from the provider's console with `passwd root` so a console login is not open to it either. |
| 3 | **Off-server backup copy** | Not done: needs a place to copy to. Backups (nightly, encrypted, `agentai-ops-backup.timer`) live only on this server. `ops/destinations.py` `CommandDestination` takes any copier (rclone, scp) by configuration. | Owner: create a bucket or a second machine and give the access key; then set the destination in `/etc/agentai-ops/config.json` (see `platform/OPERATIONS.md` section 2). The monitor says "NO off-server copy" until a copy lands. |
| 4 | **Stripe** | Not done: needs the owner's Stripe account. Billing is built and tested in test mode. | Owner: create the account and products, give the keys, then turn on `billing_checkout`; run one real payment and one refund. |
| 5 | **Legal pages** | The privacy policy exists and is kept true by `privacy/` (see its README). Terms and refund policy are not written. | Owner: provide or approve the text; the app already links to the pages. |
| 6 | **Search key** | Every assistant uses the owner's Brave key. | Owner: create a dedicated key with a spend alert and put it in the search key file (`platform/deploy/accounts.env.example`). |
| 7 | **Google (Mail and Calendar)** | **Live since 2026-11-16, read only, switch `mail_calendar_dashboard` ON for every account; the policy describing the copy was published on 2026-11-19.** Proven live with two real Google accounts at once on 2026-11-20 (`deploy/phase5_live.py`, all 9 checks, the assistant panel answering about an open thread included). GitHub and Drive connectors: built, off. | Owner: (a) done; (b) a sign-in client of a Lumina Google project (today's client belongs to ManagerAI, whose name the consent screen shows); (c) Google's verification for the restricted `gmail.readonly` scope: OAuth verification plus a CASA security assessment, renewed yearly, which takes weeks; until then only listed test users can connect. |
| 8 | **Support** | Not set up. | Owner: a support email address and who answers it. |

## The launch line: roadmap Phase 4 and 5 (state on 2026-11-19)

| Part | State | Before real customers |
|---|---|---|
| Mail and Calendar (#D1-#D5, #49-#58) | Live: one inbox and one calendar across accounts, search, the assistant beside them with citations that select the thread or event, drafts kept in Lumina (Copy, Open in your mail service), the meeting brief, attachments read into the knowledge index. The Inbox's first call takes 46 ms on the server (was 294 ms: one app worker held to a quarter of a CPU, and an unindexed badge count) | Item 7 (b) and (c) |
| Customer knowledge (#30-#48) | **Live 2026-11-19, on for every account** (`customer_uploads`, `customer_knowledge`): installed on the host, all four exit gates passed live (`deploy/phase45_live.py`), the policy published | Nothing |
| Managing mail and events (send, archive, create, answer) | Not built: Phase 6 | Launch read-only and say managing comes next, or wait for Phase 6 |
| Microsoft (Outlook) | Not built: Phase 6 (#D8) | Microsoft's app registration and publisher verification take calendar time: start them now |

## Phase 15 status
Partial (21 live cases PASS, 2 BLOCKED, 7 NOT_RUN): see `plans/product/phase-15.md`. Blocked/not-run items need the owner: a second cell (operator enrollment), the off-server backup key for the restore drill, and an independent review.

## Needs a "go" from the owner
- Phase 17 invite-only beta (2 trial accounts), then launch review.
- Browse benchmark with paid runs (tens of dollars) before JEV is allowed to choose actions.

## Not built yet (decide whether launch needs them)
Guarded ordering/payments by the browser agent (locked `credentialed_browsing`), browser hardening pass (injection tests, capacity test), live code/file preview workspace.

## Rollback
Switch the feature off in the owner switches (`browse_tasks`, `customer_execution`, `open_access`); app release rollback is `release.py` previous release (binary rollback compatible).

## Sign-ups (ready; owner switch OFF)
Self-service sign-up with your approval is built and live behind the `open_signups` switch (Feature switches page). To open the door: turn it on, then approve people in the dashboard Customers page. Details: `plans/product/signup.md`. Set the customer limit to what the server can carry.

## Deferred features
What was left out of launch was written in the removed `phase-prompts/openclaw/final_phase.md` (items F1–F13); `git show HEAD:phase-prompts/openclaw/final_phase.md` still reads it, and the capability roadmap now covers the remaining work.
