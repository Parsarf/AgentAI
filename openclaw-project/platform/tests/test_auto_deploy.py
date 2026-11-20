import importlib.machinery
import importlib.util
import io
import os
import tarfile
import tempfile
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / 'deploy' / 'agentai-deploy'
loader = importlib.machinery.SourceFileLoader('agentai_deploy', str(PATH))
spec = importlib.util.spec_from_loader('agentai_deploy', loader)
deploy = importlib.util.module_from_spec(spec)
loader.exec_module(deploy)
SHA = 'a' * 40


def archive(entries):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        for name, data, kind in entries:
            info = tarfile.TarInfo(name)
            if kind == 'file':
                info.size = len(data); tar.addfile(info, io.BytesIO(data))
            elif kind == 'link':
                info.type = tarfile.SYMTYPE; info.linkname = data; tar.addfile(info)
            elif kind == 'dir':
                info.type = tarfile.DIRTYPE; tar.addfile(info)
    return buf.getvalue()


class Command(unittest.TestCase):
    def test_only_the_two_exact_forms_are_accepted(self):
        self.assertEqual(deploy.parse_command(f'deploy {SHA}'), ('deploy', SHA))
        self.assertEqual(deploy.parse_command(f'deploy-dry {SHA}'), ('deploy-dry', SHA))
        for bad in ('', None, 'bash', f'deploy {SHA}; id', f'deploy {SHA} extra', f'deploy {SHA[:39]}', f'deploy {"A" * 40}', f'deploy ../{SHA}',
                    f'deploy {SHA}\nid', f' deploy {SHA}', f'rm -rf / {SHA}', 'deploy $(id)'):
            self.assertIsNone(deploy.parse_command(bad), bad)


class Archive(unittest.TestCase):
    def test_normal_files_are_unpacked(self):
        with tempfile.TemporaryDirectory() as d:
            deploy.safe_extract(archive([('a/b.txt', b'hi', 'file'), ('c', None, 'dir')]), d)
            self.assertEqual((Path(d) / 'a/b.txt').read_bytes(), b'hi')

    def test_anything_that_could_escape_the_folder_is_refused(self):
        for entries in ([('../evil', b'x', 'file')], [('/etc/evil', b'x', 'file')], [('a/../../evil', b'x', 'file')], [('link', '/etc', 'link')], [('l', '../x', 'link')]):
            with tempfile.TemporaryDirectory() as d:
                with self.assertRaises(ValueError, msg=entries[0][0]):
                    deploy.safe_extract(archive(entries), d)
                self.assertEqual(list(Path(d).iterdir()), [])

    def test_an_oversized_upload_is_refused(self):
        with self.assertRaises(ValueError):
            deploy.read_stream(io.BytesIO(b'0' * (deploy.MAX_BYTES + 1)))


