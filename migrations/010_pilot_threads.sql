ALTER TABLE agent_runtime.runs ADD COLUMN IF NOT EXISTS resume_count integer NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS agent_runtime.graph_threads (
 run_id uuid PRIMARY KEY REFERENCES agent_runtime.runs(run_id),
 principal text NOT NULL, thread_id text NOT NULL UNIQUE,
 workflow_version text NOT NULL, base_version bigint NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp());
