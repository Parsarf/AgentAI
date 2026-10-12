import hashlib
import json
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
PIN = json.loads((ROOT / 'plans/product/phase-12-typesafe-pin.json').read_text())


def ids(text, section):
    block = text[text.index(section + ':'):]
    nxt = re.search(r'\n[a-z]+:', block[len(section) + 1:])
    block = block[:len(section) + 1 + nxt.start()] if nxt else block
    return re.findall(r'^  - id: (\S+)', block, re.M)


class PinChecks(unittest.TestCase):
    def test_browser_config_matches_pin_and_is_disabled(self):
        cfg = json.loads((ROOT / 'browser-opt/config.json').read_text())
        self.assertEqual(cfg['model'], PIN['model'])
        self.assertEqual(cfg['endpoint'], PIN['endpoint']['url'])
        self.assertFalse(cfg['enabled'])
        self.assertNotIn('latest', cfg['model'])

    def test_research_constants_match_pin(self):
        js = (ROOT / 'research-opt/plugin/index.mjs').read_text()
        py = (ROOT / 'research-opt/adapter.py').read_text()
        for source in (js, py):
            self.assertIn('MODEL = "' + PIN['model'] + '"', source)
            self.assertIn('0.042 / 1_000_000', source)
        self.assertEqual(PIN['input_microusd_per_1000_tokens'], 42)

    def test_research_manifest_and_entry_contract(self):
        manifest = json.loads((ROOT / 'research-opt/plugin/openclaw.plugin.json').read_text())
        self.assertEqual(manifest['contracts']['agentToolResultMiddleware'], ['openclaw'])
        entry = (ROOT / 'research-opt/plugin/index.mjs').read_text()
        self.assertIn('runtimes: ["openclaw"], matcher: ["web_fetch"]', entry)
        self.assertIn('catch { return undefined; }', entry)     # fail-open wrapper
        self.assertTrue((ROOT / 'research-opt/diagnostics/registration_diagnostic.mjs').exists())


class FixtureChecks(unittest.TestCase):
    def test_browser_fixture_sets_are_separate(self):
        text = (ROOT / 'browser-opt/fixtures.yaml').read_text()
        dev, held = ids(text, 'dev'), ids(text, 'heldout')
        self.assertEqual((len(dev), len(held)), (10, 10))
        self.assertFalse(set(dev) & set(held))

    def test_browser_adversarial_cases_point_at_real_unit_tests(self):
        text = (ROOT / 'browser-opt/adversarial.yaml').read_text()
        cases = re.findall(r'unit_test: (\S+)', text)
        self.assertGreaterEqual(len(cases), 10)
        for ref in cases:
            file, _, name = ref.partition('::')
            source = (ROOT / 'browser-opt' / file).read_text()
            self.assertIn(name.split('::')[-1] if name else file, source, ref)

    def test_research_rubric_and_heldout_are_frozen(self):
        lock = json.loads((ROOT / 'research-opt/rubric.lock.json').read_text())
        self.assertEqual(lock['rubric_sha256'], hashlib.sha256((ROOT / 'research-opt/RUBRIC.md').read_bytes()).hexdigest())
        text = (ROOT / 'research-opt/fixtures.yaml').read_text()
        held = text[text.index('heldout:'):text.index('adversarial:')]
        self.assertEqual(lock['heldout_section_sha256'], hashlib.sha256(held.encode()).hexdigest())
        dev, hold, adv = ids(text, 'dev'), ids(text, 'heldout'), ids(text, 'adversarial')
        self.assertFalse(set(dev) & set(hold))
        self.assertGreaterEqual(len(adv), 6)
        self.assertIn('Browser reliability results say nothing', ' '.join((ROOT / 'research-opt/RUBRIC.md').read_text().split()))


class LedgerChecks(unittest.TestCase):
    def test_optional_requirements_remain_optional_and_pending_acceptance(self):
        req = {r['id']: r for r in json.loads((ROOT / 'plans/product/requirements.json').read_text())['requirements']}
        for rid in ('OPT-01', 'OPT-02'):
            self.assertEqual(req[rid]['release_scope'], 'optional')
            self.assertEqual(req[rid]['acceptance_phase'], 16)
            self.assertNotEqual(req[rid]['acceptance_result'], 'PASS')


if __name__ == '__main__':
    unittest.main()
