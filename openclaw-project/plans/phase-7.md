# Phase 7 — operations build plan (2026-09-27)

Owner direction: build Phase 7 only, nothing extra. Earlier gates remain
unpassed (deferred to Phase 10); this phase closes implementation gaps and
prepares — but does not run — acceptance.

## Objective

Maintainable operations/recovery on the existing VPS, a runnable-but-unexecuted
evaluation harness, and an honest inventory of what remains.

## Scope decisions

- OpenClaw stays the sole runtime. No legacy Python rebuild, no new accounts,
  no model/paid calls, no destructive jobs enabled.
- Backup path = **native** `openclaw backup create --verify` (consistency-aware
  SQLite online snapshots per docs.openclaw.ai/cli/backup) **plus** a nightly
  `pg_dump` of the LiteLLM database, because spend history and virtual-key
  identity live there and recovery must not silently reset budget caps.
- Schedule = **host systemd timer**, separate from agent authority (agent cron
  jobs untouched; the 4 existing skill-review jobs are preserved). No model
  calls, no outbound notifications from the timer.
- Retention = bounded, our own `ops-` prefixed artifacts only (14 daily),
  historical `phase*` archives always preserved.
- Restore/rollback = isolated entry points + runbook; a clone must disable
  channel polling, delivery, schedules and queued effects, and never
  overwrite live state. The actual drill executes in Phase 10.
- Off-host encrypted retention: **pending** — no approved destination or
  key-custody mechanism exists. Prepared instructions only; no new paid
  storage account.
- RPO 24 h / RTO 30 min recorded as proposed initial targets (owner has not
  chosen others).

## Deliverables

1. `plans/remaining-build-items.md` — gap inventory with statuses + test IDs.
2. `bin/ops-*.sh` on the VPS (`/opt/openclaw-production/bin/`):
   `ops-backup.sh` (exit-code + verification + bounded retention),
   `ops-status.sh` (freshness: OK/STALE/ERROR, local report only),
   `ops-restore.sh` (verify → restore to fresh target → sanitize clone →
   print activation steps; `--start` required for any boot attempt).
3. `openclaw-ops-backup.timer/.service` systemd units (daily 03:17 UTC,
   Persistent).
4. `evals/` — `README.md`, `cases.yaml` (all deferred-gate cases, full field
   set), `run.py` (list/validate/show only in this phase; paid execution
   refused without explicit enablement).
5. Runbook + architecture updates, `evidence/phase-7/<run-id>/`, build-log
   entry.

## Lightweight checks (this phase)

`bash -n`, `python3 -m py_compile`, YAML/JSON parsing, systemd unit
enablement + next-fire readback, one bounded initial native backup with
`--verify` (free safeguard, not restoration proof), `ops-status.sh` truthful
output, gateway health. No doctor migration run (state-touching — deferred;
recorded). Acceptance: **DEFERRED to Phase 10.**

## Rollback

Delete `/opt/openclaw-production/bin/ops-*.sh`, `systemctl disable --now
openclaw-ops-backup.timer` + remove units, delete `backups/ops/` and
`restore-drill/` (our artifacts only). No OpenClaw config or agent state is
modified by this phase.
