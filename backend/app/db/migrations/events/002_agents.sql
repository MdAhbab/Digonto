-- docs/database.md section 4: agent run history and the tool-call audit trail.

CREATE TABLE IF NOT EXISTS agent_runs (
  id            INTEGER PRIMARY KEY,
  public_id     TEXT NOT NULL UNIQUE,
  agent         TEXT NOT NULL CHECK (agent IN
                ('porter','prohori','khoji','shonchari','bicharok','lekhok','dalil')),
  user_id       INTEGER,
  trigger_event_id TEXT,
  status        TEXT NOT NULL CHECK (status IN ('queued','running','complete','failed','refused')),
  steps_used    INTEGER NOT NULL DEFAULT 0,
  max_steps     INTEGER NOT NULL DEFAULT 8,
  model_tag     TEXT,
  thinking      INTEGER NOT NULL DEFAULT 0 CHECK (thinking IN (0,1)),
  input_tokens  INTEGER,
  output_tokens INTEGER,
  latency_ms    INTEGER,
  error         TEXT,
  started_at    TEXT NOT NULL,
  finished_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_agent ON agent_runs(agent, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_user ON agent_runs(user_id, started_at DESC);

-- Every tool call, always. This is the agent audit trail. Arguments are
-- stored as a hash plus a redacted copy, never in full: see docs/database.md
-- section 4 for why (data minimisation even in an append-only audit log).
CREATE TABLE IF NOT EXISTS agent_tool_calls (
  id          INTEGER PRIMARY KEY,
  run_id      INTEGER NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  ordinal     INTEGER NOT NULL,
  tool_name   TEXT NOT NULL,
  args_hash   TEXT NOT NULL,
  args_redacted TEXT CHECK (args_redacted IS NULL OR json_valid(args_redacted)),
  result_hash TEXT,
  ok          INTEGER NOT NULL DEFAULT 1 CHECK (ok IN (0,1)),
  error       TEXT,
  latency_ms  INTEGER,
  called_at   TEXT NOT NULL,
  UNIQUE (run_id, ordinal)
);
