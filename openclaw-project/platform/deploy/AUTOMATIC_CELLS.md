# Approval creates the cell; a prompt wakes it

The intended flow is:

1. The owner approves an email-verified signup. Account activation, initial
   entitlement, project and queued cell creation commit together. If creation
   cannot be queued, approval rolls back and can be retried.
2. The lifecycle worker sends the create claim to the host supervisor.
3. With an enrollment policy enabled, the supervisor allocates distinct host
   ports and enrolls the binding automatically. Its fixed policy chooses the
   pinned image, profile, resource caps and backup root. Creation uses the
   existing journaled Fleet backend, capped volume and per-cell credentials.
4. The created cell stays stopped until its account has a waiting prompt.
   The lifecycle worker queues a start; the request worker claims the prompt
   only while the account owns the active lifecycle slot.
5. Idle sleep and later wake preserve that cell's existing private workspace.
   The current host policy still permits one running customer cell at a time;
   other accounts wait for a safe handover. This change does not add concurrency.

## One-time host configuration

These are deployment instructions, not actions already performed. Use the normal
reviewed release and rollback process for both platform and supervisor code.
No SQL migration is needed.

- Prepare `/etc/agentai-supervisor/enrollment-policy.json` from
  `enrollment-policy.example.json`, root-owned and mode 0600. Replace the image
  placeholder with the host-verified digest already used for customer cells.
  The placeholder intentionally fails validation. Match `profile` to the
  approval command's `PROFILE`; current value is `trial-unmeasured-v1`.
- Ensure the configured backup root exists as a root-owned directory, mode
  0700, with no symlink at that path. The supervisor creates private per-account
  children and refuses linked, foreign-owned or permissive child directories.
- Set the policy's host enrollment ceiling deliberately. It is independent of
  the app's customer limit. The reserved range currently supports at most 39
  bindings (19101–19139, with quarantine ports 50 higher); retained bindings
  continue reserving their ports and count toward the ceiling.
- Add `--enrollment-policy /etc/agentai-supervisor/enrollment-policy.json` to
  the native supervisor's existing `ExecStart`, retaining its controller user
  and native wiring arguments. Validate the configuration with the same
  arguments plus `--check` before restarting through the release procedure.
  The check reports `automatic_enrollment_enabled`.
- Keep lifecycle worker and request worker services enabled, with the intended
  `customer_execution` switch. Enrollment policy does not bypass switch or
  capacity checks. Existing bindings are never replaced or re-enrolled.

Without the new argument, manual enrollment behavior is preserved. Rollback can
remove the argument without deleting custody, cells or workspaces. Existing
automatically enrolled bindings continue to be ordinary host custody records.

## Isolation evidence and acceptance

Local tests exercise two-account enrollment, distinct backup paths/ports,
immutable binding identity, pinned policy validation, capacity refusal,
approval rollback, account-specific wake/claim, and separate bridge relays and
credentials even when session names match. These use synthetic runtimes.

Before declaring the deployed system isolated, run a disposable two-account
acceptance exercise on the deployed revision: verify actual runtime `runsc`,
mounts and credentials, prohibit peer-cell/host/private-network access, place
different canaries in both workspaces, alternate prompts and sleep/wake cycles,
and attempt cross-account transcript/artifact/live/device requests. A guessed
foreign object ID must return no foreign content. Check crash recovery and
repeated approval submissions without duplicate cells or credential reuse.
Never use real customer content as test canaries.

This is isolation between customer accounts. The trusted application, host
supervisor and configured model providers remain part of the system's trust
boundary; cell separation does not mean those services receive no data.
Local checks do not certify a live firewall, container mount or absence of all
possible data leaks. No live acceptance was performed for this change.

Local validation on 31 October 2026: the focused lifecycle/bridge/queue suites
ran 119 tests (117 passed; two Linux `SO_PEERCRED` cases skipped on macOS).
The Django signup/account suite ran 38 tests, all passing. After the final
policy startup-validation change, all seven automatic-cell regressions passed
again. `git diff --check` passed. No production service was changed.
