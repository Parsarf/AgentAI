> Current target: existing-VPS trial first; see [trial profile](EXISTING_VPS_TRIAL.md).
> VM sizing and upgrade allocations below are historical scenarios, not current
> trial prerequisites. Costs remain unknown until measured/quoted.

# Cost and capacity — 2026-09-29

Reproduce arithmetic with `python3 product/calculate_costs.py` from repository
root. [Inputs](cost-inputs.json) and [results](cost-results.json) are versioned.
Decimal arithmetic; USD only. Token volumes and non-provider costs below are
explicit scenarios, not measured bills. No paid probes were run for Phases 1–2.

## Verified public price inputs

| Route | USD price | Source / uncertainty |
|---|---|---|
| Sonnet 4.6 | $3/M input; $15/M output; $0.30/M cache read; $3.75/M 5min cache write | [Anthropic](https://claude.com/pricing); standard rates, account/region extras unverified |
| Haiku 4.5 | $1/M input; $5/M output; $0.10/M cache read; $1.25/M 5min cache write | [Anthropic](https://claude.com/pricing); actual usage not measured |
| Brave Search | $5/1,000 requests = $0.005/request | [Brave](https://brave.com/search/api/); do not subtract free credits from task reservations |
| Optional Jev 1.13 | $0.042/M input | [TypeSafe](https://docs.typesafe.ai/models); disabled, separate route/terms/accounting |
| Domestic US card + Billing | 2.9%+$0.30, plus 0.7% of billing volume | [Stripe Payments](https://stripe.com/pricing), [Billing](https://stripe.com/billing/pricing); account/country/payment-method rates need verification |
| Native Codex / ACP | Unknown complete metered commercial route | Existing owner subscription/quota is separate; no zero-cost assumption/customer sharing |
| Host/DB/tenant VM/storage/identity/mail/monitoring/support | Actual invoices/quotes unknown | Current IONOS deployment includes proxy DB, but invoice not inspected; no invented quote |

Standard task formula: billable uncached input×input rate + cache read/write
volumes×respective rates + output×output rate + search/tool fees. Cached tokens
are distinct from uncached tokens; do not charge both for the same input.
Reservation must bound all remaining steps/output/retries/fallback/verification
and uncertain inflight liability. A 50% illustrative buffer is not a hard cap
or sufficient admission rule. Phase 5 must enforce a real quote/reservation.

## Calculated scenarios

| Scenario | Sonnet input/output | Haiku input/output | Searches | Known research-route cost | Illustrative 50% reserve |
|---|---|---|---|---|---|
| Low | 4,000/1,000 | 1,000/200 | 2 | $0.039 | $0.0585 |
| Base | 40,000/8,000 | 4,000/800 | 6 | $0.278 | $0.417 |
| High | 160,000/32,000 | 16,000/3,200 | 20 | $1.092 | $1.638 |

These are sums across calls, not single-request context assumptions. They
exclude unknown coding/reviewer routes, extra provider fees and infrastructure.
**Complete coding task total remains unknown**. Per-task $5 maximum is an
allocation; tasks must be scoped/admitted within it, never assumed affordable.

At owner-selected $79/month, domestic-card+Billing fee is $3.144. Revenue after that
fee and full $25 included provider consumption is $50.856 before compute,
storage, identity/mail, monitoring, support, tax/refunds and other liabilities.

For sensitivity only, assume fixed platform $40/mo and per-customer node $12,
backup $1, identity/mail $0.20, monitoring $0.20, support $5. Then variable cost
including full provider consumption and payment fees is $46.544/customer,
contribution $32.456 and fixed-cost break-even `ceil(40/32.456)=2` customers.
These are hypothetical inputs, not vendor quotes/profit evidence. At 2 customers
that model costs $133.088/month versus $158 revenue; actual monthly total is
unknown until invoices and customer-node/support measurements are available.
Each extra dollar of node/support cost reduces contribution by one dollar;
non-positive contribution has no finite break-even. Taxes and FX are excluded.

Optional browser benchmark remains 180 runs plus calibration/adversarial/canary
and corrections. Applying the unrelated base research scenario gives $50.04
for 180 runs as arithmetic only; it is **not a browser quote**. Measure each
complete browser route first, including coding/planning/fallback, before admission.
The current owner $2/day backstop cannot admit that illustrative suite unchanged.

## Actual host inventory and capacity decision

[Live inventory](../openclaw-project/plans/product/runtime-inventory.json)
observed 2026-09-29T23:05:20Z: 2 CPUs, 4,055,998,464 bytes RAM (~3.78GiB),
1,021,976,576 bytes available (~0.95GiB), 2,140,823,552 bytes of swap used
(~1.99GiB), 88,903,847,936 bytes disk available (~82.80GiB). The owner Gateway
was healthy, model proxy/database and backup timer present. A snapshot is not
peak capacity. Existing browser containers/owner workloads account for resource
usage; they were not stopped or pruned.

Foundation app/control budget: two processes, maximum 128MiB each, no swap,
25% CPU quota each, 16 processes/threads each, eight connections each, five-second
socket timeout. Proposed safety headroom 512MiB. With current available RAM,
`floor((0.95GiB-0.50GiB-0.25GiB)/2GiB)=0` hypothetical additional 2GiB active
customer cells. More strongly, the selected hostile-customer boundary is a
separate VM: the owner VPS admits **zero customer deployments** in this design.
Do not substitute extra swap or a namespace for verified customer isolation.

Starting customer-node sizing assumption: 2vCPU/4GiB, 10GiB workspace quota,
1GiB Gateway ceiling, 768MiB browser, 768MiB builder, 256MiB connectors plus
OS/reviewer/safety headroom. These allocations alone approach capacity; serialize
builder/reviewer/browser overlap as needed and measure peak before admission.
One customer's active task/node is a ceiling, not proof that the example fits.
Two simultaneous customers require two separate nodes plus measured control-plane
capacity in Phase 4/15. Node quote and cloud account access remain decisions.

Artifact quota 2GiB/account: 30 daily full copies would be at least 60GiB/account
before DB/state/browser credential backups and encryption overhead; two customers
≥120GiB if every day is full quota. This is an intentionally conservative worst
case, not a forecast. Use bounded/versioned/incremental retention with measured
restore consistency. Thirty-day backup expiry must include deletion tombstones.
RPO target24h/RTO30min are proposed; measure actual age/time in Phase 15.

## Missing measurements and activation gates

Get actual host/customer-node/off-host quotes; identity/mail/monitoring cost;
commercial Codex/ACP route plus exact receipt/price support; low/base/high real
task usage; peak per-tenant CPU/RAM/storage and recovery timing; provider privacy/
regional terms and Stripe account fees. Unknown inputs stay null in results.
Independent Phase 2 work does not need these purchases; enabling customer paid
execution and public offer does. Existing owner caps/keys remain unchanged.

## Phase4 deployment target correction — one VPS/shared domain

The VM-per-customer design above is historical and superseded by the owner's
one-VPS target. A single public app domain routes internally to private independent
cells, never a shared customer Gateway. Current capacity remains0 added agents
from measured headroom, rather than a permanent rule excluding the owner host.
See [reproduced Phase4 calculation](../openclaw-project/plans/product/phase-04-capacity.json)
and [assessment](../openclaw-project/plans/product/phase-04-single-vps-assessment.md).
16GiB/4CPU is an unmeasured two-account beta allocation candidate; upgrade invoice,
stronger-runtime/worker peaks and backup costs remain unknown. The earlier $12
per-node sensitivity is an illustrative scenario, not a quote for shared cells.

## Existing-VPS trial clarification — 2026-09-30

Owner selected trying the existing server before any upgrade. The current target
is two invite-only accounts, one global running customer task, on-demand private
cells and sequential isolated worker stages. Keep every planned feature; no
hardware upgrade prerequisite for implementation. Default-profile zero-slot
measurements remain historical evidence, not proof of a smaller profile. Follow
`product/EXISTING_VPS_TRIAL.md` and deployment policy v2. Measure a fitting profile
and complete isolation/budget checks before execution. Account invitations do
not automatically start an agent; later resize changes capacity, not accounts,
domain or feature scope. No live deployment or feature activation in this update.
