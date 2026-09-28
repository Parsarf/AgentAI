# Phase 10 run summary — 20260927T221952Z

**Gate 10: NOT PASSED (partial run, zero failures).** 13 cases passed
(+2 reused live proofs from Phase 1), 8 blocked on the enforced budget
window, 4 blocked on pre-known external prerequisites, 7 await owner
participation, 1 awaits the scheduled 03:17 UTC backup fire. No case failed;
no thresholds were moved; nothing skipped was counted as passed.

## What was proven today

- **Security**: dashboard auth/lockout, CSRF, four traversal forms, symlink
  refusal, download tamper/expiry, session revocation, redaction, disabled
  controls — all with runtime denial evidence. Live budget admission denial
  (tiny temp key → 429 → deleted → revocation 404).
- **Recovery**: restore drill executes end-to-end after a real defect fix
  (root-owned staging); corrupt archives reject safely; isolated clone
  staged with channels/schedules/delivery-off procedure; live state never
  touched; freshness reporting OK.
- **Behavior**: trivial deterministic request answers directly with no
  worker spawn.
- **Two defects found and fixed with re-run proof** (ops-restore staging
  ownership; dashboard Files root listing).

## Why it stopped

The LiteLLM key's enforced 24h window hit its $2 ceiling mid-orchestration
(429 at $1.9434/$2.00, bounded retries, then stop — the ceiling doing its
job). Paid resume condition: window frees as prior-phase spend ages out
(hours) or the owner temporarily raises the cap.

## To finish Gate 10

1. After the window frees: research+citations, injection-no-effect (page +
   serve procedure staged), memory recall/correction/deletion, durable
   resume/cancellation, scheduling admission, browser flows, integration
   fail-closed — ~$1.50–2.50 total, next window(s).
2. Observe the scheduled backup fire (03:17 UTC) + record RPO/RTO, run the
   rollback drill in the isolated target.
3. Owner participation (5–10 min): Telegram owner reply; non-owner denial
   from a second account; one approval-card grant/deny; Control UI sign-in
   via `bin/open-control-ui.py`.
4. Pre-known externals: ChatGPT quota for the native build browser proof;
   reviewer route admission for the independent review.

Sanitized per-case table: `evals/RESULTS.md`. No secrets in evidence; probe
cleanup verified.
