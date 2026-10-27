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
- **Calm and premium.** A near-black, Apple-inspired workspace with one restrained violet accent.

## Operating Context
- Served at `https://getlumina.pro/app/` by the account backend; single-page app, same-origin API under `/v1`, cookie session.
- Chat is the main surface. Around it: Home, Chat history, Task activity, Live view (watch and take over the browser agent), Files, Calendar, Automations, Integrations, Settings.
- Each customer has an isolated assistant workspace that sleeps when idle and wakes when work arrives.

## Capabilities and Constraints
- `features` from `GET /v1/app` decides which screens and buttons exist (`platform/UI_CONTRACT.md`).
- Product name stays **Lumina**.
- The UI maps real task and workspace state; it never simulates progress on a timer (`AGENTS.md`).
- Reduce-motion support is required: orbs and the planet have a still fallback.
- Frontend rules: no inline scripts or styles, no CDN, same-origin only (backend CSP).

## Brand Commitments
- Name: Lumina; the four-point spark mark and the spaced wordmark.
- Visual world: the dark, Apple-inspired system recorded in `DESIGN.md` (reference image approved by the owner, 25 Oct 2026).

## Product Principles
1. Show the truth: every indicator reflects real state, and errors stay visible.
2. Never make the customer feel lost: always say what the assistant is doing and what it needs from them.
3. Privacy first: sensitive text is masked, never stored client-side, and never shown to the wrong account.
4. Calm for non-experts: plain words, no jargon, nothing that needs configuring to get a first result.
5. Never present anything as a feature that does not exist; sample data is labelled as such.

## Accessibility & Inclusion
Reduced motion is honoured everywhere; every interactive element is keyboard reachable with a visible focus ring; text meets 4.5:1 contrast; decorative media is hidden from assistive technology.
