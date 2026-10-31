from django.db import migrations

SQL = """
CREATE TABLE safety_overrides(
  account_id TEXT NOT NULL,
  feature TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
  changed_by TEXT NOT NULL,
  changed_epoch INTEGER NOT NULL,
  expires_epoch INTEGER,
  PRIMARY KEY(account_id, feature)
);
"""


class Migration(migrations.Migration):
    dependencies = [('accounts', '0013_signup_token')]
    operations = [migrations.RunSQL(SQL, 'DROP TABLE safety_overrides;')]
