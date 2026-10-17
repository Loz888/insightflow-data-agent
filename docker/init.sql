\getenv owner_password INSIGHTFLOW_OWNER_PASSWORD
\getenv reader_password INSIGHTFLOW_READER_PASSWORD
\getenv runtime_password INSIGHTFLOW_RUNTIME_PASSWORD
CREATE ROLE insightflow_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD :'owner_password';
CREATE ROLE insightflow_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD :'reader_password';
CREATE ROLE insightflow_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD :'runtime_password';
CREATE DATABASE insightflow_dev OWNER insightflow_owner;
CREATE DATABASE insightflow_test OWNER insightflow_owner;
REVOKE ALL ON DATABASE insightflow_dev,insightflow_test FROM PUBLIC;
GRANT CONNECT ON DATABASE insightflow_dev,insightflow_test TO insightflow_owner,insightflow_reader,insightflow_runtime;
ALTER ROLE insightflow_reader SET default_transaction_read_only=on;
ALTER ROLE insightflow_reader SET statement_timeout='1500ms';
ALTER ROLE insightflow_reader SET search_path=pg_catalog,business;
