"""The checks have one definition (ci/run.sh). The workflow must run every part the script names, so a part can never be defined and then forgotten in CI."""
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT.parent / '.github' / 'workflows' / 'platform.yml').read_text()
SCRIPT = ROOT / 'ci' / 'run.sh'


def run(*args):
    return subprocess.run(['bash', str(SCRIPT), *args], capture_output=True, text=True, timeout=60).stdout.split('\n')


class Parts(unittest.TestCase):
    def test_the_workflow_runs_every_part_the_script_names(self):
        named = {p for p in run('parts') if p}
        in_matrix = set(re.search(r"part: \[('accounts 1 3'.*?)\]", WORKFLOW).group(1).replace("'", '').split(', '))
        self.assertEqual(named - {'lumina'}, in_matrix)
        self.assertIn('run: bash openclaw-project/ci/run.sh lumina', WORKFLOW)
        self.assertNotIn('unittest', WORKFLOW); self.assertNotIn('manage.py test', WORKFLOW)       # the workflow holds no test command of its own: only the script does

    def test_every_test_module_is_in_exactly_one_share(self):
        accounts = sorted('accounts.' + f.stem for f in (ROOT / 'platform' / 'accounts').glob('test*.py'))
        blocking = sorted('tests.' + line.strip() for line in (ROOT / 'platform' / 'tests' / 'ci_blocking.txt').read_text().splitlines() if line.strip())
        for kind, expected, count in (('accounts', accounts, 3), ('platform', blocking, 2)):
            shares = [run('share', kind, str(i), str(count))[0].split() for i in range(1, count + 1)]
            self.assertEqual(sorted(m for s in shares for m in s), expected, kind)                # all of them, none twice
            self.assertTrue(all(shares), kind)

    def test_a_repeat_run_is_skipped_only_for_identical_files_that_a_pull_request_already_passed(self):
        gate = (ROOT / 'ci' / 'already-tested.sh').read_text()
        for must in ('[ "${GITHUB_EVENT_NAME:-}" = "push" ] || no', "HEAD^{tree}", '^{tree}', 'status=success', 'select(.event=="pull_request")'):
            self.assertIn(must, gate)
        self.assertEqual(WORKFLOW.count("if: needs.gate.outputs.tested != 'true'"), 3)
        self.assertIn('branches: [main]', WORKFLOW)                                              # a branch push alone runs nothing; a pull request does
        out = subprocess.run(['bash', str(ROOT / 'ci' / 'already-tested.sh')], capture_output=True, text=True, timeout=30, env={'PATH': '/usr/bin:/bin', 'GITHUB_EVENT_NAME': 'pull_request'})
        self.assertEqual(out.stdout.strip(), 'tested=false')                                     # anything but a push to main: the full checks


if __name__ == '__main__':
    unittest.main()
