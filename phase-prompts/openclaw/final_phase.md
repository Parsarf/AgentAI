# Final phase — everything deliberately left out of launch

**Stage:** Post-launch build and evaluation. **Dependencies:** Phase 18 launched (items marked *early* may be pulled forward on the owner's say-so).
Written 2026-10-13 so the incomplete features are on record in one place instead of spread across phase notes. Nothing here is required for the baseline launch except where stated. Each item can be started on its own; none authorizes live payments, invitations or paid tests unless the owner says so for that item.

Standing rule (owner, 2026-10-13): **no new task guardrails.** Every item below adds capability or protects privacy and data; none may restrict what customers can ask the assistant to do. Cost caps ($79 plan, $25 included usage, $5 task cap) are budget limits and stay.

## Paste this prompt

Execute only the final phase of the AgentAI customer-platform plan, one item at a time in the order the owner picks. Read `phase-prompts/openclaw/execution-contract.md`, `openclaw-project/plans/product/LAUNCH.md`, `plans/product/privacy.md`, `platform/OPERATIONS.md` and the current phase notes for the item. Resume from actual implementation; preserve working capabilities and unrelated edits. Report implementation readiness separately from acceptance, the checks actually run, cost, unknowns, blockers and rollback.

## Items

### F1 — Off-server backup copy (*early; launch blocker recorded in Phase 14*)
Today encrypted backup sets live on the VPS and are copied to the owner's computer by hand (`bin/pull-backups.py`). Add an automatic encrypted copy to a second location so losing the server does not lose customer data.
- Destination: an S3-compatible bucket (Backblaze B2 / Cloudflare R2) with a bucket-scoped key, or a second server. Owner creates the destination and puts its details in `.env`.
- Keep decryption keys (age) off the server and off the destination; the destination only ever holds ciphertext. Verify each upload by hash, prune by the existing retention (30 days), alert on failure through the existing monitor.
- Done when: a nightly set appears off-server, `ops verify` passes against the remote copy, a restore of one account into an isolated target succeeds from the remote copy alone, and a failed upload raises an alert.

### F2 — Claude Code coding agent for customers
Prepared and not applied (`plans/product/phase-10-claude-code-activation.md`). Blocked because Claude Code calls Anthropic directly and bypasses the metering proxy. Needs proof that it can run through a per-account virtual key (or an equivalent hard cap) before any customer use. Baseline coding already works through the assistant's own write/exec tools.

### F3 — Guarded ordering and saved logins for the browser agent
Browser plan P6 behind the locked `credentialed_browsing` switch: customer logs in by taking over the browser into an encrypted per-customer profile; a clear confirmation of item, merchant and total before any purchase; stop on any total change after confirmation; receipts captured; first real order only on the owner's own account. (Confirmation of a purchase is a payment safeguard, not a task limit.)

### F4 — JEV choosing real actions
Chat routing is currently OFF and browser JEV runs in record-only mode. Run the paired benchmark (browser plan P5 / Phase 16; tens of dollars, owner "go" required), compare agreement and cost against Claude, and only then let JEV choose clicks with Claude as fallback. Privacy: all JEV input stays behind `privacy.scrub`.

### F5 — Telegram linking (Phase 7 wiring)
Real bot, secure numeric account link, attachment wiring after file scanning. Needs a bot token and webhook secret from the owner.

### F6 — Integrations (Phase 11)
Gmail, Calendar, Drive (read-only) and GitHub (selected repos). Needs Google and GitHub OAuth app registrations and a protected token store. Read-only by default; content returned as untrusted data.

### F7 — Customer uploads
Turn on uploads (`AGENTAI_UPLOADS_ENABLED`) once a malware/content scan capability exists; quarantine until scanned. Assistant-made files already work.

### F8 — Live preview and workspace
A preview link for websites the assistant builds, an in-app file viewer/editor, and a terminal-style live view beyond the Activity window. Builds on the Files page and artifact store.

### F9 — Automations and schedules
Recurring tasks, triggers and unattended runs (`customer_schedules`, Phase 10 scheduling). Needs the enforcement proof recorded in Phase 10 before creation is allowed. Autonomous resume after a restart is not built (only explicit resume).

### F10 — Capacity beyond one VPS
One customer task runs at a time on one 15.6 GiB host. Add a second host or queue-aware scaling when the waiting list grows; measure memory with browse and chat together.

### F11 — Privacy extras
Anthropic zero-data-retention request, a dedicated Brave search key with spend alert, per-key LiteLLM `allowed_routes` as a second layer behind the relay filter, key-only SSH with a break-glass procedure, and periodic restore drills.

### F12 — Billing beyond test mode
Live Stripe keys, tax and refund terms, invoices to customers, dunning emails, and turning `billing_checkout` on for real customers (owner decision; currently OFF with test keys installed and verified).

### F13 — Customer-funded purchases (Phase 19)
Agent purchases funded by the customer's own provider budget; separate selection, provider and authorization.

## Order the owner may choose
F1 first (it is the only launch blocker), then F11 (privacy), F7 and F8 (they make coding output more useful), F12 when real customers are ready, then the rest by demand.

## Required close-out
For every item finished: update `openclaw-project/plans/product/LAUNCH.md` and `plans/product/privacy.md`, the runbook section, the requirement ledger and BUILD_LOG; store a sanitized evidence manifest under `openclaw-project/evidence/product/final/<UTC-run-id>/`. Stop after the item unless further work is authorized.
