"""The privacy policy must keep telling the truth.

privacy/derive.py reads the facts the policy rests on out of the code; privacy/facts.json is the reviewed record of them; deploy/vercel/public/privacy.html is the
policy. These tests fail when any of the three drifts from the others. A failure is not a nuisance: it means "something the policy relies on changed, so a person must
check whether the policy still says the right thing". How to respond is in privacy/README.md.
"""
import json
from datetime import date, timedelta
from pathlib import Path
import re
import sys
import unittest

PLATFORM = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM / 'privacy'))
import check_server  # noqa: E402
import derive  # noqa: E402

FACTS = json.loads((PLATFORM / 'privacy' / 'facts.json').read_text())
POLICY = (PLATFORM / FACTS['policy_file']).read_text()
TEXT = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', re.sub(r'<style.*?</style>', ' ', POLICY, flags=re.S)))      # what a reader sees: no tags, no stylesheet
WORDS = re.sub(r'[\w.+-]+@[\w.-]+\.\w+', ' ', TEXT)                                                              # ...and without email addresses, so a contact address cannot trip a word check
HOWTO = 'Review privacy/README.md: decide whether the policy (deploy/vercel/public/privacy.html) must change, update it and privacy/facts.json together, and add a line to review_log.'


class CodeMatchesTheRecord(unittest.TestCase):
    def check(self, name, now, recorded):
        self.assertEqual(now, recorded, f'\n\nThe code now says something different about "{name}" than the reviewed record.\n  code:   {json.dumps(now, sort_keys=True)}\n  record: {json.dumps(recorded, sort_keys=True)}\n{HOWTO}')

    def test_retention(self):
        self.check('how long things are kept', derive.retention(), FACTS['derived']['retention'])

    def test_what_the_extension_can_do_and_keeps(self):
        self.check('the extension', derive.extension(), FACTS['derived']['extension'])

    def test_who_the_code_talks_to(self):
        now, recorded = derive.hosts(), sorted(FACTS['derived']['hosts'])
        self.check('the servers our code talks to (a new one may mean a new recipient of customer data)', now, recorded)
        self.assertEqual(sorted(FACTS['hosts_explained']), recorded, 'every host must be explained in hosts_explained, and nothing else')

    def test_how_the_assistant_reaches_the_outside(self):
        self.check('the assistant\'s plugins, search provider, MCP servers, switched-off tools and DNS servers', derive.assistant(), FACTS['derived']['assistant'])

    def test_every_outside_connection_of_the_assistant_has_a_named_recipient(self):
        a = FACTS['derived']['assistant']; mapped = FACTS['assistant_recipients']
        needed = [f'search_provider:{a["search_provider"]}'] + [f'plugin:{p}' for p in a['plugins']] + [f'dns:{ip}' for ip in a['dns_servers']]
        self.assertEqual([n for n in needed if n not in mapped], [], 'the assistant reaches something with no named recipient in assistant_recipients.\n' + HOWTO)
        if a.get('remote_mcp_connections'):
            self.assertIn('remote_mcp_connections', mapped, 'Customer-selected remote MCP recipients must be disclosed')
        self.assertEqual(a['mcp_servers'], ['lumina'], 'the assistant now has an outside MCP server: its operator would receive what the assistant sends it. Name it in the policy.\n' + HOWTO)

    def test_the_experimental_decider_stays_limited_to_the_owner(self):
        self.assertTrue(derive.owner_only_ultrafast(), 'OpenRouter is left out of the policy only because the experimental browser decider is limited to the owner\'s own account; that limit is gone.\n' + HOWTO)
        self.assertTrue(FACTS['derived']['owner_only_ultrafast'])

    def test_what_data_the_database_holds(self):
        s = derive.schema()
        self.check('the tables and columns that hold customer data (a new one may be new personal data)', s['sha256'], FACTS['derived']['schema_sha256'])
        self.assertEqual(s['count'], FACTS['derived']['schema_columns'])

    def test_the_cleanup_of_old_database_copies_works_on_the_names_the_release_tool_really_makes(self):
        self.assertTrue(derive.retention()['plaintext_snapshot_cleanup_matches_real_names'], 'the policy says copies made before updates are removed within 30 days; the cleanup pattern no longer matches the real file names')


