#!/usr/bin/env python3
"""Run the acceptance cases and refuse a change that breaks a workflow which worked before (roadmap #3, #4).

    python deploy/acceptance.py run                       # Tier A: every case, against the synthetic runtime (free, about 3 s)
    python deploy/acceptance.py run --case A-STOP         # one case
    python deploy/acceptance.py run --out results.json --baseline previous.json
    python deploy/acceptance.py list

Each case is a test in tests/test_acceptance.py with an id. The result file has one entry per case: passed or failed, seconds, and for a failure the kind of error and
where (never values). Exit codes: 0 all passed; 1 a case failed; 2 a case that PASSED in the baseline fails now (a regression: what a deploy must refuse); 3 a case in the
baseline no longer exists (a workflow lost its check). Tier B (the same idea against a real cell on the server) is deploy/p15_acceptance.py until it is folded in here.
"""
import argparse
import json
import sys
import time
import unittest
from pathlib import Path

PLATFORM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM))


class Recorder(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.rows, self._began = {}, {}

    def _id(self, test):
        return getattr(getattr(test, test._testMethodName), 'CASE', test._testMethodName)

    def startTest(self, test):
        super().startTest(test); self._began[self._id(test)] = time.monotonic()

    def _record(self, test, passed, err=None):
        row = {'passed': passed, 'seconds': round(time.monotonic() - self._began.get(self._id(test), time.monotonic()), 3), 'test': test._testMethodName}
        if err is not None:
            kind, _value, tb = err
            while tb is not None and tb.tb_next is not None and 'test_acceptance' not in tb.tb_frame.f_code.co_filename:
                tb = tb.tb_next
            row.update(error=kind.__name__, where=f'{Path(tb.tb_frame.f_code.co_filename).name}:{tb.tb_lineno}' if tb is not None else '')
        self.rows[self._id(test)] = row

    def addSuccess(self, test): super().addSuccess(test); self._record(test, True)
    def addFailure(self, test, err): super().addFailure(test, err); self._record(test, False, err)
    def addError(self, test, err): super().addError(test, err); self._record(test, False, err)


def run(case=None):
    from tests import test_acceptance
    names = [test_acceptance.CASES[case]] if case else sorted(test_acceptance.CASES.values())
    suite = unittest.TestSuite(test_acceptance.Acceptance(name) for name in names)
    recorder = Recorder()
    suite.run(recorder)
    return recorder.rows


def compare(rows, baseline):
    """-> (regressions, lost): cases that passed before and fail now; cases that existed before and are gone."""
    before = baseline.get('cases', {}) if isinstance(baseline, dict) else {}
    regressions = sorted(c for c, row in rows.items() if not row['passed'] and before.get(c, {}).get('passed'))
    lost = sorted(c for c, row in before.items() if row.get('passed') and c not in rows)
    return regressions, lost


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=['run', 'list'])
    parser.add_argument('--case'); parser.add_argument('--out'); parser.add_argument('--baseline')
    parser.add_argument('--write-baseline', help='write the list of cases that pass now (ids only) to this file: do it in the same change that adds or removes a case')
    args = parser.parse_args(argv)
    from tests import test_acceptance
    if args.command == 'list':
        for case in sorted(test_acceptance.CASES):
            print(case, '-', test_acceptance.CASES[case][5:].replace('_', ' '))
        return 0
    if args.case and args.case not in test_acceptance.CASES:
        print('unknown case', args.case, file=sys.stderr); return 64
    rows = run(args.case)
    from agentai_platform import versions
    result = {'tier': 'a', 'release': versions.release(), 'rules': versions.rules(), 'at': int(time.time()), 'cases': rows}
    for case in sorted(rows):
        row = rows[case]
        print(('PASS ' if row['passed'] else 'FAIL ') + case + (f"  ({row.get('error')} at {row.get('where')})" if not row['passed'] else ''))
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')
    failed = [c for c, row in rows.items() if not row['passed']]
    if args.write_baseline and not args.case:
        Path(args.write_baseline).write_text(json.dumps({'tier': 'a', 'cases': {c: {'passed': row['passed']} for c, row in sorted(rows.items())}}, indent=1, sort_keys=True) + '\n')
    if args.baseline and not args.case:
        try:
            baseline = json.loads(Path(args.baseline).read_text())
        except (OSError, ValueError):
            print('baseline unreadable: comparing with nothing', file=sys.stderr); baseline = {}
        regressions, lost = compare(rows, baseline)
        if regressions:
            print('REGRESSION (passed in the baseline, fails now): ' + ', '.join(regressions), file=sys.stderr); return 2
        if lost:
            print('LOST (in the baseline, no longer checked): ' + ', '.join(lost), file=sys.stderr); return 3
    print(f'{len(rows) - len(failed)} of {len(rows)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
