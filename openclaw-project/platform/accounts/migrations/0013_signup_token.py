from django.db import migrations

SQL = """
DROP TRIGGER token_purpose;
CREATE TRIGGER token_purpose BEFORE INSERT ON accounts_actiontoken
WHEN NEW.purpose NOT IN ('onboarding','recovery','signup') BEGIN SELECT RAISE(ABORT,'invalid token purpose'); END;
"""
REVERSE = """
DROP TRIGGER token_purpose;
CREATE TRIGGER token_purpose BEFORE INSERT ON accounts_actiontoken
WHEN NEW.purpose NOT IN ('onboarding','recovery') BEGIN SELECT RAISE(ABORT,'invalid token purpose'); END;
"""


class Migration(migrations.Migration):
    dependencies = [('accounts', '0012_event_streams')]
    operations = [migrations.RunSQL(SQL, REVERSE)]
