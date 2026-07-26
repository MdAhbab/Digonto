-- docs/database.md section 4: request-level metrics for latency reporting.

CREATE TABLE IF NOT EXISTS request_metrics (
  id            INTEGER PRIMARY KEY,
  route         TEXT NOT NULL,
  method        TEXT NOT NULL,
  status        INTEGER NOT NULL,
  latency_ms    INTEGER NOT NULL,
  cache_hit     INTEGER NOT NULL DEFAULT 0 CHECK (cache_hit IN (0,1)),
  kb_version_id INTEGER,
  created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metrics_route_time ON request_metrics(route, created_at DESC);
