# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Everyday people delegating tasks: non-technical customers who hand Lumina real jobs (research, browsing the web, forms, files) and come back to check progress. They are not expected to understand agents, models or queues.

## Product Purpose
Lumina is a private AI assistant each customer owns: a chat where they ask for work, then watch it get done (research, browser tasks, files, recurring tasks). Success is that a person can trust it with a task and always know what it is doing and what it needs from them.

## Positioning
- **Honest, observable activity.** The interface shows what the assistant is actually doing (tool use, browsing, terminal output it really reported) and never invents reasoning or simulated progress.
- **A living character.** A mascot whose scene mirrors the real state of the assistant and the task (asleep, waking, planning, working, waiting, blocked, needs you, stopped, completed, failed).

## Operating Context
- Served at `https://getlumina.pro/app/` by the account backend; single-page app, same-origin API under `/v1`, cookie session.
- Chat is the main surface. Around it: Home, Tasks, Live view (watch and take over the browser agent), Files, History, Calendar, Automations, Integrations, Settings.
- Each customer has an isolated assistant workspace that sleeps when idle and wakes when work arrives.
- Customers answer the assistant's questions and approvals in the chat; sensitive input (passwords, payment) stays with the customer.

## Capabilities and Constraints
- `features` from `GET /v1/app` decides which screens and buttons exist (`platform/UI_CONTRACT.md`).
- Product name stays **Lumina**.
- The UI must map real task and workspace state; it never simulates progress on a timer (`lumina/AGENTS.md`).
- Reduce-motion support is required: animations (orbs, film background) have a still-frame fallback.
- Frontend rules: no inline scripts or styles, no CDN, same-origin only (backend CSP).
- Undecided: pricing and billing presentation beyond the `billing_mode` switch.

## Brand Commitments
- Name: Lumina.
- Existing visual and motion commitments (Obsidian palette, the pencil-on-parchment mascot film) are documented in `DESIGN.md` and the film package; they were not confirmed as binding in this interview.

## Evidence on Hand
- Real product behaviour and constraints: `platform/UI_CONTRACT.md`, `platform/CHAT.md`, `lumina/AGENTS.md`.
- Mascot film package: `lumina-environment-v3-clips.zip` (nine state loops, enter and exit clips, six event clips), bundled at `lumina/public/scenes/`.
- No testimonials, customer counts, benchmarks or pricing claims exist in the repository; future work must not fabricate them.

## Product Principles
1. Show the truth: every indicator reflects real state, and errors stay visible.
2. Never make the customer feel lost: always say what the assistant is doing and what it needs from them.
3. Privacy first: sensitive text is masked, never stored client-side, and never shown to the wrong account.
4. Calm for non-experts: plain words, no jargon, nothing that needs configuring to get a first result.
5. The character earns its place by being accurate, not decorative.

## Accessibility & Inclusion
Reduced motion is honoured everywhere; interactive elements are keyboard reachable; decorative media is hidden from assistive technology.
