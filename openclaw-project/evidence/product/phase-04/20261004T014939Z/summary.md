# Phase4 native backend slice evidence

Implemented the verified native Fleet backend behind the existing supervisor
boundaries; nothing native can execute until the host operator captures and
verifies real effect-output schemas and wires the backend. Entry point still
ships DisabledDriver; no supervisor, migration, cell, worker, provider call or
owner/VPS change occurred in this run.

Boundary facts: custody manifests reject digest mismatches, symlinks, inherited
environments and unverified schemas; timeout kills the whole executor process
group and requires a proven reaped group; uncertain outcomes never fabricate
receipts; backup archives must be bounded, regular, non-symlink gzip files
under the binding's private root; delete/create reconciliation uses only the
previously probed `fleet list --json` absence form; dispatch-side admission
denies runnable kinds without host RAM headroom before any journal intent and
the coordinator rescinds such denials to pending rather than uncertain.

Checks actually run: 12 new driver/orchestration cases (macOS), 72 core cases
(2 Linux-only skips), 40 account regressions in the platform venv, Vercel
routing checks, py_compile and git diff --check. GitHub workflow extended to
run capacity/foundation/fleet-driver modules; Linux CI result recorded in the
manifest when observed.

Remaining Phase4 blockers: effect-schema capture/verification plus service
wiring, credential custody, stronger runtime/worker broker, disk quotas and
egress, provider admission at dispatch, quarantined restore/pinned upgrade/
rollback/retention, and a measured usable existing-host profile. Phase15
native acceptance remains NOT_RUN. Cost: 0 paid provider calls.
