-- Existing documents remain readable; metadata is created lazily on the first write.
CREATE TABLE gen_artifact_state (
 account_id TEXT NOT NULL, artifact_id TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
 state_revision INTEGER NOT NULL DEFAULT 1, state_json TEXT NOT NULL DEFAULT '{}',
 PRIMARY KEY(account_id,artifact_id),
 FOREIGN KEY(account_id,artifact_id) REFERENCES data_blocks(account_id,id) ON DELETE CASCADE
);
CREATE TABLE gen_artifact_events (
 account_id TEXT NOT NULL, id TEXT NOT NULL, artifact_id TEXT NOT NULL, actor_id TEXT NOT NULL,
 conversation_id TEXT NOT NULL, node_id TEXT NOT NULL, action_id TEXT NOT NULL,
 version INTEGER NOT NULL, payload_json TEXT NOT NULL, status TEXT NOT NULL,
 result_json TEXT, created_epoch INTEGER NOT NULL,
 PRIMARY KEY(account_id,id),
 FOREIGN KEY(account_id,artifact_id) REFERENCES data_blocks(account_id,id) ON DELETE CASCADE
);