class PolicyMatchesTheRecord(unittest.TestCase):
    def test_it_says_everything_the_record_says_it_must(self):
        missing = [p for p in FACTS['policy_must_say'] if p not in TEXT and p not in POLICY]
        self.assertEqual(missing, [], f'the policy no longer says: {missing}\n{HOWTO}')

    def test_it_stays_silent_about_things_that_are_not_live(self):
        said = [p for p in FACTS['policy_must_not_say'] if re.search(re.escape(p), WORDS, re.I)]
        self.assertEqual(said, [], f'the policy mentions things the record says it must not (not live, or an absolute promise we cannot keep): {said}')

    def test_the_numbers_in_the_policy_are_the_numbers_in_the_code(self):
        r = FACTS['derived']['retention']
        for statement in (f'{int(r["browse_pictures_and_trace_hours"])} hours', f'every {int(r["browse_purge_every_minutes"])} minutes', f'{r["encrypted_backups_max_days"]} days',
                          f'{r["plaintext_snapshots_max_days"]} days', f'{FACTS["server"]["journald_max_retention"].replace("day", " days")}',
                          f'{FACTS["derived"]["extension"]["max_controls_listed"]} controls', f'{FACTS["derived"]["extension"]["page_text_limit_chars"]:,} characters'):
            self.assertIn(statement, TEXT, f'the policy should say "{statement}"')
        self.assertEqual(FACTS['derived']['retention']['scheduled_retention_jobs'], [], 'a retention job is now scheduled in deploy/: the "kept until you ask us to delete them" row of the policy must change.\n' + HOWTO)

    def test_every_extension_permission_is_explained(self):
        for permission in FACTS['derived']['extension']['permissions']:
            self.assertIn(f'<code>{permission}</code>', POLICY, f'the policy must explain the "{permission}" permission')

    def test_every_recipient_of_customer_data_is_named(self):
        for host, info in FACTS['hosts_explained'].items():
            if info.get('in_policy'):
                self.assertIn(info['in_policy'], TEXT, f'{host} receives data ({info["why"]}) so the policy must name {info["in_policy"]}')
        for key, name in FACTS['assistant_recipients'].items():
            self.assertIn(name, TEXT, f'{key} sends data to {name}, so the policy must name {name}')
        for name in FACTS['recipients_not_visible_in_code']:
            self.assertTrue(re.search(re.escape(name.split(' (')[0]), TEXT, re.I) or name in ('email delivery (SMTP)', 'server hosting provider'), f'the policy must name {name}')
        self.assertIn('email provider', TEXT); self.assertIn('server hosting provider', TEXT)

    def test_a_host_that_gets_no_customer_data_is_not_in_the_policy(self):
        for host, info in FACTS['hosts_explained'].items():
            if not info['customer_data'] and not info.get('in_policy'):
                self.assertNotIn(info['who'].lower(), WORDS.lower(), f'{info["who"]} is not live, so the policy must not mention it')

    def test_the_date_and_the_contact_agree_with_the_record(self):
        d = date.fromisoformat(FACTS['policy_updated'])
        self.assertIn(f'Last updated {d.day} {d.strftime("%B %Y")}', TEXT)
        self.assertIn(f'mailto:{FACTS["contact_email"]}', POLICY)
        self.assertEqual(FACTS['review_log'][-1]['date'] >= FACTS['policy_updated'], True, 'add a review_log line whenever the policy changes')

    def test_the_page_is_self_contained_and_public(self):
        self.assertNotRegex(POLICY, r'<script', 'no scripts')
        self.assertEqual([u for u in re.findall(r'(?:src|href)="([^"]+)"', POLICY) if not (u.startswith('mailto:') or u == '/')], [], 'no outside resources: the page must load with nothing else')
        self.assertIn('<meta name="viewport"', POLICY)
        self.assertIn('privacy.html', (PLATFORM / 'deploy' / 'vercel' / 'build.mjs').read_text(), 'the Vercel build must publish the page')
        self.assertTrue(FACTS['policy_url'].endswith('/privacy'))

    def test_the_policy_is_reviewed_at_least_twice_a_year(self):
        age = date.today() - date.fromisoformat(FACTS['policy_updated'])
        self.assertLess(age, timedelta(days=200), f'the policy was last reviewed {age.days} days ago. Reread privacy.html against the code, then set policy_updated and add a review_log line.')

    def test_a_known_gap_cannot_outlive_its_deadline(self):
        gap = FACTS['server'].get('known_gap')
        if gap:
            deadline = date.fromisoformat(re.search(r'until (\d{4}-\d{2}-\d{2})', gap).group(1))
            self.assertLess(date.today(), deadline, f'deadline passed: {gap}\nDeploy the fix, run platform/privacy/check_server.py, then delete server.known_gap from facts.json.')


class ServerCheck(unittest.TestCase):
    """The pure part of privacy/check_server.py: given what the server reports, which promises hold?"""
    GOOD = {'journald_max_retention': '7day', 'timers': ['agentai-ops-backup.timer'], 'plaintext_snapshots': {'count': 3, 'oldest_days': 4},
            'encrypted_backups': {'count': 14, 'oldest_days': 13.7}, 'model_providers': ['anthropic'], 'uploads_on': False, 'telegram_configured': False, 'connectors_on': False, 'retention_job_scheduled': False}

    def levels(self, **change):
        return {m: l for l, m in check_server.evaluate({**self.GOOD, **change}, FACTS, today=date(2026, 11, 1))}

    def worst(self, **change):
        got = [l for l, _ in check_server.evaluate({**self.GOOD, **change}, FACTS)]
        return 'FAIL' if 'FAIL' in got else 'WARN' if 'WARN' in got else 'PASS'

    def test_a_healthy_server_passes_everything(self):
        self.assertEqual(self.worst(), 'PASS')

    def test_each_promise_fails_on_its_own(self):
        for what, change in {'logs kept longer': {'journald_max_retention': 'infinity'}, 'logs not capped': {'journald_max_retention': None}, 'no backups': {'timers': []},
                             'old encrypted backup': {'encrypted_backups': {'count': 20, 'oldest_days': 31}}, 'old plaintext copy': {'plaintext_snapshots': {'count': 3, 'oldest_days': 31}},
                             'a second model company': {'model_providers': ['anthropic', 'openai']}, 'models unreadable': {'model_providers': None}, 'uploads on': {'uploads_on': True}, 'telegram on': {'telegram_configured': True}, 'connectors on': {'connectors_on': True}}.items():
            self.assertEqual(self.worst(**change), 'FAIL', what)

    def test_too_many_copies_or_an_unexpected_retention_job_is_a_warning_not_a_failure(self):
        self.assertEqual(self.worst(plaintext_snapshots={'count': 38, 'oldest_days': 19}), 'WARN')
        self.assertEqual(self.worst(retention_job_scheduled=True), 'WARN')


if __name__ == '__main__':
    unittest.main()
