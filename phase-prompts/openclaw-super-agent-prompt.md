# AgentAI customer platform — product brief

This brief replaces the former personal-only/from-scratch instructions.
Execute the [canonical Phase 1–19 prompts](openclaw/README.md) one at a time
under the [execution contract](openclaw/execution-contract.md). Do not paste a
second all-at-once build plan. The [coverage ledger](openclaw/coverage-ledger.md)
retains all prior unfinished requirements and maps historical phase numbers.

## Intended product

Customers sign in, own an isolated OpenClaw deployment, work through dashboard
chat or a linked Telegram identity, organize projects, follow useful live events
and receive versioned downloadable outputs. Usage admission, plan limits and
billing use consistent account/task records. Operators can diagnose failures,
recover a single customer and run a controlled beta before public paid signup.

The existing owner system provides reusable runtime configuration, restricted
workers, coding/integration bases, dashboard/live viewer and operator tools.
It is neither a blank installation nor an accepted multi-customer product.
The current user request supersedes old scope exclusions on customer accounts,
tenant provisioning and service subscription billing. Agent purchases remain
separate and disabled.

## Architecture and delivery discipline

OpenClaw supplies the native agent runtime. Product services supply customer
identity/routing, deployment lifecycle, projects/artifacts/event projection,
usage admission and hosted billing. Do not port the retired Python agent loop,
router, memory store, approvals or agent scheduler. Keep production on the
always-on server and Gateway credentials server-side.

Separate mutually untrusted tenants by actual execution/storage/secret/network
boundaries, including native Codex and ACP. Restricted researcher/browser
workers handle untrusted content; they cannot grant themselves policy,
credential, scheduling or outbound authority. Important coding work needs
objective tests, real browser verification and independent review. Memory is
selective, attributed and correctable; restart durability needs an actual
supported controller, not merely a saved transcript.

Build first with relevant inexpensive checks. Keep comprehensive/paid testing
and live account setup deferred until explicitly resumed. Missing authorization,
isolation or budget enforcement blocks dependent activation. Record build
readiness separately from actual acceptance and preserve original evidence.

Phase 1 defines exact offer/screens/example/retention/limits and calculates the
cost/capacity scenarios from sourced prices and measured inputs. Phase 5 puts
budget admission before customer execution. Phases 15–18 prove the completed
system, optional optimization, real beta workflow/payments and authorized
launch. No fabricated costs, capacity, completion claims or universal savings.
