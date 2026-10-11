import json
import os
from pathlib import Path
import tempfile
import unittest
from agentai_platform.switches import SwitchStore, SwitchError, CATALOG, load_facts, kill_switches


class SwitchChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.path, self.facts = str(self.dir / 'switches.json'), str(self.dir / 'facts.json')
        self.now = 1000
        self.store = SwitchStore(self.path, facts_path=self.facts, clock=lambda: self.now)

    def facts_on(self, *names):
        Path(self.facts).write_text(json.dumps({n: True for n in names}))

    def test_everything_is_off_by_default_and_fails_closed(self):
        self.assertFalse(any(self.store.is_on(k) for k in CATALOG))
        self.assertFalse(SwitchStore(None).is_on('research_optimization'))
        Path(self.path).write_text('not json')
        self.assertFalse(self.store.is_on('research_optimization'))
        Path(self.path).write_text(json.dumps({'switches': {'research_optimization': {'on': 'yes'}}}))
        self.assertFalse(self.store.is_on('research_optimization'))     # only literal true counts
        self.assertFalse(self.store.is_on('no_such_switch'))

    def test_turning_on_needs_facts_and_confirmations_with_plain_reasons(self):
        with self.assertRaises(SwitchError) as r:
            self.store.set('research_optimization', True, 'owner')
        self.assertTrue(any('TypeSafe key' in x for x in r.exception.reasons))
        self.assertTrue(any(x.startswith('Confirm:') for x in r.exception.reasons))
        self.facts_on('typesafe_key_present', 'research_provenance')
        with self.assertRaises(SwitchError) as r:
            self.store.set('research_optimization', True, 'owner')
        self.assertEqual(len(r.exception.reasons), 1)
        self.store.confirm('research_optimization', 'data_handling', 'owner')
        after = self.store.set('research_optimization', True, 'owner')
        self.assertEqual((after['status'], after['changed_by']), ('on', 'owner'))
        self.assertTrue(self.store.is_on('research_optimization'))

    def test_turning_off_always_works_and_a_lost_fact_switches_it_off_in_effect(self):
        self.facts_on('typesafe_key_present', 'research_provenance')
        self.store.confirm('research_optimization', 'data_handling', 'owner')
        self.store.set('research_optimization', True, 'owner')
        Path(self.facts).write_text('{}')                       # prerequisite disappears
        self.assertFalse(self.store.is_on('research_optimization'))
        self.assertEqual(self.store.describe('research_optimization')['status'], 'on_but_blocked')
        self.assertFalse(self.store.set('research_optimization', False, 'owner')['recorded_on'])

    def test_locked_switches_cannot_be_turned_on_or_confirmed(self):
        for key in ('customer_schedules', 'claude_code_for_customers'):
            self.facts_on(*[f for s in CATALOG.values() for f, _ in s.needs])
            with self.assertRaises(SwitchError):
                self.store.set(key, True, 'owner')
            self.assertEqual(self.store.describe(key)['status'], 'locked')
        with self.assertRaises(SwitchError):
            self.store.confirm('customer_schedules', 'anything', 'owner')

    def test_unknown_ids_are_refused(self):
        with self.assertRaises(SwitchError):
            self.store.set('nonsense', True, 'owner')
        with self.assertRaises(SwitchError):
            self.store.confirm('research_optimization', 'not_a_confirmation', 'owner')

    def test_facts_only_true_counts_and_garbage_is_ignored(self):
        Path(self.facts).write_text(json.dumps({'a': True, 'b': 'true', 'c': 1, 'd': False}))
        self.assertEqual(load_facts(self.facts), {'a': True, 'b': False, 'c': False, 'd': False})
        Path(self.facts).write_text('[1,2]')
        self.assertEqual(load_facts(self.facts), {})
        self.assertEqual(load_facts(None), {})

    def test_write_is_atomic_readable_and_secret_free(self):
        self.store.confirm('connectors_linking', 'privacy_notice', 'owner')
        self.assertEqual(oct(os.stat(self.path).st_mode & 0o777), '0o644')
        self.assertEqual([p.name for p in self.dir.iterdir() if p.name.startswith('.switches-')], [])
        data = json.loads(Path(self.path).read_text())
        self.assertEqual(data['switches']['connectors_linking']['confirmations']['privacy_notice']['by'], 'owner')

    def test_unwritable_location_reports_instead_of_pretending(self):
        bad = SwitchStore('/proc/nonexistent/switches.json')
        with self.assertRaises(SwitchError):
            bad.confirm('connectors_linking', 'privacy_notice', 'owner')
        with self.assertRaises(SwitchError):
            SwitchStore(None).confirm('connectors_linking', 'privacy_notice', 'owner')

    def test_kill_switch_adapter_rereads_each_call(self):
        ks = kill_switches(self.store)
        self.assertEqual(ks(), {'browser': False, 'research': False})
        self.facts_on('typesafe_key_present', 'research_provenance')
        self.store.confirm('research_optimization', 'data_handling', 'o')
        self.store.set('research_optimization', True, 'o')
        self.assertEqual(ks(), {'browser': False, 'research': True})
        self.store.set('research_optimization', False, 'o')
        self.assertEqual(ks()['research'], False)

    def test_catalog_has_plain_language_and_honest_risk(self):
        for sw in CATALOG.values():
            self.assertTrue(sw.plain and sw.when_on and sw.cost_note)
            self.assertIn(sw.risk, {'low', 'high'})
            self.assertFalse(sw.locked and sw.confirmations)


if __name__ == '__main__':
    unittest.main()
