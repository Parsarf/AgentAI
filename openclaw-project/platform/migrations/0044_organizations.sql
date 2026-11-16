-- Organizations (roadmap Phase 2, #12 to #15). An organization owns one or more people. Each person keeps their own account and their own assistant cell: isolation between the
-- members of an organization is exactly as strong as between two customers. Every existing account becomes an organization of one, with the same id, and its customer becomes the
-- owner. Nothing about ids, URLs or behaviour changes for a single-person organization. Additive: an older release ignores these tables and the new column.
CREATE TABLE organizations (
 id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '' CHECK(length(name)<=120),
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','deleting','deleted')),
 created_epoch INTEGER NOT NULL
);
CREATE TABLE organization_members (
 organization_id TEXT NOT NULL REFERENCES organizations(id), actor_id TEXT NOT NULL,
 account_id TEXT NOT NULL REFERENCES accounts(id),
 role TEXT NOT NULL CHECK(role IN ('owner','admin','member','viewer')),
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','removed')),
 created_epoch INTEGER NOT NULL, updated_epoch INTEGER NOT NULL,
 PRIMARY KEY(organization_id,actor_id)
);
CREATE UNIQUE INDEX organization_members_by_account ON organization_members(account_id,actor_id);
ALTER TABLE accounts ADD COLUMN organization_id TEXT;
INSERT INTO organizations(id,created_epoch) SELECT id,CAST(strftime('%s','now') AS INTEGER) FROM accounts;
UPDATE accounts SET organization_id=id;
INSERT INTO organization_members(organization_id,actor_id,account_id,role,status,created_epoch,updated_epoch)
 SELECT account_id,actor_id,account_id,'owner',CASE status WHEN 'active' THEN 'active' ELSE 'removed' END,CAST(strftime('%s','now') AS INTEGER),CAST(strftime('%s','now') AS INTEGER)
 FROM memberships WHERE role='customer';
-- An account made after this migration, by any code path (invitation, sign-up, a test), gets its organization of one the moment its customer is added. A person added to an
-- EXISTING organization has their member row written first by the code that adds them, so the INSERT OR IGNORE below leaves their role alone.
CREATE TRIGGER membership_gets_organization AFTER INSERT ON memberships WHEN NEW.role='customer' BEGIN
 INSERT OR IGNORE INTO organizations(id,created_epoch) SELECT NEW.account_id,CAST(strftime('%s','now') AS INTEGER) WHERE (SELECT organization_id FROM accounts WHERE id=NEW.account_id) IS NULL;
 UPDATE accounts SET organization_id=NEW.account_id WHERE id=NEW.account_id AND organization_id IS NULL;
 INSERT OR IGNORE INTO organization_members(organization_id,actor_id,account_id,role,status,created_epoch,updated_epoch)
  VALUES ((SELECT organization_id FROM accounts WHERE id=NEW.account_id),NEW.actor_id,NEW.account_id,'owner','active',CAST(strftime('%s','now') AS INTEGER),CAST(strftime('%s','now') AS INTEGER));
END;
-- Organization policy (#15): one row per setting an organization decides for its members. No row means "the member decides" (today's behaviour).
CREATE TABLE organization_policies (
 organization_id TEXT NOT NULL REFERENCES organizations(id), key TEXT NOT NULL CHECK(length(key) BETWEEN 1 AND 40),
 value_json TEXT NOT NULL CHECK(json_valid(value_json)), updated_by TEXT NOT NULL, updated_epoch INTEGER NOT NULL,
 PRIMARY KEY(organization_id,key)
);
