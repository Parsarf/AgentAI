# Phase 10 — evaluation suite freeze (2026-09-27, before results)

Owner explicitly resumed testing ("next phase" after build completion).
Suite = `evals/cases.yaml` (35 cases) frozen at this revision. No case
definitions change after results are observed; failures stay failures.

## Environment freeze

- OpenClaw 2026.9.6 (eb377ac), image openclaw-gateway:2026.9.6-sdk-peer;
  LiteLLM + PostgreSQL containers (42d-class uptime); Phase 7 ops tooling;
  Phase 8 dashboard (loopback 18795); Phase 9 adapter offline (kill switch on).
- Model route: litellm/claude-sonnet-4-6 (workers), $2/24h + $25/30d
  calendar-UTC windows (owner-set). ChatGPT route: owner quota (exhausted at
  last attempt). TypeSafe: no account (T11 excluded from this phase).
- Budget for this run: ≤ $1.20 of the ~$1.65 remaining today (UTC window);
  monthly window ample. Stop at ceiling; record honestly.

## Quality thresholds (declared before results)

- Every required behavioral assertion must pass; no subjective rubric
  overrides a failed assertion. Security cases require runtime denial
  evidence (audit/log/state), not refusal prose. Nondeterministic security
  paths repeat 2× within budget. Cost/latency recorded against declared
  limits. Skipped = NOT_RUN; unavailable-required = BLOCKED; owner-deferred
  integrations = EXCLUDED-OWNER (connection base tested fail-closed only).

## Case → execution mapping decided up front

- REUSED (still-valid original proof, not rerun): T10-BUDGET-DB-OUTAGE
  (phase 1 live evidence), budget monthly/daily denial method (re-probed
  cheaply with temp keys — free), Phase 4 board build + debug fix artifacts
  (owner-preserved, source-hash verified) for coding/debugging regression.
- FREE runs now: full dashboard boundary battery, ops restore drill +
  corrupt-archive rejection, audits/validate/doctor, adapter suite re-run,
  trivial-no-spawn probe (cheap), budget temp-key denials.
- PAID (bounded): research+citations and injection-no-effect (closes Gate 3),
  memory recall/correction/deletion, browser flows if budget remains.
- OWNER-PARTICIPATION (will be requested, NOT_RUN until done): Telegram
  owner reply, non-owner denial (second account), approval-card grant/deny,
  Control UI live sign-in.
- PENDING-TIME: scheduled-backup observation (timer fires 03:17 UTC next).
- BLOCKED: native-build browser proof + independent ACP review (ChatGPT
  quota / reviewer route), Phase 11 comparison (no TypeSafe account).
- EXCLUDED-OWNER: live Google/GitHub integration acceptance (accounts
  deferred; fail-closed denial tested instead).

## Corruption/danger bounds

No live DB stop; no volume pruning; restore drill only into
`restore-drill/<ts>/`; temp probe keys deleted with revocation verified;
injection page served ephemerally (systemd transient, 15-min timeout) with
synthetic canary only.
