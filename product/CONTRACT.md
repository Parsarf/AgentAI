# AgentAI first offer — launch contract v1

Status: **design complete; owner-selected pricing and limits; not a live offer**.
2026-09-29. Numeric source of truth: [plan.json](plan.json). Public activation
requires Phases 3–5/15–18 and the commercial/legal decisions below.

## What the customer buys

One private agent environment for one individual account. In the proposed
Builder plan ($79/month), customers work in dashboard conversations or linked
Telegram DMs, organize up to 10 projects, follow a useful live timeline and
receive versioned downloadable results. Included provider consumption is
$25 per billing month, with $5 per rolling 24 hours and $5 maximum per task.
A limit is provider cost, not a promise of task count. No automatic overage.
The subscription price is charged by the service; this allowance is neither
a cash wallet nor authority for the agent to purchase things.

Research returns supported primary-source links and an explanation of uncertainty.
A small app build/debug task delivers source, locked dependencies, tests,
start instructions and a ZIP. Completed software requires actual tests,
restricted browser verification and independent review on its final revision.
If a required stage fails or its paid route is unavailable, the task reports
failed/blocked/partial, with accessible outputs, rather than a verified result.
No public app hosting is included in this offer.

Private beta first, maximum two invited paying/test customers. Phase 15 verifies
the selected serialized trial profile; parallel execution requires separate
measured capacity and concurrency acceptance before raising that ceiling. One
running task/customer and three queued tasks/customer. This is a policy ceiling,
not current host capacity. Owner clarified one service-operated VPS and one
shared public domain; customers supply no infrastructure. Each account requires
a separate isolated agent environment. The owner selected an existing-VPS trial with one globally running customer task,
on-demand separate cells and sequential worker stages. Keep every planned feature
in scope; an upgrade is optional later capacity work, not a trial prerequisite.
The earlier default-cell assessment admitted zero agents; a smaller profile still
requires actual capacity and isolation proof before execution. Invitations and
account access do not themselves reserve a running cell. See
[existing-VPS trial](EXISTING_VPS_TRIAL.md) and the historical
[Phase4 assessment](../openclaw-project/plans/product/phase-04-single-vps-assessment.md).
Trial: invite-only, seven days, one project, $1 total provider allowance, no
card requirement/no automatic paid conversion. Trial gets the same ownership
boundaries; free means funded by the service and still admitted/reserved.

## Supported work and release scope

| Capability | Release | Observable promise |
|---|---|---|
| Research and small app build/debug | Launch required | Primary sources; tested/reviewed named version + reproducible bundle or explicit failed/partial result |
| Dashboard and Telegram DM chat | Launch required | One scoped history/project mapping; refresh continues conversation |
| Projects, safe inputs, artifact versions/download | Launch required | File provenance and ownership on every URL/API |
| Live timeline and native cancel | Launch required | Durable public progress/events, reconnect, honest control availability |
| Memory | Launch required | Project context plus selected confirmed preferences; view/correct/delete active records and index |
| Durable tasks | Launch required | Persisted plan/receipts/status, safe restart reconciliation and explicit resume controls; uncertain effects not repeated |
| Autonomous execution resume | Later unless native controller is proven before launch | No promise that a saved goal automatically restarts a process; preserved requirement NATIVE-05 |
| Schedules/watchers/reusable customer skills | Later release | Native stricter unattended authority; unchanged watcher zero model calls; requirements remain in ledger |
| Brave source discovery and isolated browser | Launch required | Researcher-only search, browser-only worker; source content grants no authority |
| Google Gmail/Calendar/Drive, GitHub, credentialed site browsing | Later release | Account-bound read-only base and protected sign-in; customer writes need proven exact authorization |
| Jev browser/research | Optional Phases 12/16 | Baseline default; promotion only from measured accepted track |
| Agent-funded purchases | Optional later Phase 19 | Disabled at launch; customer funding/opt-in/provider proof are separate |

The required coding/review billing routes must be metered/admitted for the
hosted service. The owner's ChatGPT login/quota is not a customer billing or
auth isolation solution. If no supported commercial route exists, coding
activation is blocked; do not silently sell a narrower completed product.

## Numeric limits and enforcement

| Limit | Value/unit | Enforcement point / failure |
|---|---|---|
| Price / monthly included provider usage | Proposed $79 / $25 USD | Billing/entitlements and usage ledger; exhaustion blocks new admission |
| Daily/task budget | $5 rolling 24h / $5 per task | Atomic reservation before provider dispatch; insufficient allowance denies without call |
| Running/queued tasks | 1 / 3 per account | API + task admission; explicit queue-full refusal |
| Task duration/steps/model/search calls | 60min / 60 steps / 30 model calls / 20 searches | Native adapter/dispatch fences; stop safely, settle liability |
| Retry | Up to 2 retries for transient errors | Same operation identity; denial/uncertain effect never blind retry |
| Message/project name | 16,000 / 120 characters | API validation before persistence |
| Upload | 10MiB/file, 25MiB/batch, 10 files/batch | Streaming ingress + scan/quarantine; no parse before acceptance |
| Storage/artifact/export | 2GiB/account; 100MiB/artifact; 250MiB uncompressed ZIP | Capture/export admission; versions/uploads/ZIP copies count |
| Projects / event streams | 10 projects / 3 concurrent streams/account | Server/database ownership and capacity gates |
| Approval/link/download/session | Approval ≤24h; link 10min; download 5min; session idle2h/absolute24h | Exact account/payload/version/purpose binding, atomic consume and revocation |
| API rate defaults | 60 reads/min, 10 mutations/min, 5 sign-in/recovery attempts/15min per identity+IP | Edge + API; 429 Retry-After, no side effects |
| Event replay / event payload | 30days / 32KiB normalized event | Event storage/transport; expired cursor resyncs scoped snapshot |

