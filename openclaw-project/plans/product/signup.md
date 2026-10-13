# Self-service sign-up with owner approval

Decision (owner, 2026-10-13): people create their own account with an email; nothing works for them until the owner approves it. Built so launch is one switch.

## What a person sees
1. Sign-in page shows **Create an account** (only while the owner switch `open_signups` is on). Email + password (12+ characters, common-password check).
2. They get an email with a link that works for 15 minutes. Opening it confirms the email; the page says the account is waiting for approval.
3. Signing in before approval says "waiting for approval" (only after the correct password); a declined person is told it was not approved.
4. When the owner approves, they get an email and can sign in; their assistant is created and the allowance is applied.

## What the owner does (private dashboard, Customers page)
- **Waiting for your approval**: Approve / Decline per person (email and date only; no content is ever shown).
- **All customers**: Suspend (signs them out immediately) / Resume.
- **Customer limit**: how many assistants this server may carry (default 2; raise it as capacity allows). Approval is refused with a clear message when the limit is reached.
- **Feature switches → "Let people create an account"**: ON opens sign-ups, OFF closes them (existing customers are unaffected). It is OFF now; turning it on is the launch step for sign-ups.
- A new confirmed sign-up also emails the owner (the sender address).

## Protections
Same answer for new and existing addresses (no account enumeration); 5 sign-ups per hour per source and 3 per day per address; honeypot field; at most 200 waiting sign-ups; unconfirmed sign-ups are deleted after 24 hours; the account row stays `suspended` and nothing exists in the assistant runtime until approval; every step is audited; the dashboard only passes fixed actions and validated ids to the host command.

## Technical map
`accounts/signup.py` (public routes), `accounts/management/commands/signup_admin.py` (list/approve/decline/suspend/resume/limit, host-only), `migrations/0021_signups.sql` + Django `0013_signup_token` (allows the `signup` token purpose), `agentai_platform/lifecycle/capacity.py` (customer limit file `/var/lib/agentai-platform/signup-settings.json`; coordinator uses it instead of the fixed 2), dashboard `/customers`, Lumina `Login.tsx`, `deploy/signup_live_check.py` (live check, approval not exercised because it would create a real assistant).

## Verified
Offline: sign-up → confirm → wait → approve (real coordinator queues a create) → sign in; decline; suspend/resume; limit; enumeration; rate limits; expiry. Live on the server (temporary switch file, mail captured in memory): all 14 steps passed, then cleaned up. SMTP sends from the server (one test email to the owner's address). Not exercised live: a real approval that builds an assistant cell.

## Notes
- The release containing this schema cannot be rolled back to an older binary (new table and trigger); a database backup was taken before the migration.
- Billing: while `open_access` is on, approved accounts get their allowance from the billing worker; in invite-only mode approval seeds the $1 7-day trial; with `billing_checkout` on they must subscribe.

## Owner console (one-click switching between owner views)
`python3 openclaw-project/bin/owner-console.py` (or double-click `bin/Owner Console.command`) opens one SSH tunnel and a private launcher page at `http://127.0.0.1:18790/` with a button for Customers, Feature switches, Overview, Live, Costs, Audit, Routing, the OpenClaw Control UI, the Lumina app and Stripe test mode, plus status lights and a "Copy dashboard password" button (clipboard only, never shown). Every port is loopback-only; the dashboard header has an "Owner console" link back to it. `--stop` closes the tunnel.

## Owner dashboard redesign (2026-10-13)
The private dashboard now opens on a product **Overview**: status line ("Everything is running" / "2 things need you"), things needing attention (waiting sign-ups, a service down, backups only on the server), four numbers (customers, tasks this week, spend, assistants awake), a launch checklist, top usage, service lights and every feature as a card with an on/off button. Left menu: Overview, Customers (with a waiting badge), Features, Money, Live, Audit log, and an Advanced group (the older runtime views, plus "System details" which is the previous overview). Customers shows approve/decline cards, a customer limit box and a searchable list. Features groups every switch in plain words with its confirmations and what is missing. Light and dark themes, phone layout, a link back to the Owner console. Data comes from `manage.py signup_admin overview` (counts, queue, spend; never content). Server backups of the old files: `*.bak-redesign`.
