# Feature switches — turning optional features on and off without code

Open the private ops dashboard (`python3 openclaw-project/bin/open-ops-dashboard.py`), sign in, and choose
**Feature switches**. Each feature is a card in plain English: what it is, what changes when it is on, what it costs,
whether it can be turned on yet, and why not.

## How a switch behaves

- **Turning OFF always works**, immediately, and is read back and written to the audit log.
- **Turning ON works only when** every confirmation is ticked (for example "I read TypeSafe's data terms") and every
  setup step it depends on is really finished. If something is missing the card says exactly what, in words.
- A switch never overrides a safety check. It is the outermost layer: the per-account approvals, budget reservations,
  read-only limits and the isolation boundary still apply underneath.
- **Locked** switches (customer schedules, Claude Code for customers) cannot be turned on here at all until the safety
  proof they depend on exists. Nothing in the UI can unlock them.
- Everything fails closed: if the switch file is missing or unreadable, the feature is off.

## The switches today

| Switch | Today | What has to happen first |
|---|---|---|
| Smarter page reading for research (Jev) | OFF, blocked | confirm the data terms; the component that identifies public pages must be built; a TypeSafe key must exist |
| Smarter browser actions (Jev) | OFF, blocked | confirm data terms and transport review; the optimized browser route must be deployed |
| Customers connect Gmail/Calendar/Drive/GitHub | OFF, blocked | sign-in apps registered; protected token storage; customer notice confirmed |
| Browser saved logins | OFF, blocked | protected storage; secure login screen |
| Customer schedules | LOCKED | Phase 15 safety checks |
| Claude Code for customers | LOCKED | isolated workspaces and a metered key |

"Blocked" cards show a **Before it can be turned on** list. When setup work finishes, the deployment tooling marks the
matching fact true in `feature-switches/facts.json`; the owner never edits that file by hand.

## Where it lives

- Code: `platform/agentai_platform/switches.py` (one file, standard library only; the dashboard ships a copy).
- State: `/opt/openclaw-production/feature-switches/switches.json` (on/off, who, when, confirmations — no secrets) and
  `facts.json` (set by deployment tooling).
- The customer app reads the same file through `AGENTAI_SWITCHES_FILE` (and `AGENTAI_SWITCH_FACTS_FILE`) with read-only
  access. Unset means everything off.
- The research plugin keeps its own `jev-research/config.json`; the switch writes it and reads it back, and the page flags
  any disagreement ("plugin file says ON but the switch is OFF") with a one-click **Turn it off everywhere**.

## Installing this update (one command, backs up first)

`python3 openclaw-project/bin/update-ops-dashboard.py` shows the plan; add `--apply` to run it. It backs up the dashboard,
copies two files, creates the switches folder with empty facts, restarts only the dashboard and checks the sign-in page.
Rollback is printed if any step fails.

## Not covered yet (needs a follow-up, not code changes by you)

- Per-customer approvals for the optimization tracks (data-handling, transport review, account reference) are still
  recorded by an operator tool, not this page, because the customer database is separate from the dashboard.
- Telegram, schedules for the owner, and native OpenClaw settings (sandbox browser) keep their existing controls.
