"""Effective tool-ceiling checks over the recorded capability inventory (Phase 10).

Inspects the sanitized inventory (``plans/product/capability-inventory.json``),
never live config or credentials. Findings are ``fail`` (violates policy even
for the owner runtime) or ``customer-blocker`` (acceptable for the owner
runtime but must be resolved before a customer cell is activated). Metadata
is not runtime proof: a clean result here is a necessary, not sufficient,
condition; effective-denial probes remain Phase 15 (P15-RESEARCH).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

RESTRICTED = {'researcher', 'browser-worker', 'critic'}
BUILDERS = {'codex-builder', 'codex-debugger', 'claude-builder', 'claude-debugger'}
NEVER_FOR_WORKERS = {'sessions_spawn', 'sessions_send', 'sessions_yield', 'subagents', 'cron',
                     'automations', 'gateway', 'message', 'exec', 'process', 'apply_patch',
                     'memory_search', 'memory_get', 'get_goal', 'create_goal', 'update_goal'}
NEVER_FOR_BUILDERS = {'sessions_spawn', 'sessions_send', 'sessions_yield', 'subagents', 'cron',
                      'automations', 'gateway', 'message', 'web_fetch', 'web_search', 'browser'}


def check(inventory: dict) -> list[dict]:
    findings = []

    def add(level, agent, rule, detail):
        findings.append({'level': level, 'agent': agent, 'rule': rule, 'detail': detail})

    agents = {a['id']: a for a in inventory['agents']}
    for name, agent in agents.items():
        allow, deny = set(agent.get('tools_allow', [])), set(agent.get('tools_deny', []))
        both = allow & deny
        if both:
            add('fail', name, 'allow-deny-conflict', sorted(both))
    for name in RESTRICTED & agents.keys():
        agent = agents[name]
        allow, deny = set(agent['tools_allow']), set(agent['tools_deny'])
        missing = NEVER_FOR_WORKERS - deny
        if missing:
            add('fail', name, 'worker-denies-privileged-tools', sorted(missing))
        if allow & NEVER_FOR_WORKERS:
            add('fail', name, 'worker-allows-privileged-tool', sorted(allow & NEVER_FOR_WORKERS))
        if agent.get('spawn_targets'):
            add('fail', name, 'worker-can-spawn', agent['spawn_targets'])
        integrations = sorted(t for t in allow if t.endswith('__*'))
        if integrations:
            add('customer-blocker', name, 'worker-has-integration-tools',
                integrations + ['owner credentials must not exist in a customer cell'])
    for name, agent in agents.items():
        if name != 'researcher':
            leaked = sorted(t for t in agent.get('tools_allow', []) if t.endswith('__*'))
            if leaked:
                add('fail', name, 'integration-tools-researcher-only', leaked)
    critic = agents.get('critic')
    if critic and set(critic['tools_allow']) & {'write', 'edit', 'exec', 'process', 'apply_patch'}:
        add('fail', 'critic', 'critic-must-be-read-only', sorted(critic['tools_allow']))
    for name in BUILDERS & agents.keys():
        agent = agents[name]
        if agent.get('sandbox_mode') != 'all':
            add('fail', name, 'builder-sandbox', agent.get('sandbox_mode'))
        if set(agent['tools_allow']) & NEVER_FOR_BUILDERS:
            add('fail', name, 'builder-allows-network-or-control-tool',
                sorted(set(agent['tools_allow']) & NEVER_FOR_BUILDERS))
        missing = NEVER_FOR_BUILDERS - set(agent['tools_deny'])
        if missing:
            add('fail', name, 'builder-denies-control-tools', sorted(missing))
    main = agents.get('main')
    if main and main.get('sandbox_mode') == 'off':
        add('customer-blocker', 'main', 'orchestrator-unsandboxed',
            'unsandboxed main is acceptable only inside a verified customer cell (ACP/Claude Code cannot be spawned from a sandboxed session and run host-side)')
    if inventory.get('elevated_enabled'):
        add('customer-blocker', '*', 'global-elevated-enabled',
            'global elevated is enabled; per-agent denial exists but customer cells must disable it')
    if inventory.get('global_browser_enabled'):
        add('customer-blocker', '*', 'global-browser-enabled',
            'browser reachable only through browser-worker; confirm per-cell profile and no owner sign-ins')
    if inventory.get('session_visibility') not in {'tree', 'self'}:
        add('fail', '*', 'session-visibility', inventory.get('session_visibility'))
    return findings


def main(argv=None) -> int:
    path = Path(argv[0] if argv else Path(__file__).resolve().parents[2] / 'plans/product/capability-inventory.json')
    findings = check(json.loads(path.read_text()))
    print(json.dumps(findings, indent=1))
    return 1 if any(f['level'] == 'fail' for f in findings) else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
