from django.db import migrations

SQL="""
CREATE UNIQUE INDEX identity_email_unique ON auth_user(lower(email));
CREATE TRIGGER identity_account_insert BEFORE INSERT ON accounts_identity
WHEN NEW.epoch<1 OR NEW.role NOT IN ('customer','operator','service') OR (NEW.role='customer' AND (NEW.account_id IS NULL OR NOT EXISTS(SELECT 1 FROM accounts WHERE id=NEW.account_id))) OR (NEW.role!='customer' AND NEW.account_id IS NOT NULL)
BEGIN SELECT RAISE(ABORT,'invalid identity binding'); END;
CREATE TRIGGER identity_account_update BEFORE UPDATE ON accounts_identity
WHEN NEW.epoch<1 OR NEW.role NOT IN ('customer','operator','service') OR (NEW.role='customer' AND (NEW.account_id IS NULL OR NOT EXISTS(SELECT 1 FROM accounts WHERE id=NEW.account_id))) OR (NEW.role!='customer' AND NEW.account_id IS NOT NULL)
BEGIN SELECT RAISE(ABORT,'invalid identity binding'); END;
CREATE TRIGGER grant_account_insert BEFORE INSERT ON accounts_operatorgrant
WHEN NEW.action NOT IN ('invite','suspend','revoke','audit') OR NOT EXISTS(SELECT 1 FROM accounts WHERE id=NEW.account_id) OR NOT EXISTS(SELECT 1 FROM accounts_identity WHERE user_id=NEW.user_id AND role='operator' AND verified=1)
BEGIN SELECT RAISE(ABORT,'invalid operator grant'); END;
CREATE TRIGGER grant_account_update BEFORE UPDATE ON accounts_operatorgrant
WHEN NEW.action NOT IN ('invite','suspend','revoke','audit') OR NOT EXISTS(SELECT 1 FROM accounts WHERE id=NEW.account_id) OR NOT EXISTS(SELECT 1 FROM accounts_identity WHERE user_id=NEW.user_id AND role='operator' AND verified=1)
BEGIN SELECT RAISE(ABORT,'invalid operator grant'); END;
CREATE TRIGGER identity_audit_no_update BEFORE UPDATE ON accounts_audit BEGIN SELECT RAISE(ABORT,'audit is append only'); END;
CREATE TRIGGER identity_audit_no_delete BEFORE DELETE ON accounts_audit BEGIN SELECT RAISE(ABORT,'audit is append only'); END;
CREATE TRIGGER identity_audit_binding BEFORE INSERT ON accounts_audit
WHEN NEW.outcome NOT IN ('pending','completed','denied','failed','uncertain') OR (NEW.account_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM accounts WHERE id=NEW.account_id))
BEGIN SELECT RAISE(ABORT,'invalid audit'); END;
CREATE TRIGGER token_purpose BEFORE INSERT ON accounts_actiontoken
WHEN NEW.purpose NOT IN ('onboarding','recovery') BEGIN SELECT RAISE(ABORT,'invalid token purpose'); END;
"""
class Migration(migrations.Migration):
    dependencies=[('accounts','0001_initial'),('auth','0012_alter_user_first_name_max_length')]
    operations=[migrations.RunSQL(SQL)]
