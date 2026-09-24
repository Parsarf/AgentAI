# Phase 5 — Selective memory and durable autonomous work

Continue from Gate 4. Read the phase index, architecture and log. Verify
current docs for memory, compaction, session pruning, background tasks,
standing orders, cron/heartbeat, delivery and approvals. Choose supported
native primitives; do not recreate AgentAI's memory DB or scheduler.

## Work

1. Define memory categories and attribution: preference/fact/project/decision,
source, date, confidence and last confirmation where supported. Make memory
inspectable, correctable and deletable by the owner. Retrieved hostile content
may become an attributed claim but never a standing instruction. Use selective
retrieval and summarize large outputs into artifacts.
2. Configure durable objectives using the installed runtime's documented
mechanism. Persist the objective, plan, step status, artifacts, errors,
verification and cost. Resume after a controlled gateway restart without
repeating an external side effect. Keep each objective inside a budget and
give the owner an accurate short status response.
3. Configure cheap-first heartbeat/cron behavior. Scheduled runs must have
less authority than interactive work. Verify the actual approval delivery
surface for unattended tasks; if no reachable surface exists, the action must
deny or wait safely. Do not route a request to Telegram by assumption.
4. Test selective recall across sessions, owner correction and deletion, a
misleading external memory candidate, a multi-step objective interrupted by
restart, one scheduled task, and an approval timeout. Use harmless data and
no paid load. Run doctor, feature checks and security audit; log evidence.

## Gate 5

Memory recall is relevant and correctable; the interrupted objective resumes
without duplicate side effects; the scheduled task runs under the stricter
policy and its approval arrives on a tested surface or safely denies. Stop.