class Drift(unittest.TestCase):
    def tree(self, root, name, recorded):
        d = Path(root) / name / 'current'; d.mkdir(parents=True)
        import json
        (d / 'RELEASE.json').write_text(json.dumps({'source_sha256': recorded}))
        return Path(root) / name

    def test_files_released_by_hand_must_be_in_the_incoming_code_unchanged(self):
        import hashlib
        with tempfile.TemporaryDirectory() as root:
            plat = Path(root) / 'plat'; (plat / 'a').mkdir(parents=True)
            (plat / 'a/same.py').write_text('1'); (plat / 'a/changed.py').write_text('NEW')
            h = lambda t: hashlib.sha256(t.encode()).hexdigest()
            app = self.tree(root, 'app', {'a/same.py': h('1'), 'a/changed.py': h('OLD'), 'a/gone.py': h('x'), '../evil': h('x')})
            sup = self.tree(root, 'sup', {'a/same.py': h('1')})
            self.assertEqual(deploy.drift([app, sup], plat), ['app: a/changed.py', 'app: a/gone.py'])
            self.assertEqual(deploy.drift([sup], plat), [])

    def test_a_finished_deploy_forgets_the_manual_record_so_later_commits_are_not_refused(self):
        import hashlib, json
        with tempfile.TemporaryDirectory() as root:
            plat = Path(root) / 'plat'; (plat / 'a').mkdir(parents=True); (plat / 'a/file.py').write_text('COMMITTED')
            app = self.tree(root, 'app', {'a/file.py': hashlib.sha256(b'HAND MADE').hexdigest()})
            record = app / 'current' / 'RELEASE.json'
            record.write_text(json.dumps({'source_sha256': json.loads(record.read_text())['source_sha256'], 'commit': 'abc', 'purpose': 'kept'}))
            self.assertEqual(deploy.drift([app], plat), ['app: a/file.py'])            # before: the hand-made file would be undone
            deploy.forget_manual([app, Path(root) / 'missing'])
            self.assertEqual(json.loads(record.read_text()), {'commit': 'abc', 'purpose': 'kept'})
            (plat / 'a/file.py').write_text('A LATER COMMIT')
            self.assertEqual(deploy.drift([app], plat), [])                            # after: a later change to the same file is an ordinary change

    def test_a_tree_without_a_record_has_no_drift(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(deploy.drift([Path(root) / 'nothing'], root), [])


class SelfInstall(unittest.TestCase):
    def test_the_installed_program_follows_the_deployed_commit(self):
        with tempfile.TemporaryDirectory() as root:
            plat = Path(root) / 'plat'; (plat / 'deploy').mkdir(parents=True)
            installed = Path(root) / 'sbin' / 'agentai-deploy'; installed.parent.mkdir()
            installed.write_text('#!/usr/bin/env python3\nold = 1\n')
            (plat / 'deploy' / 'agentai-deploy').write_text('#!/usr/bin/env python3\nnew = 2\n')
            self.assertTrue(deploy.install_self(plat, installed))
            self.assertIn('new = 2', installed.read_text())
            self.assertEqual(installed.stat().st_mode & 0o777, 0o755)
            self.assertFalse(deploy.install_self(plat, installed))                     # already the same: nothing to do
            self.assertEqual([p.name for p in installed.parent.iterdir()], ['agentai-deploy'])      # no temporary file left behind

    def test_a_program_that_does_not_parse_or_is_missing_is_never_installed(self):
        with tempfile.TemporaryDirectory() as root:
            plat = Path(root) / 'plat'; (plat / 'deploy').mkdir(parents=True)
            installed = Path(root) / 'agentai-deploy'; installed.write_text('#!/usr/bin/env python3\nold = 1\n')
            self.assertFalse(deploy.install_self(plat, installed))                     # the commit has no deploy program
            for bad in ('#!/usr/bin/env python3\ndef broken(:\n', 'not a script\n'):
                (plat / 'deploy' / 'agentai-deploy').write_text(bad)
                self.assertFalse(deploy.install_self(plat, installed), bad)
                self.assertIn('old = 1', installed.read_text())

    def test_the_lifecycle_worker_is_restarted_with_the_other_services_and_the_supervisor_is_not(self):
        self.assertIn('agentai-lifecycle-worker', deploy.UNITS)
        self.assertNotIn('agentai-supervisor-native', deploy.UNITS)

    def test_the_supervisor_runs_the_new_release_too_but_is_never_restarted_under_a_cell_operation(self):
        # It sets up every cell (tool hook, configuration, rules). Never restarted by a deploy, it ran the code of 15 November until 2026-11-20.
        ran = []
        self.assertTrue(deploy.restart_supervisor_when_idle(idle=lambda: True, run=ran.append))
        self.assertEqual(ran, [['systemctl', 'restart', 'agentai-supervisor-native']])
        ran.clear()
        self.assertFalse(deploy.restart_supervisor_when_idle(idle=lambda: False, run=ran.append))
        self.assertEqual(ran, [])
        import sqlite3, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'p.sqlite3'
            con = sqlite3.connect(db); con.execute('CREATE TABLE operations (state TEXT)'); con.execute("INSERT INTO operations VALUES ('completed')"); con.commit()
            self.assertTrue(deploy.supervisor_idle(db))
            con.execute("INSERT INTO operations VALUES ('running')"); con.commit(); con.close()
            self.assertFalse(deploy.supervisor_idle(db))
            self.assertFalse(deploy.supervisor_idle(Path(tmp) / 'missing.sqlite3'))          # unreadable: not idle, so not restarted


class Layout(unittest.TestCase):
    def test_the_required_paths_exist_in_the_repository(self):
        platform = Path(__file__).resolve().parents[1]
        for name in deploy.REQUIRED:
            self.assertTrue((platform / name).exists(), name)
        self.assertTrue((platform / deploy.RELEASE_PY).is_file())

    def test_the_restart_list_is_services_that_exist(self):
        platform = Path(__file__).resolve().parents[1]
        for unit in deploy.UNITS:
            self.assertTrue((platform / 'deploy' / f'{unit}.service').is_file(), unit)



class ProofsBeforeGoingLive(unittest.TestCase):
    """A release proves itself on a COPY of the database before anything live changes (deploy/release.py). What it found after going live on 2026-11-16 (twice) it now finds first."""
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('release_procedure', PATH.parent / 'release.py')
        cls.release = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.release)
        cls.source = (PATH.parent / 'release.py').read_text()

    def test_a_result_is_read_from_the_gates_and_never_from_what_they_printed_about_data(self):
        good = b'PASS  P2-ROLES  An account is an organization of one  -- role=owner\nPASS  P3-PARTIAL  A partial result is stated  -- count=50\n{"passed": true}\n'
        self.assertEqual(self.release.proof_result(0, good, b''), (True, '2 gates passed'))
        bad = b'PASS  P2-ROLES  ok\nFAIL  P2-OFFBOARD  The disposable account is offboarded  -- {"found": {"auth_user": 1}, "who": "someone@example.test"}\n'
        passed, why = self.release.proof_result(1, bad, b'')
        self.assertEqual((passed, why), (False, 'FAIL  P2-OFFBOARD  The disposable account is offboarded'))
        self.assertEqual(self.release.proof_result(2, b'NOT RUN: turn on the owner switch(es) synthetic_connector.\n', b'')[0], False)
        self.assertEqual(self.release.proof_result(1, b'', b'Traceback\nValueError: boom\n'), (False, 'the proof script ended with an error: ValueError: boom'))
        self.assertEqual(self.release.proof_result(0, b'', b''), (False, 'the proof script printed no result'))          # silence is never a pass
        self.assertEqual(self.release.proof_result(0, b'FAIL  P3-HANDOFF  x\n', b'')[0], False)                          # nor is a clean exit with a failed gate

    def test_the_proofs_run_on_the_copy_after_the_canary_and_before_any_live_change(self):
        canary, proofs, live = (self.source.index(text) for text in ("step('new release passes its canary probes on the copy'", 'proven, detail = canary.prove()', 'return apply_live('))
        self.assertTrue(canary < proofs < live)
        self.assertIn("if not proven: shutil.rmtree(new, ignore_errors=True); return finish(report, 1)", self.source)
        self.assertIn("'deploy/phase23_live.py', '--copy'", self.source)
        proof = (PATH.parent / 'phase23_live.py').read_text()
        self.assertIn("COPY = '--copy' in sys.argv", proof)
        self.assertNotIn("/opt/agentai-platform/current')", proof.split('import django')[0])      # it proves the release it is part of, not whichever one is live

