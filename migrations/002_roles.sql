-- Run as the dedicated owner, never as the runtime reader.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA business FROM PUBLIC;
GRANT USAGE ON SCHEMA business TO insightflow_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA business TO insightflow_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA business GRANT SELECT ON TABLES TO insightflow_reader;
