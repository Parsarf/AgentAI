"""Phase 6 exit gate 6: every control in the Inbox and the Calendar goes through the action pipeline. No route by which the web app changes a provider's data outside it:
the routes never reach an adapter or the connector's write, and only the write modules send a changing request to a provider."""
import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def functions(path):
    tree = ast.parse((ROOT / path).read_text())
    return {n.name: ast.get_source_segment((ROOT / path).read_text(), n) for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


class NoWayAroundThePipeline(unittest.TestCase):
    def test_the_dashboard_routes_change_a_provider_only_through_actions(self):
        source = (ROOT / 'accounts/hub.py').read_text()
        for forbidden in (r'\.write\(', r'\badapter\.', r'client\.open\(', r'\._send\(', r'\._post\(', r'\._patch\(', r'(?<![\w.])http\('):
            self.assertIsNone(re.search(forbidden, source), forbidden)             # a route never holds an adapter or a credential
        views = functions('accounts/hub.py')
        from accounts.route_actions import ROUTES
        changing = {path for path, action in ROUTES.items() if path.startswith('v1/hub/') and action == 'action.approve'}
        self.assertTrue({'v1/hub/events/create', 'v1/hub/events/change', 'v1/hub/events/cancel', 'v1/hub/events/respond', 'v1/hub/mail/send', 'v1/hub/mail/organize'} <= changing)
        routed = dict(re.findall(r"path\('(v1/hub/[^']+)', hubv\.(\w+)\)", (ROOT / 'accounts/urls.py').read_text()))
        self.assertTrue(changing <= set(routed), changing - set(routed))
        for path in sorted(changing):
            body = views[routed[path]]
            self.assertTrue(re.search(r'actions\.(direct|undo_direct|cancel)\(', body), f'{path} changes a provider outside the action pipeline')

    def test_only_the_write_modules_send_a_changing_request_to_a_provider(self):
        changing = re.compile(r"""['"](POST|PATCH|PUT|DELETE)['"]""")
        allowed = {'agentai_platform/google_calendar_writes.py', 'agentai_platform/google_mail_writes.py', 'agentai_platform/google_hub.py'}
        for path in sorted((ROOT / 'agentai_platform').glob('*.py')):
            rel = str(path.relative_to(ROOT))
            text = path.read_text()
            if 'googleapis.com' not in text and 'gmail' not in text.lower():
                continue
            if rel not in allowed:
                self.assertIsNone(changing.search(text), f'{rel} sends a changing request to a provider')
        google = (ROOT / 'agentai_platform/google_hub.py').read_text()
        for line in google.splitlines():                                         # the adapter itself: only the token exchange, renewal and revocation, and free/busy
            if changing.search(line) and 'def ' not in line:
                self.assertTrue(any(word in line for word in ('TOKEN_URL', 'revoke', 'token', "'POST', url", 'method')), line.strip()[:120])
