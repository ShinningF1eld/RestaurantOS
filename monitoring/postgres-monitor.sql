-- Run once as the database/role administrator against the ONE monitored database.
-- Set the password separately using psql's \password restaurantos_monitor; never
-- put it in command arguments, SQL history, this file, or source control.
-- No pg_monitor, pg_read_all_stats, pg_read_all_data or business-schema grants.
CREATE ROLE restaurantos_monitor LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 2;
GRANT CONNECT ON DATABASE :"DBNAME" TO restaurantos_monitor;
-- These views already have PUBLIC SELECT on a standard PostgreSQL 16 install.
-- Explicit grants also support installations which revoke those PUBLIC rights.
GRANT SELECT ON pg_catalog.pg_stat_database, pg_catalog.pg_stat_activity,
  pg_catalog.pg_locks, pg_catalog.pg_database, pg_catalog.pg_class
  TO restaurantos_monitor;
ALTER ROLE restaurantos_monitor SET default_transaction_read_only = on;
ALTER ROLE restaurantos_monitor SET statement_timeout = '1500ms';
ALTER ROLE restaurantos_monitor SET lock_timeout = '500ms';
ALTER ROLE restaurantos_monitor SET idle_in_transaction_session_timeout = '2s';