A task reservation includes verification/review, bounded retries, fallbacks and
uncertain liability. Limits do not authorize a route, new credential, external
write or release. Preserve the separate owner's existing $2/24h + $25/30d caps.
These proposed customer defaults never modify the owner key.

## Exact file support

Input allowlist: UTF-8 `.txt` (text/plain), `.md` (text/markdown or text/plain),
`.csv` (text/csv), `.json` (application/json), `.pdf` (application/pdf), `.png`
(image/png), `.jpg`/`.jpeg` (image/jpeg), and source `.py`, `.js`, `.ts`, `.tsx`,
`.jsx`, `.html`, `.css`, `.sql` as validated UTF-8 text with a source-preview
label. Text bounded to 1MiB decoded for direct context; larger accepted files
are summarized via bounded extraction. PDF bounded to 50 pages; images ≤20
megapixels. Reject NUL/binary in text, mismatched image/PDF signature, invalid
JSON, encrypted PDFs and unsupported media. MIME/extension alone is not proof.
Inputs remain quarantined until the selected scanning path passes. If scan or
safe parser is missing, uploads stay disabled. No input archive extraction at
launch; no executables, Office macros, video/audio or arbitrary script execution
outside the project sandbox.

Output support: supported source/text/JSON/CSV, PNG/JPEG, safe generated PDF
and ZIP bundles (output only). Each immutable artifact version has task/run,
name/type/size/hash/time/tested revision/verification status. Text is escaped;
HTML/apps preview on an isolated origin without dashboard cookies. Do not
serve active content in the account origin. PDF preview uses a sandbox viewer.
Download authorization is checked against current membership and exact version.

## Task lifecycle, failure and approvals

Queued = admitted/reserved, waiting for execution capacity. Running = native
run observed. Waiting-for-approval = exact supported decision awaiting customer;
no effect until authorized. Paused = native execution pause acknowledged; do
not set this just because a timeline stopped scrolling. Blocked = dependency/
authorization/native capability absent, with next action. Cancelled = stop
acknowledged and no new steps admitted; already completed external effects
remain. If cancellation is pending/uncertain, show that rather than cancelled.
Failed = actual unrecoverable stage error; budget-exhausted = further admission
denied; completed = required assertions, artifact capture and final reconciliation
(or explicitly labeled late-usage pending) succeeded. Terminal/uncertain states
retain partial artifacts and short factual explanations.

Timeline pause only stops display. It always says “Pause timeline”. Execute
pause/cancel buttons exist only where the native adapter has verified semantics.
Native cancel is launch-required; unsupported installed abort blocks that gate.
No public raw model reasoning, credentials, private prompts or global audit feed.

Retries create a recorded attempt or reconcile the same invocation according
to effect certainty. Network failure after write is unknown, holds reservation
and requires receipt lookup. Provider outage blocks the affected route; no
unapproved cross-provider fallback. A customer cannot approve past a hard limit.
A requested larger scope needs a new affordable reservation. Support receives
redacted IDs/outcomes; account content requires scoped audited customer consent.

Proposed credit policy: actual successful/failed provider consumption counts;
a service-caused duplicate/error may receive an auditable service credit after
review. Unknown liability remains pending. Cancellation/refund never rewrites
provider receipts or silently increases a hard cap. Subscription cancellation
ends renewal, retains current access through the paid period; failed payment
gets a 72h proposed grace then blocks new tasks, allows billing/export access,
and safely drains/reconciles running work. Reactivation comes only from verified
billing state. Final refund/tax terms need commercial/legal decision before sale.

## Retention and account deletion

| Data | Default retention | Deletion/export behavior |
|---|---|---|
| Chat/task summaries | 90days rolling | Scoped JSON export; remove active records within 7days of confirmed account deletion |
| Confirmed memory/project context | Until corrected/deleted/account deletion | Active source+retrieval index removed; history/backups disclosed separately |
| Inputs/artifact versions | Until customer/project deletion or 30days after subscription end | Quota applies; version manifest/ZIP export; active deletion ≤7days |
| Detailed live events | 30days | Redacted export; expired cursor yields current summary |
| Application audit | 180days | Minimal pseudonymous metadata; restricted operator/security access |
| Backups | 30days maximum | Encrypted off-host; deleted data ages out, not instant removal; restore reapplies tombstones |
| Billing/usage receipts | Proposed 7years pending jurisdiction/accountant review | Minimized financial records retained separately; no automatic deletion of required records |
| Provider data/caches | Provider-specific unknown until route review | Disclose current provider terms/residency before activating route; no universal zero-retention claim |

Confirmed deletion revokes account/Telegram/sessions/keys immediately, stops
new task admission, reconciles inflight effects, marks a tombstone and removes
active customer content within seven days. Restores must respect that tombstone
and current billing entitlement. Audit/financial exceptions and provider copies
must be stated in the customer disclosure; no invented legal obligation.

## Decisions and acceptance

Owner selected the $79/month/$25 included/$5 task/one-running-task/no-overage
plan in this session. Other operational defaults are documented design choices.
Open launch decisions: legal entity/jurisdiction/tax/refund/
financial retention, provider commercial usage/data terms, metered coding/reviewer
route, customer-node/off-host backup vendor and recovery key custody. Independent
builds can proceed. These decisions block selling/activating dependent capabilities.

Every promise/limit maps to the [requirement ledger](../openclaw-project/plans/product/requirements.json),
[screen designs](SCREENS.md), [complete example](EXAMPLE_TASK.md) and
[calculated cost/capacity scenarios](COST_CAPACITY.md). Design acceptance is
complete when these mappings are valid; this is not runtime customer acceptance.
