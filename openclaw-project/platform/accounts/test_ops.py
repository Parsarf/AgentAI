from django.db import connection
from django.test import TestCase
from agentai_platform.ops.restore import SCOPE


class RestoreClassificationChecks(TestCase):
    def test_every_table_in_the_real_django_plus_platform_schema_has_a_restore_rule(self):
        with connection.cursor() as c:
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            names = [r[0] for r in c.fetchall()]
        self.assertEqual(sorted(n for n in names if n not in SCOPE), [], 'add a restore rule for every new table in agentai_platform/ops/restore.py')
        self.assertTrue({'accounts_identity', 'django_session', 'billing_subscriptions', 'usage_entries'} <= set(names))