if __name__ == '__main__':
    unittest.main()


class LiveAcceptance(unittest.TestCase):
    """Tier B after every deploy: a failure puts the previous release back."""
    def tree(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(os.path.realpath(tmp.name))      # (macOS puts temp folders behind a /private symlink: compare real paths)
        for tree in ('app', 'sup'):
            for release in ('old', 'new'):
                (root / tree / 'releases' / release).mkdir(parents=True)
            os.symlink(root / tree / 'releases' / 'new', root / tree / 'current')
        (root / 'ui').mkdir(); (root / 'ui' / 'index.html').write_text('new')
        (root / 'ui.prev').mkdir(); (root / 'ui.prev' / 'index.html').write_text('old')
        (root / 'base').mkdir()
        previous = {'sha': SHA, 'previous_sha': 'b' * 40, 'old_app': str(root / 'app' / 'releases' / 'old'), 'old_sup': str(root / 'sup' / 'releases' / 'old'), 'ui_replaced': True}
        return root, previous

    def test_a_rollback_switches_both_trees_the_web_bundle_and_the_recorded_commit_back_and_restarts_the_services(self):
        root, previous = self.tree()
        ran = []
        done = deploy.rollback(previous, run=lambda argv: ran.append(argv), base=root / 'base', app=root / 'app', sup=root / 'sup', ui_parent=root)
        self.assertEqual(os.path.realpath(root / 'app' / 'current'), str(root / 'app' / 'releases' / 'old'))
        self.assertEqual(os.path.realpath(root / 'sup' / 'current'), str(root / 'sup' / 'releases' / 'old'))
        self.assertEqual((root / 'ui' / 'index.html').read_text(), 'old')
        self.assertEqual((root / 'base' / 'last').read_text().strip(), 'b' * 40)
        self.assertEqual(ran, [['systemctl', 'restart', *deploy.UNITS, *deploy.APP_UNITS], ['systemctl', 'try-restart', *deploy.OPTIONAL_UNITS]])      # the render service and the knowledge worker run release code too
        self.assertTrue(any('web app bundle restored' in d for d in done))

    def test_a_rollback_to_a_release_that_is_not_there_changes_nothing(self):
        root, previous = self.tree()
        previous['old_sup'] = str(root / 'sup' / 'releases' / 'gone')
        ran = []
        with self.assertRaises(ValueError):
            deploy.rollback(previous, run=lambda argv: ran.append(argv), base=root / 'base', app=root / 'app', sup=root / 'sup', ui_parent=root)
        self.assertEqual(ran, [])

    def fake(self, root, *, passed, returncode=0):
        class Result:
            pass
        calls = []
        def run(argv):
            calls.append(argv)
            result = Result(); result.returncode = returncode
            result.stdout = '{"passed": %s, "cases": [{"id": "LIVE-ANSWER", "passed": %s}]}\n' % (str(passed).lower(), str(passed).lower()) if argv[0] == 'systemd-run' else ''
            result.stderr = ''
            return result
        return run, calls

    def patched(self, root, previous):
        (root / 'base' / 'last').write_text(SHA + '\n')
        (root / 'base' / 'previous.json').write_text(__import__('json').dumps(previous))
        saved = (deploy.LAST, deploy.PREVIOUS, deploy.TIERB, deploy.LOG, deploy.BASE, deploy.APP, deploy.SUP, deploy.UI_PARENT)
        deploy.LAST, deploy.PREVIOUS, deploy.TIERB, deploy.LOG, deploy.BASE = root / 'base' / 'last', root / 'base' / 'previous.json', root / 'base' / 'tierb.json', root / 'base' / 'log', root / 'base'
        deploy.APP, deploy.SUP, deploy.UI_PARENT = root / 'app', root / 'sup', root
        self.addCleanup(lambda: (setattr(deploy, 'LAST', saved[0]), setattr(deploy, 'PREVIOUS', saved[1]), setattr(deploy, 'TIERB', saved[2]), setattr(deploy, 'LOG', saved[3]),
                                 setattr(deploy, 'BASE', saved[4]), setattr(deploy, 'APP', saved[5]), setattr(deploy, 'SUP', saved[6]), setattr(deploy, 'UI_PARENT', saved[7])))
        (root / 'app' / 'releases' / 'new' / 'deploy').mkdir()

    def test_a_passing_acceptance_is_recorded_and_the_release_stays(self):
        root, previous = self.tree(); self.patched(root, previous)
        run, calls = self.fake(root, passed=True)
        self.assertEqual(deploy.accept(SHA, run=run), 0)
        self.assertTrue(__import__('json').loads(deploy.TIERB.read_text())['passed'])
        self.assertEqual(os.path.realpath(root / 'app' / 'current'), str(root / 'app' / 'releases' / 'new'))
        self.assertEqual([c[0] for c in calls], ['systemd-run'])

    def test_a_failing_acceptance_puts_the_previous_release_back_and_exits_40(self):
        root, previous = self.tree(); self.patched(root, previous)
        run, calls = self.fake(root, passed=False)
        self.assertEqual(deploy.accept(SHA, run=run), 40)
        self.assertFalse(__import__('json').loads(deploy.TIERB.read_text())['passed'])
        self.assertEqual(os.path.realpath(root / 'app' / 'current'), str(root / 'app' / 'releases' / 'old'))
        self.assertEqual(deploy.LAST.read_text().strip(), 'b' * 40)
        self.assertIn('systemctl', [c[0] for c in calls])

    def test_a_crashed_acceptance_counts_as_a_failure(self):
        root, previous = self.tree(); self.patched(root, previous)
        run, _ = self.fake(root, passed=True, returncode=1)
        self.assertEqual(deploy.accept(SHA, run=run), 40)

    def test_an_acceptance_that_could_not_be_checked_keeps_the_release_and_exits_42(self):
        root, previous = self.tree(); self.patched(root, previous)
        class Result:
            returncode, stderr = 3, ''
            stdout = '{"passed": false, "inconclusive": true, "why": "the model provider was too busy to answer", "cases": []}\n'
        calls = []
        def run(argv):
            calls.append(argv)
            return Result()
        self.assertEqual(deploy.accept(SHA, run=run), 42)
        self.assertEqual(os.path.realpath(root / 'app' / 'current'), str(root / 'app' / 'releases' / 'new'))          # nothing was rolled back
        self.assertEqual(deploy.LAST.read_text().strip(), SHA)
        self.assertEqual([c[0] for c in calls], ['systemd-run'])
        recorded = __import__('json').loads(deploy.TIERB.read_text())
        self.assertEqual((recorded['passed'], recorded['inconclusive']), (False, True))

    def test_a_failed_check_that_only_claims_to_be_unchecked_is_still_rolled_back(self):
        root, previous = self.tree(); self.patched(root, previous)
        class Result:
            returncode, stderr = 1, ''
            stdout = '{"passed": false, "inconclusive": true, "cases": []}\n'
        self.assertEqual(deploy.accept(SHA, run=lambda argv: Result()), 40)

    def test_accepting_a_commit_that_is_not_the_deployed_one_is_refused(self):
        root, previous = self.tree(); self.patched(root, previous)
        run, calls = self.fake(root, passed=True)
        self.assertEqual(deploy.accept('c' * 40, run=run), 41)
        self.assertEqual(calls, [])

    def test_accept_is_one_of_the_three_exact_commands(self):
        self.assertEqual(deploy.parse_command(f'accept {SHA}'), ('accept', SHA))
        for bad in (f'accept {SHA}; id', 'accept', f'accept {SHA[:39]}'):
            self.assertIsNone(deploy.parse_command(bad), bad)
