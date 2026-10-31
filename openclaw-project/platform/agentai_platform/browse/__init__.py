"""Browser agent core: deterministic hands (the runner), a cost ladder of deciders, and policy that no model can override.

Pure logic with injected transports so it is fully testable offline. Production wiring (sandbox stage, per-account model key,
chat integration) lives outside this package.
"""
