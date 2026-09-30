"""Expand explicit operator scopes while retaining database binding checks."""
from django.db import migrations

SQL = """
DROP TRIGGER grant_account_insert;
DROP TRIGGER grant_account_update;
CREATE TRIGGER grant_account_insert BEFORE INSERT ON accounts_operatorgrant
WHEN NEW.action NOT IN ('invite','suspend','revoke','audit','lifecycle_create','lifecycle_start','lifecycle_stop','lifecycle_upgrade','lifecycle_backup','lifecycle_restore','lifecycle_delete')
OR NOT EXISTS(SELECT 1 FROM accounts WHERE id=NEW.account_id)
OR NOT EXISTS(SELECT 1 FROM accounts_identity WHERE user_id=NEW.user_id AND role='operator' AND verified=1)
BEGIN SELECT RAISE(ABORT,'invalid operator grant'); END;
CREATE TRIGGER grant_account_update BEFORE UPDATE ON accounts_operatorgrant
WHEN NEW.action NOT IN ('invite','suspend','revoke','audit','lifecycle_create','lifecycle_start','lifecycle_stop','lifecycle_upgrade','lifecycle_backup','lifecycle_restore','lifecycle_delete')
OR NOT EXISTS(SELECT 1 FROM accounts WHERE id=NEW.account_id)
OR NOT EXISTS(SELECT 1 FROM accounts_identity WHERE user_id=NEW.user_id AND role='operator' AND verified=1)
BEGIN SELECT RAISE(ABORT,'invalid operator grant'); END;
"""
class Migration(migrations.Migration):
    dependencies = [('accounts','0005_alter_operatorgrant_action')]
    operations = [migrations.RunSQL(SQL)]
