# Existing VPS trial — complete product, limited concurrency

Owner direction, 2026-09-30: use the existing VPS and shared domain, retain every
planned feature and the ability to invite users, upgrade hardware later. This
supersedes an upgrade-first implementation sequence. **Plan selected; deployment
and agent execution are not activated.** No feature switch was changed to true.

## Trial experience

- Start with at most two invited trial accounts. Invitations use the existing
  scoped operator/onboarding flow, never public signup. Creating an account does
  not start a Gateway. Account data, sign-in and artifact/history access persist
  while its agent is stopped. No real invitations were sent by this plan update.
- Both accounts use the same dashboard/domain and customer Telegram ingress.
  Each keeps its own agent state, projects, memory, files, credentials and budget.
  A stopped account is not reset or reassigned to someone else.
- One customer task runs globally, one per account, with the existing three-task
  queue limit per account. Two signed-in users can use the dashboard at once;
  task execution is serialized. Show “Waiting for server capacity” and queue
  position only within the customer's own account. Do not reveal another user's
  name, task, files or spending. No promised wait time without measured evidence.
- Start the selected account's private cell on demand. Drain and stop it after
  the task when it is safe; wait for observed shutdown before waking another.
  Unknown start/stop state retains its resource reservation and blocks overlap.
  Approval waits, uncertain provider effects and native durable jobs need exact
  recovery/cancel/reconciliation semantics; never kill them to free a slot.
- Run build, browser verification and independent review sequentially with their
  own account/project sandboxes. Start only the needed worker, then prove exit
  before releasing its reservation. Reviewer independence is preserved even
  though its execution is later in the sequence.
- The profile changes throughput and startup latency. It does not remove any
  planned feature or bypass ownership, secrets, resource or usage enforcement.
  A task exceeding the measured envelope reports capacity-blocked with partial
  outputs if present. Hardware cannot make every possible task size fit.

## Feature scope and remaining implementation

| Capability | Build phase | Current-host policy |
|---|---|---|
| Sign-in, recovery, operator invitations | 3 | Existing account code; deploy isolated app/TLS/mail before real onboarding |
| Independent agent lifecycle and worker sandboxes | 4 | On-demand cells, one active customer, safe sleep/wake; adapter still missing |
| Usage, entitlements, task budgets | 5 | Same enforcement for trials and upgraded host; trial allowance remains $1 |
| Dashboard chat, projects, history, retry/cancel | 6 | Durable app projection and scoped native adapter; wake only with admission |
| Telegram linking and active project | 7 | Single ingress; account routing; queue while cell is stopped |
| Files, previews, downloads, app ZIPs | 8 | Persistent versioned artifacts available without running a Gateway |
| Live work, approvals, reconnect | 9 | Timeline persists while sleeping; queued/capacity state is explicit |
| Memory, durable work, skills, schedules | 10 | All retained; background execution uses the same global slot and budget |
| Connected services and protected browser identity | 11 | Account-bound credentials and required authorization checks |
| Optional browser/research optimization | 12/16 | Retained; enable only after its selected implementation and comparison proof |
| Checkout, invoices, cancellation, payment failure | 13 | Same adapter and UI; test mode clearly labeled until live billing authorized |
| Backups, restore, monitoring, rollback | 14 | Drain customer execution for resource-heavy maintenance; no extra live cell without admission |
| Security/capacity/workflow acceptance | 15/17 | Validate two accounts with serialized execution on this host |
| Paid launch and optional purchases | 18/19 | Retained; normal commercial/authorization gates still apply |

No phase, legacy case or requirement is deleted. “Available” means a working,
verified adapter, not a visible button connected to a disabled driver. Optional
and later features remain scheduled in their existing phases; this direction
keeps them in the final product rather than claiming they are implemented today.
The $79/$25/$5 selected plan and seven-day/$1 trial remain unchanged. Testing
billing uses provider test mode; no automatic charge or paid signup is enabled.

## Capacity work on this server

The previous snapshot remains valid evidence for the **default 2GiB cell**:
about 0.95GiB available RAM and >99% swap used yielded zero admissible default
cells. It is not evidence that a smaller on-demand profile works or cannot work.
Do not overwrite that result or treat a smaller container memory cap as a measured
working footprint. One active cell still overlaps product services and its worker.

1. Inventory current owner activity and measure fixed usage again. Identify truly
   idle resource consumers; prepare scoped drain/rollback before changing them.
   Preserve active owner work and its state. No owner cleanup is done by this plan.
2. Implement the lifecycle and resource broker locally. Prepare a bounded native
   startup probe with pinned image, separate scratch roots, no owner credentials,
   no provider calls and a verified safe host envelope. If it cannot fit, report
   that precise blocker and continue independent implementation.
3. Measure startup and small representative research/build/browser/review stage
   peaks, cgroup swap/PIDs/CPU and storage, including runtime isolation overhead.
   Paid probes require an explicit bounded allocation. Gate each worker stage,
   not just Gateway creation. Do not rely on swap or host OOM to enforce admission.
4. Enforce aggregate tenant hard limits and fresh owner/platform reserves. Stop
   idle cells only after receipt/job reconciliation. Settle or retain provider
   liability consistently; queued reservations have bounded expiry and safe
   cancellation, not indefinite provider-budget locks.
5. Run private A/B ownership, worker, network, mount, secret and restart proofs;
   prove a racing second task cannot acquire the global slot. Validate artifact
   and chat access while stopped, cold wake and replay without duplicate effects.
6. Then activate the invite-only trial after required feature boundary checks.
   The default-profile zero-slot result does not require buying new hardware;
   live execution still needs an actually measured fitting profile. If no such
   profile fits without harming owner work, report that limit honestly.

## Acceptance and later upgrade

Existing-host trial acceptance uses two real controlled accounts with **one
running customer task**. B must remain able to sign in, inspect its own history,
download its own artifacts, queue/cancel pending work, and be denied access to A.
Run both accounts' complete workflows in turn. Maintenance/restore may queue
execution while the app remains available, with that limitation disclosed.

Keep simultaneous two-cell execution and restore-while-another-task-runs cases
as NOT_RUN/BLOCKED until capacity permits; they are gates for increasing global
concurrency, not claims of passed trial proof. Security, per-account isolation,
resource enforcement, budgets, required independent review and complete-task
proof remain mandatory for the serialized trial. Never use serialization as a
substitute for filesystem/network/credential boundaries.

A later VPS upgrade changes measured resource ceilings and allowed concurrency.
Use the same domain, accounts, isolated durable roots, APIs, bot links and feature
adapters. Back up and restore with tested compatibility if the provider resize
requires replacement. No account reset, separate customer domain or rewrite.
16GiB/4vCPU is an optional sizing candidate, not a trial prerequisite or purchase.

Immediate next work remains Phase 4: implement the durable cell supervisor,
resource/worker broker and measured low-footprint profile. Features from later
phases are not fabricated or activated by this document.
