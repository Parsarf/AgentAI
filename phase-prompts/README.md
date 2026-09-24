# Phase prompts — multi-user agent build

Ready-to-paste build prompts, one per phase, generated from
`agent-build-spec-multiuser.md`. Give them to an AI coding agent **one at a
time, in order**. Each prompt is self-contained: it carries the shared
project context, the phase's file-by-file specs, exact interfaces, the
tests to write, and the acceptance checklist.

## How to run a phase

1. Do the operator setup (spec Part 0a items) listed in that phase's
   **Prerequisites** section, and put the new keys into `.env`.
2. Open a **fresh** AI coding session in this repo's root directory.
3. Paste the **entire** phase file. Nothing else is needed.
4. When the AI reports done, work through the phase's **"Phase done when"**
   checklist yourself before starting the next phase.
5. Skim `BUILD_NOTES.md` — the AI appends its decisions there every session.

If a session dies partway through a phase, paste the same phase file again:
every prompt instructs the AI to inventory existing work and continue, not
restart.

## Order and prerequisites

| # | File | Turns the system into | Needs from Part 0a |
|---|------|----------------------|--------------------|
| 1 | `phase-1-foundation.md` | Accounts + provably tenant-isolated data layer | #1–5 (Anthropic, Telegram bot, domain/host, TLS, email) |
| 2 | `phase-2-core-loop.md` | Usable multi-user product (chat, research, code, memory) | #6–7 (Docker host, search API) |
| 3 | `phase-3-autonomy.md` | Per-user scheduled jobs, watchers, skill library | — |
| 4 | `phase-4-browser-vault.md` | Login-gated browsing with per-user encrypted secrets | #8 (KMS), optional #10 |
| 5 | `phase-5-lean-billing.md` | Accurate usage metering, hard caps, flat Stripe subscriptions | #9 (Stripe) |
| 6 | `phase-6-lean-payments.md` | Opt-in spending through a verified user-funded provider | Supported provider connection |
| 7 | `phase-7-lean-tests-ops.md` | Tenant and safety tests, backups, single-process compose stack | — |

Do not reorder. The spec requires Phase 5 (plan gating) and Phase 2's
proven approval system to both exist before Phase 6 puts money on the line.

## Why every prompt repeats the same warnings

Each AI session starts with zero memory. Every phase prompt therefore
re-states, in full: the multi-tenancy model, the two-modes safety model,
the two-kinds-of-money split, and the coding conventions. That repetition
is deliberate — those are the four rules whose violation turns a bug into
an incident (leaked user data, spent money, burned API budget).
