# Roadmap Phase 2 - permissions and account lifecycle

**Status (2026-11-15): BUILT AND TESTED, NOT DEPLOYED.** All ten features and the organization model are built, with tests, behind owner switches that are off. By the
owner's instruction of 2026-11-15 nothing was merged to `main` or deployed: the phases are collected on branch `phase-0-1-review-fixes` and deployed together. The live
exit gate has therefore **not been run**; `platform/deploy/phase23_live.py` runs it on the server on deploy day, and the same script already passes against the test
database (`accounts/test_phase23.py` `LiveProofScript`). The steps for that day are in `platform/deploy/PENDING_DEPLOY.md`.

## Exit gate

| Gate | State |
|---|---|
| 1. The existing suites pass unchanged with the new permission function in place | **PASS** locally: the 684 blocking platform tests of Phase 1 pass with no change to them; the accounts suite passes with three guard tests updated because three "disabled" routes are real now (`test_all_sensitive_routes...`, the API description check, the wiring rule) |
| 2. Every route and relay tool names an action; the per-row tests pass | **PASS** locally: `accounts/test_phase23.py` `EveryRouteNamesAnAction` (both directions), `tests/test_permissions.py` (one check per row and role, generated from the table; every relay tool) |
| 3. A disposable account is offboarded on the live stack and the scan finds only the tombstone | **Not run live.** Passes in `tests/test_data_lifecycle.py`, over HTTP in `accounts/test_phase23.py`, as acceptance case `A-OFFBOARD-CLEAN`, and inside the live script run against the test database |
| 4. The retention sweeper is scheduled, and the privacy record and public policy match it | Unit files and the command exist; the record and the policy text are **prepared in this branch** and match (`tests/test_privacy_policy.py`). Installing the timer and publishing the page are deploy-day steps |

## Feature table

| # | Feature | Label was right? | State now | Switch | Tests | Evaluation cases |
|---|---|---|---|---|---|---|
| - | Organization model | n/a | `organizations`, `organization_members`, `accounts.organization_id` (migration 0044). Every account is an organization of one with the same id, its customer the owner; a trigger does the same for every account made later. One cell per member | none (always on, no visible change) | `tests/test_permissions.py` | `P2-ROLE-VIEWER` |
| 12 | Role-based access control | P: yes (only `customer` existed) | Four roles; one table (`permissions.py`); one function `security.allowed`; asked by the account middleware for every route (`accounts/route_actions.py`), by `store._authorize`, the queue (claim and heartbeat), the Telegram ingress and the tool relay (`ToolPermit`). A role change ends the person's sessions | none | `tests/test_permissions.py`, `accounts/test_phase23.py` | `P2-ROLE-VIEWER`, `A-ROLE-VIEWER` |
| 13 | Resource-level permissions | P: yes | `connector_grants`; a new connection reaches nothing; "everything" is `*` per kind; checked before a request leaves and again on the way back (`ConnectorClient`); `authorize_read` carries the scope and `authorize_write` exists | `connectors_linking` / `synthetic_connector` | `tests/test_connector_layer.py` `Grants` | `P2-GRANT-BOUNDARY`, `A-GRANT-BOUNDARY` |
| 14 | Permission visibility | P: yes | `GET /v1/controls` and Settings > Access, generated from the enforcement tables (`access.py`); `/v1/integrations` is real; a test compares the page with `connector_grants` | none (the page is always there) | `accounts/test_phase23.py` `AccessPage`, `AccessPage.test.tsx` | `P2-ACCESS-PAGE-IS-ENFORCEMENT` |
| 15 | Organization policy enforcement | M: yes | `organization_policies`: tools allowed, connectors allowed, write kinds (allowed, admin as well, blocked), member spending limits (lockable), own model key, knowledge sources. Safety switches gained an organization scope that overrides a member's; privacy protections still cannot be switched off for a group. The snapshot other processes read carries it | none | `tests/test_permissions.py` `Policy`, `Organization.test.tsx` | `P2-ORG-POLICY` |
| 16 | Credential refresh | P: yes (no job existed) | `connector_refresh.py`: a database lock per connection, three failure kinds, tokens only in custody, logs the connection id and outcome. Remote MCP OAuth connections are kept fresh by the same job | runs when connected services are on | `tests/test_connector_layer.py` `Refresh` (40-cycle soak; invalid token ends in "needs you" once) | `P2-REFRESH-SOAK` |
| 17 | Credential revocation lifecycle | P: yes | `ConnectorService.revoke` / `revoke_by_system`: checked at call time, tokens leave custody, grants and automatic approvals go, waiting changes end, schedules that need it pause; one audited receipt | none (removing is always possible) | `tests/test_connector_layer.py` `Revocation` | `P2-REVOKE-RECEIPT` |
| 18 | Data retention management | P: yes (defined, not scheduled) | One table (`retention.py`), one sweeper (`manage.py retention_sweep`, timer unit), `privacy/derive.py` reads it, a test fails when a table has no rule, `GET /v1/retention` and Settings show it | timer installed at deploy | `tests/test_data_lifecycle.py` `Retention` | `P2-RETENTION-TABLE` |
| 19 | Customer data export | P: yes | One ZIP with a manifest (kind, count, hash per file), documented in `platform/DATA_EXPORT.md`; single-use expiring link; archive kept 7 days; an owner may export the organization | `account_self_service` | `tests/test_data_lifecycle.py` `Export`, `accounts/test_phase23.py` | `P2-EXPORT-ARCHIVE` |
| 20 | Customer data deletion | P: yes | `data_lifecycle.py`: each store a checkpoint (connections, custody, memory bank, model key, cell, files, database, sign-in identity), a verification scan of every table and store, what remains stated; deleting one chat uses the same steps | `account_self_service` | `tests/test_data_lifecycle.py` `Deletion` | `P2-OFFBOARD-SCAN`, `A-OFFBOARD-CLEAN` |
| 21 | Complete account offboarding | M: yes | The guided flow in Settings and `manage.py offboard_account`: stop work, export choice, end connections, cancel the subscription, cooling-off (7 days, cancellable), delete, confirmation email with the report. Removing a member offboards that member's account | `account_self_service` | `tests/test_data_lifecycle.py` `Offboarding`, `DataControls.test.tsx` | `P2-OFFBOARD-SCAN` |

