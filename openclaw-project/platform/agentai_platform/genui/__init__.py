"""Schema-driven generative UI: strictly validated specifications, never code.

A response block is data (a form or a task plan) that the front end renders with an allowlisted component set. The server
is authoritative: it validates every specification and every edit, and the only side effects a block can have are the
registered operations in ``store.py`` (save state, submit, launch), each of which re-checks ownership and limits.
"""
