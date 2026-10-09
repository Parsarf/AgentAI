import copy
import json
from pathlib import Path
import unittest
from agentai_platform.policy_check import check

INVENTORY = json.loads((Path(__file__).resolve().parents[2] / 'plans/product/capability-inventory.json').read_text())


def levels(findings, level='fail'):
    return [f['rule'] for f in findings if f['level'] == level]


class PolicyChecks(unittest.TestCase):
    def test_recorded_inventory_has_no_policy_failures(self):
        self.assertEqual(levels(check(INVENTORY)), [])

    def test_recorded_customer_blockers_are_reported(self):
        blockers = set(levels(check(INVENTORY), 'customer-blocker'))
        self.assertEqual(blockers, {'worker-has-integration-tools', 'orchestrator-unsandboxed',
                                    'global-elevated-enabled', 'global-browser-enabled'})

    def mutate(self, agent, **changes):
        inv = copy.deepcopy(INVENTORY)
        entry = next(a for a in inv['agents'] if a['id'] == agent)
        entry.update(changes)
        return inv

    def test_worker_regressions_fail(self):
        researcher = next(a for a in INVENTORY['agents'] if a['id'] == 'researcher')
        self.assertIn('worker-denies-privileged-tools', levels(check(
            self.mutate('researcher', tools_deny=[t for t in researcher['tools_deny'] if t != 'cron']))))
        self.assertIn('worker-can-spawn', levels(check(self.mutate('browser-worker', spawn_targets=['main']))))
        self.assertIn('worker-allows-privileged-tool', levels(check(
            self.mutate('researcher', tools_allow=researcher['tools_allow'] + ['exec']))))
        self.assertIn('critic-must-be-read-only', levels(check(
            self.mutate('critic', tools_allow=['read', 'write']))))

    def test_connector_tools_on_other_agents_fail(self):
        critic = next(a for a in INVENTORY['agents'] if a['id'] == 'critic')
        self.assertIn('integration-tools-researcher-only', levels(check(
            self.mutate('critic', tools_allow=critic['tools_allow'] + ['google-readonly__*']))))
        self.assertIn('integration-tools-researcher-only', levels(check(
            self.mutate('codex-builder', tools_allow=['read', 'github-readonly__*']))))

    def test_builder_regressions_fail(self):
        builder = next(a for a in INVENTORY['agents'] if a['id'] == 'codex-builder')
        self.assertIn('builder-sandbox', levels(check(self.mutate('codex-builder', sandbox_mode='off'))))
        self.assertIn('builder-allows-network-or-control-tool', levels(check(
            self.mutate('codex-builder', tools_allow=builder['tools_allow'] + ['web_fetch']))))
        self.assertIn('builder-denies-control-tools', levels(check(
            self.mutate('codex-builder', tools_deny=[t for t in builder['tools_deny'] if t != 'message']))))


if __name__ == '__main__':
    unittest.main()