## Decisions taken (the prompt's "stop and ask" list, answered with its recommended defaults because the owner asked for the build without a question round)

- **One cell per member**, not a shared cell. Isolation between members is the same as between customers.
- **Team invitations ship later.** The checks, `add_member`, role changes and removal exist and are tested; there is no invitation screen.
- **Custody uses the vault's sealing** (AES-256-GCM, a key per account derived from a master key in a root-only file), in its own key space and its own file.
- **Roles, grants, automatic approvals and waiting changes are never restored from a backup** (what stands now stands), like memberships and safety switches.
- **Export, deletion and offboarding keep their checkpoints in `account_jobs`**, not in `objectives`: a deletion must keep its report after every other row of the account is gone.
- **Financial records** are copied out as amounts and dates (`financial_records`) before the rows they hung on are deleted; receipts cannot stay where they were without keeping the chats they point at.
- **A machine may still never delete a cell.** Deleting the cell of a leaving account is a separate, narrow call that works only while the account is `deleting` and a deletion job is open.
- **The confirmation email goes out before the address is erased**, and a last check confirms the address is gone.

## Needs the owner before or on deploy day

- **The privacy policy wording** (prepared, not published). Three rows of the retention table changed and one line of the summary; `PENDING_DEPLOY.md` step 1.
- **Enforcing retention deletes old activity and security records for good.** That is what #18 asks for; it happens on the first run of the timer.
- The connector key file, the three timers, the switch facts, the live proof (`PENDING_DEPLOY.md`).

## Cost, unknowns, rollback

Cost so far: none (no model call, nothing on the server). Unknowns: the memory bank and cell deletion adapters are exercised with stand-ins in tests; their real
counterparts run for the first time in the live proof (the disposable account has no cell and no memory bank, so those two stores are first exercised by a real
customer's offboarding: run one with a second disposable account that has a cell before turning `account_self_service` on). Rollback: `PENDING_DEPLOY.md`.
