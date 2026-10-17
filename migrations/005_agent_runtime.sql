CREATE SCHEMA IF NOT EXISTS agent_runtime;
REVOKE ALL ON SCHEMA agent_runtime FROM PUBLIC;
CREATE TABLE IF NOT EXISTS agent_runtime.sessions (
 session_id text PRIMARY KEY, principal text NOT NULL, version bigint NOT NULL DEFAULT 0,
 constraints jsonb NOT NULL DEFAULT '{}', history jsonb NOT NULL DEFAULT '[]',
 active_run uuid, lease_owner uuid, lease_until timestamptz,
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE IF NOT EXISTS agent_runtime.runs (
 run_id uuid PRIMARY KEY, sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
 principal text NOT NULL, session_id text NOT NULL REFERENCES agent_runtime.sessions(session_id),
 idempotency_key text, request_hash text NOT NULL, question text NOT NULL,
 status text NOT NULL CHECK(status IN ('queued','running','succeeded','failed','cancelled','interrupted')),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 deadline timestamptz NOT NULL, expires_at timestamptz NOT NULL,
 cancel_requested boolean NOT NULL DEFAULT false, result jsonb,
 error_code text, started_at timestamptz, finished_at timestamptz,
 UNIQUE(principal,idempotency_key));
CREATE INDEX IF NOT EXISTS runs_session_queue ON agent_runtime.runs(session_id,sequence) WHERE status='queued';
CREATE TABLE IF NOT EXISTS agent_runtime.events (
 event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 run_id uuid NOT NULL REFERENCES agent_runtime.runs(run_id),
 stage text NOT NULL, payload jsonb NOT NULL DEFAULT '{}', at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE IF NOT EXISTS agent_runtime.experiments (
 experiment_id text PRIMARY KEY, budget numeric NOT NULL CHECK(budget>0 AND budget<=2),
 reserved numeric NOT NULL DEFAULT 0 CHECK(reserved>=0), attempts integer NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS agent_runtime.model_attempts (
 attempt_id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES agent_runtime.runs(run_id),
 experiment_id text NOT NULL REFERENCES agent_runtime.experiments(experiment_id),
 reservation numeric NOT NULL, input_tokens bigint, output_tokens bigint,
 usage_known boolean NOT NULL DEFAULT false, outcome text NOT NULL DEFAULT 'unknown',
 created_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE IF NOT EXISTS agent_runtime.schema_migrations (
 version text PRIMARY KEY, digest text NOT NULL, applied_at timestamptz NOT NULL DEFAULT clock_timestamp());
