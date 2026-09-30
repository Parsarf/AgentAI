CREATE TABLE lifecycle_cells (
 account_id TEXT PRIMARY KEY REFERENCES accounts(id), deployment_id TEXT NOT NULL UNIQUE,
 tenant_ref TEXT NOT NULL UNIQUE, profile_revision TEXT NOT NULL,
 observed_state TEXT NOT NULL DEFAULT 'absent' CHECK(observed_state IN ('absent','stopped','running','unknown')),
 FOREIGN KEY(account_id,deployment_id) REFERENCES deployments(account_id,id)
);
CREATE TABLE lifecycle_details (
 account_id TEXT NOT NULL, operation_id TEXT NOT NULL,
 target_profile TEXT NOT NULL, backup_ref TEXT,
 attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 3),
 fence INTEGER NOT NULL DEFAULT 0 CHECK(fence>=0), lease_owner TEXT,
 lease_until INTEGER, retry_safe INTEGER NOT NULL DEFAULT 0 CHECK(retry_safe IN (0,1)),
 error_code TEXT, updated_at INTEGER NOT NULL,
 PRIMARY KEY(account_id,operation_id),
 FOREIGN KEY(account_id,operation_id) REFERENCES operations(account_id,id)
);
CREATE TABLE lifecycle_backups (
 account_id TEXT NOT NULL, id TEXT NOT NULL, operation_id TEXT NOT NULL,
 generation INTEGER NOT NULL, profile_revision TEXT NOT NULL,
 PRIMARY KEY(account_id,id),
 FOREIGN KEY(account_id,operation_id) REFERENCES operations(account_id,id)
);
CREATE TABLE lifecycle_slot (
 id INTEGER PRIMARY KEY CHECK(id=1), account_id TEXT NOT NULL, deployment_id TEXT NOT NULL,
 operation_id TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('reserved','active','uncertain')),
 FOREIGN KEY(account_id,deployment_id) REFERENCES deployments(account_id,id),
 FOREIGN KEY(account_id,operation_id) REFERENCES operations(account_id,id)
);
CREATE INDEX lifecycle_pending ON operations(state,created_at,id);
