-- Legacy sessions retain explicit ownership; no adoption by pilot identities.
ALTER TABLE agent_runtime.sessions ADD COLUMN IF NOT EXISTS public_session_id text;
CREATE TABLE IF NOT EXISTS agent_runtime.api_tokens (
 token_hash text PRIMARY KEY CHECK(length(token_hash)=64),
 principal text NOT NULL, tenant text NOT NULL, datasource text NOT NULL,
 expires_at timestamptz NOT NULL, revoked_at timestamptz);
REVOKE ALL ON agent_runtime.api_tokens FROM PUBLIC;
