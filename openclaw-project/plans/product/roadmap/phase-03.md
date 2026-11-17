# Roadmap Phase 3 - shared integration and action infrastructure

**Status (2026-11-16): DEPLOYED AND PROVEN LIVE.** Merged to `main` (pull requests #46, #47, #48); the server runs `8327634`. The live exit gates were run on the server with `platform/deploy/phase23_live.py`: all eight pass (the handoff gate in its few-seconds form; the `--hour` form has not been run). The three owner switches (`connector_writes`, `synthetic_connector`, `account_self_service`) are off. What follows is the record from before the deploy.

**Status (2026-11-15): BUILT AND TESTED, NOT DEPLOYED.** All nine features and the synthetic connector are built, with tests, behind owner switches that are off. Not
merged, not deployed, on the owner's instruction (see `phase-02.md`). The live exit gate has **not been run**; `platform/deploy/phase23_live.py` runs all five of its
points on deploy day and already passes against the test database.

## Exit gate (on the live stack with the synthetic connector behind its test-only switch)

| Gate | State |
|---|---|
| 1. A full write cycle: preview, approval, execute once under a forced retry, verify, undo | **Not run live.** Passes as `tests/test_actions.py` `Undo.test_a_full_cycle...`, over HTTP (`accounts/test_phase23.py` `WriteCycle`), as `A-ACTION-EXACT-ONCE` and `A-ACTION-UNDO`, and in the live script against the test database |
| 2. A forced failure after an irreversible step offers the registered compensation | Same: `Workflows.test_a_failure_after_an_irreversible_step...`, live script `P3-COMPENSATION` |
| 3. A three-step workflow that fails at step three leaves steps one and two reversed | Same: `A-WORKFLOW-WALKBACK`, live script `P3-WORKFLOW` |
| 4. A parked approval answered an hour later resumes from its checkpoint | Same: `Handoff.test_a_parked_approval_answered_an_hour_later...` (clock moved an hour), live script `P3-HANDOFF` (`--hour` really waits) |
| 5. A partial result is always stated as partial | Same: `A-PARTIAL-IS-SAID`, live script `P3-PARTIAL` |

## Feature table

| # | Feature | Label was right? | State now | Switch | Tests | Evaluation cases |
|---|---|---|---|---|---|---|
| 22 | API integration: the connector contract | P: yes | `connector_kit.py`: declaration plus adapter, six error kinds, first-party or MCP wrapper behind the same contract (the choice and reason recorded per connector), one client that applies state, role, policy, grants, the Phase 1 rate limiter, paging caps, freshness and receipts. Sealed custody replaces `DisabledCustody` when the key file exists. Six assistant tools, one per kind of operation | `connectors_linking`, `synthetic_connector` | `tests/test_connector_layer.py` `Contract`, `Custody` | `P3-ERROR-KINDS` |
| 23 | General pagination handling | M: yes | `paginate`: cursor, page-token and offset; caps on pages, items, bytes and time; every result says count, complete or not, the provider's estimate and a continuation handle; the tool result states a partial set in words | same | `Paging` | `P3-PARTIAL-IS-SAID`, `A-PARTIAL-IS-SAID` |
| 24 | Data freshness tracking | M: yes | `connector_freshness` per (connection, resource): last read, last complete read, count, last error; a limit per resource kind flags older data without refusing it; "as of" on every tool result and on Settings > Access | same | `FreshnessChecks` | `P3-FRESHNESS` |
| 25 | Concurrent edit detection | M: yes | Every record carries the provider's version token; a write sends it as a precondition where the provider takes one and re-reads just before writing where it does not; a mismatch is `conflict` with the customer's version, the current one and the proposed change | `connector_writes` | `tests/test_actions.py` `ConcurrentEdits` | `P3-CONFLICT` |
| 26 | Action previews (and approval) | P: yes | `actions.py`: the action record, a preview rendered from the stored payload by the connector's own renderer, approval bound to the payload hash and expiring, an organization may ask for an admin as well, automatic approval per connection and kind (never default, never silent for what cannot be undone), at-most-once execution, read-back of an unknown outcome, verification | `connector_writes` | `Previews`, `Approval` | `P3-WRITE-CYCLE`, `A-ACTION-EXACT-ONCE`, `A-ACTION-CHANGED-PAYLOAD` |
| 83 | Human handoff | P: yes | `handoff.py`: work that waits for a person holds no slot and no cell; reasons `action_approval`, `workflow_approval`, `question`; one table of how long each kind waits (browser waits 30 minutes as before, an approval 3 days, a question 1 day), shown to the customer; the chat driver's fixed 1,800 s became that table; an unanswered wait expires and nothing is done; an answer resumes the chat with a new turn | `connector_writes` (questions: connected services on) | `Handoff`, `ChangeApproval.test.tsx` | `P3-HANDOFF-RESUME` |
| 27 | Undo mechanisms | M: yes | A write kind registers its inverse or says why it cannot be undone (registration refuses neither); the inverse's data is captured before the forward write; undo is offered for the kind's stated time, is itself a previewed, approved action with a receipt, and carries the version | `connector_writes` | `Undo` | `P3-WRITE-CYCLE`, `A-ACTION-UNDO` |
| 28 | Compensating actions | M: yes | Follow-ups registered in code per write kind, their payloads written before the forward write, idempotent, proposed by the assistant or the customer and never invented | `connector_writes` | `Compensation` | `P3-COMPENSATION` |
| 29 | Cross-application workflows | P: yes | `workflows.py`: steps are actions from one or more connectors; changes that cannot be undone must come last (refused otherwise); one approval over a hash of every step; a failure walks the finished steps back in reverse with an exact report; survives a restart | `connector_writes` | `Workflows` | `P3-WORKFLOW-WALKBACK`, `A-WORKFLOW-WALKBACK` |
| - | A synthetic connector | n/a | `synthetic_connector.py`: folders, notes and messages with versions, cursor paging, queued faults (rate limit, server error, refused token, forbidden, a write that succeeds without answering), idempotency keys. The worked example in `platform/CONNECTORS.md` | `synthetic_connector` (test only) | every Phase 3 test | every Phase 3 case |

## Decisions taken

- **A change is sent by Lumina's own worker pass, not by the assistant.** The assistant's tool only prepares; the turn ends; the customer approves; the worker sends once
  and then starts a new turn that tells the assistant the outcome. That is what lets an approval wait for days without holding a cell.
- **The step in the idempotency key is counted by Lumina** (`<request id>-<step>`), never taken from the assistant's arguments. The same change asked twice in one task is one action.
- **"Reads first" is not a workflow step.** The assistant reads through the connector tools before it proposes; the workflow's steps are the changes, ordered reversible first.
- **A workflow walks itself back without a second approval.** The customer approved the workflow knowing (the preview says so) that a failure reverses the finished steps.
- **Approving from a phone link** is the same signed-in route: there is no link that approves by itself. Notifications that carry such a link belong to Phase 7.
- **No real connector is registered.** Gmail, Calendar, Drive and GitHub stay as they were (catalog entries with no adapter). Phase 5 writes the first real declarations.
- **MCP wrapper:** `McpAdapter` is built and tested against a stand-in for the MCP service. No provider is wrapped yet, so the per-connector choice ("official remote MCP server or first-party, and why") is recorded when each connector is added; the registry refuses a declaration without it.

## Needs the owner

Nothing blocks the build. On deploy day: the connector key file, the switch facts and the live proof (`PENDING_DEPLOY.md`). `connector_writes` can stay off until Phase 5
brings a real connector; turning it on earlier changes nothing a customer can reach.

## Cost, unknowns, rollback

Cost so far: none. Unknowns: the assistant's own use of the six tools (does it end its turn after `propose` as told) is not proven with a real model: the tools' words
say so and the resume turn tells it not to repeat, but the first real connector's evaluation in Phase 5 is where that is measured. Rollback: switches off, then the
release back (`PENDING_DEPLOY.md`).
