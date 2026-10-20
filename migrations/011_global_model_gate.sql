CREATE TABLE IF NOT EXISTS agent_runtime.model_permits (
 permit_id uuid PRIMARY KEY,provider text NOT NULL,model text NOT NULL,tenant text NOT NULL,
 run_id uuid NOT NULL REFERENCES agent_runtime.runs(run_id),
 acquired_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 held_until timestamptz NOT NULL,outcome text NOT NULL DEFAULT 'uncertain');
CREATE INDEX IF NOT EXISTS model_permits_active ON agent_runtime.model_permits(provider,model,held_until);
