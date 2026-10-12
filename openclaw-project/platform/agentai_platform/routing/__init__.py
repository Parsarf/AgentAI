"""JEV-first task routing: classify, enforce policy outside the model, record, never execute.

The router only ever *recommends* a route. Deterministic policy decides what is allowed; the existing queue,
budget ledger, approvals and cell sandbox still gate every effect. Disabled and shadow-only until the owner enables it.
"""
