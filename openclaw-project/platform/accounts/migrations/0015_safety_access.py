from django.db import migrations

SQL = """
CREATE TABLE safety_access(
  account_id TEXT PRIMARY KEY,
  granted_by TEXT NOT NULL,
  granted_epoch INTEGER NOT NULL
);
"""


class Migration(migrations.Migration):
    dependencies = [('accounts', '0014_safety_overrides')]
    operations = [migrations.RunSQL(SQL, 'DROP TABLE safety_access;')]
