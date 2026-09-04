CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ticketing_metrics') THEN
        CREATE ROLE ticketing_metrics
            LOGIN
            PASSWORD 'ticketing_metrics_dev';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE ticketing TO ticketing_metrics;
GRANT pg_monitor TO ticketing_metrics;
REVOKE CREATE ON SCHEMA public FROM ticketing_metrics;
