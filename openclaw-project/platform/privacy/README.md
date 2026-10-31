# Keeping the privacy policy true

The public policy is `deploy/vercel/public/privacy.html` (served at `https://getlumina.pro/privacy` by the Vercel project in `deploy/vercel/`, no sign-in needed).
It makes promises about what Lumina and the Chrome extension collect, who receives it and how long it is kept. A promise that stops being true is worse than no promise,
so the policy is wired to the code and to the server:

| Piece | What it is |
|---|---|
| `facts.json` | The **reviewed record**: the facts the policy rests on, the date it was last reviewed, a log of reviews. Edited by a person, never generated. |
| `derive.py` | Reads the same facts **out of the code** (retention constants, extension permissions and storage, every host our code names, the database columns). `python3 platform/privacy/derive.py` shows them. |
| `tests/test_privacy_policy.py` | Fails when the code and the record disagree, when the policy stops saying what the record says it must, when it says something it must not, or when it has not been reviewed for 200 days. |
| `check_server.py` | Reads the **live server** over SSH (read-only) and checks what config outside the repo promises: log retention, the backup timer, backup ages, features that are off. |
| `bin/push-release.py` | Runs the policy test before every release. `--skip-privacy-check` exists for emergencies and prints a warning. |

## When `test_privacy_policy` fails

The failure text says which fact moved. Do this, in order:

1. **Read what changed** (the test prints the code's value next to the recorded one).
2. **Decide: does the policy still tell the truth?**
   - A longer or shorter retention time, a new kind of data, a new company that receives customer data, a new extension permission, or the extension reaching a new server: **the policy must change** (`privacy.html`), and so may the table of who receives what.
   - A change that does not touch what customers are told (a column that holds no personal data, a renamed internal host): no wording change.
3. **Update `facts.json`** (the matching value, `policy_updated`, and a line in `review_log` saying what you decided and why) and `privacy.html` in the same change. The test passes only when both agree.
4. **Publish the page** (see below). A policy that is only in the repo protects nobody.

Never "fix" a failing test by editing `facts.json` alone: that makes the test pass while the published promise is wrong.

## Things no test can see: update the policy FIRST

These are switched on in server settings, not in code, so nothing in the repo changes when you flip them. Before you do, add them to the policy (and to `facts.json`):

- **Telegram linking** (`AGENTAI_TELEGRAM_BOT_USERNAME`): a new recipient and new data. Currently off; the policy says nothing about it.
- **File uploads** (`AGENTAI_UPLOADS_ENABLED=1`): customer files stored on our server. Currently off.
- **Google connectors** (switch `connectors_linking`): Gmail, Calendar and Drive access. Currently off.
- **Charging money** (Stripe live keys, `open_access` off): the policy already names Stripe as "if we start charging", but check the wording again.
- **A new model provider** in `/opt/openclaw-production/config/litellm.yaml` (today every model is `anthropic/*`): a new recipient of chat content. `check_server.py` now checks this.
- **A new tool for the assistant**: another search provider, a plugin, an outside MCP server, a connector, file uploads. The code-side ones (`@openclaw/...` plugins, the search provider, MCP servers, DNS servers in `lifecycle/cell_config.py`) fail the test; anything switched on in a cell by hand or in server config does not. Rule: the policy lists everything the assistant can send data to, and the section "Connecting other services and tools" is the promise that a new one is announced before it exists.
- **Moving servers, a new host, a new email provider, a new analytics or logging tool.**
- **Changing log retention** (`MaxRetentionSec` in `/etc/systemd/journald.conf`, today 7 days).
- **Scheduling the retention job** (`accounts/management/commands/retention_accounts.py`): it exists but nothing runs it. If you schedule it, the policy's last table row can promise real limits (events 30 days, audit and email records 180 days, chat timelines 90 days). `check_server.py` warns when it is scheduled and the record says it is not.

`python3 platform/privacy/check_server.py` checks the server-side items above and exits 1 if a promise in the policy is not true right now. Run it after any server change.

## Publishing the page

The page is a static file in the Vercel project (`deploy/vercel/`; `build.mjs` copies it and routes `/privacy` to it before the server rewrites). Push the repository as the Vercel README describes; Vercel rebuilds. `node deploy/vercel/check.mjs` verifies the route. Publish the policy **together with** the features it describes: it already talks about the browser icon at the top of every chat and Settings → Your browser, which exist in the code but must be deployed first (or at the same time).

The extension's store listing needs this URL as its privacy policy URL: `https://getlumina.pro/privacy`.

**Published 2026-10-31** with a prebuilt CLI deploy (`vercel deploy --prebuilt --prod` of the build output of `deploy/vercel`, project `agentai-vercel`), not through Git. The production alias therefore points at a deployment that is not tied to a commit. **Until `privacy.html`, `build.mjs` and `check.mjs` are committed and merged to the branch Vercel builds for production, the next Git-based production deploy will remove `/privacy`.** Current production deployment: `dpl_45fb7R4i7mYxmV3HQmCj7vCa6BVt` (the corrected policy). Roll back with `vercel rollback dpl_EQQqt89GP3DsnSdE4n2kYCWpjyq1` (first draft of the policy) or `vercel rollback dpl_3H9wwD4aEmrFTncKcede8BPhigYc` (2026-10-12, before `/privacy` existed).

## Open items (2026-10-31)

- **Deadline 2026-11-11, fix deployed 2026-10-31 but not yet seen working.** The policy says copies of the database made before software updates are removed within 30 days. The cleanup (`ops/housekeeping.py`, run by the nightly backup) never matched the real file names, so nothing was removed. The fix shipped on 2026-10-31 (release `20261031T204618Z-f789bf2`); a dry run on the server showed it keeps the newest 3 and would remove 35 copies and 70 side files. **After the nightly backup at 03:40 UTC on 2026-11-01**, run `python3 platform/privacy/check_server.py` (expect 3 copies left, no warning) and then delete `server.known_gap` from `facts.json`. `test_a_known_gap_cannot_outlive_its_deadline` fails on 2026-11-11 if that has not been done.
- **Retention job unscheduled** (see above). The policy says "kept until you ask us to delete them" because that is what happens today.
- **Deleting an account is manual.** The policy promises an answer within 30 days to an emailed request. There is no self-service deletion yet.
