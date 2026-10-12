-- JEV routing telemetry. Shadow mode records what the router WOULD have chosen; nothing here changes execution.
CREATE TABLE route_decisions (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  request_id TEXT NOT NULL,
  mode TEXT NOT NULL CHECK(mode IN ('shadow','canary','live')),
  status TEXT NOT NULL CHECK(status IN ('classified','unavailable','rejected')),
  jev_route TEXT, route_confidence REAL, risk TEXT, complexity TEXT,
  policy_route TEXT, policy_action TEXT, requires_approval INTEGER, reasons TEXT,
  actual_route TEXT NOT NULL,
  latency_ms INTEGER, input_tokens INTEGER, output_tokens INTEGER,
  est_cost_microusd INTEGER, price_version TEXT,
  outcome TEXT, task_cost_microusd INTEGER, task_seconds INTEGER,
  created_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id, request_id)
);
CREATE INDEX route_decisions_time ON route_decisions(created_epoch);
