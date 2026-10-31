# Automatic customer cells — deployed 31 October 2026

Owner authorization: “deploy”. Source commit: `fae3c938c1b5ef96dc6f7c13a4e5632182f3fd50`.
Release: `20261031T190301Z-automatic-cells-fae3c93`.

## Deployed scope

Both `/opt/agentai-platform/current` and `/opt/agentai-supervisor/current` now
point to this release. Each was based on its previous production tree, with
only the 11 committed cell-automation paths overlaid and SHA-256 verified.
Unrelated local UI/browser changes were not included. Both previous releases
were `20261030T094705Z-e20a9e6` and remain available.

The supervisor has an active `automatic-enrollment.conf` systemd drop-in and
root-owned `/etc/agentai-supervisor/enrollment-policy.json` (0600). Its image
is the existing verified digest
`62832668e3e5e139f745f7d3df892c9251eb53318b7d14a76c410dde1f25d730`.
Its profile matches the approval command (`trial-unmeasured-v1`); the existing
measured-profile cell was preserved. The host enrollment ceiling matches the
existing customer limit of two; no execution-concurrency increase was made.

The existing production idle setting was retained. A local sleep test requires
45 minutes, while production's constant is 15 minutes; the six-test sleep module
was excluded from staged Linux validation rather than changing deployed policy.

## Validation

- Staged Linux lifecycle/enrollment/bridge/request checks: 113 passed,
  including the Linux authenticated peer/socket cases.
- Staged Django signup/account checks against a disposable database: 38 passed.
  No real invitation or customer message was sent.
- The regular `deploy/release.py` process built hash-pinned dependencies,
  migrated a database COPY, passed the new-release canary, and passed the
  previous-release compatibility canary before the live switch.
- App database backup and supervisor-custody snapshot were retained before
  applying. No SQL migration was added; live migration/readiness checks passed.
- All patched files in both deployed trees matched the committed source hashes.
- App, supervisor, lifecycle worker, request worker and cell bridge were active
  with zero automatic restarts at the final check.
- The supervisor process includes `--enrollment-policy`; its authenticated
  app-user Unix socket accepts the fixed create capability check.
- Public `/app/` returned 200 and anonymous `/v1/me` returned 401. Loopback
  health/readiness probes passed. No unresolved lifecycle effects were present.
- Inspection of the existing cell confirmed `runsc`, no privileged mode, no
  host PID/network namespace, and no mounted Docker socket. Live nftables
  rules contain the host-service and private-network blocking rules.

No paid model call, real approval/new-cell provisioning, or two-live-cell
adversarial isolation exercise was run. The last two remain acceptance limits;
this release does not certify absence of all possible data leaks.

## Rollback and evidence

The server retains the previous links, database snapshots, configuration
backups, source manifest and JSON smoke evidence under:

`/root/20261031T190301Z-automatic-cells-fae3c93/`

Prepared rollback command (not executed):

```sh
python3 /root/20261031T190301Z-automatic-cells-fae3c93/rollback/rollback.py
```

It restores the previous application/supervisor releases and configuration,
then restarts services. It preserves current application data and host custody,
including any new bindings created after deployment. Application release
canary results are also recorded in `/var/lib/agentai-ops/releases.log`.
