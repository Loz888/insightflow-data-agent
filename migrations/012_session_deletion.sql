ALTER TABLE agent_runtime.sessions ADD COLUMN IF NOT EXISTS deleted_at timestamptz;
CREATE TABLE IF NOT EXISTS agent_runtime.lifecycle_audit (
 event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 principal text NOT NULL,session_digest text NOT NULL,action text NOT NULL,
 at timestamptz NOT NULL DEFAULT clock_timestamp());
