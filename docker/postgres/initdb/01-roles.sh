#!/bin/bash
# Runs once, when the PostgreSQL data volume is first initialized.
#
# Least privilege (ADR-014):
#   postgres        superuser, administration only; PulseOps never uses it
#   pulseops_owner  owns the databases and their schema; used by migrations
#   pulseops_app    used by the API and the worker; rows only, no DDL
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
    -v owner_password="$PULSEOPS_OWNER_PASSWORD" \
    -v app_password="$PULSEOPS_APP_PASSWORD" <<-'EOSQL'
	CREATE ROLE pulseops_owner LOGIN PASSWORD :'owner_password';
	CREATE ROLE pulseops_app LOGIN PASSWORD :'app_password';
EOSQL

# pulseops_test mirrors pulseops so tests run with the same roles and
# privileges, without ever touching development data.
for db in pulseops pulseops_test; do
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
        -v db="$db" <<-'EOSQL'
		CREATE DATABASE :"db" OWNER pulseops_owner;
		REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
		GRANT CONNECT ON DATABASE :"db" TO pulseops_app;
	EOSQL

    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<-'EOSQL'
		GRANT USAGE ON SCHEMA public TO pulseops_app;
		-- Whatever pulseops_owner creates from now on (tables, identity
		-- sequences) is automatically usable by pulseops_app, rows only.
		ALTER DEFAULT PRIVILEGES FOR ROLE pulseops_owner IN SCHEMA public
		    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO pulseops_app;
		ALTER DEFAULT PRIVILEGES FOR ROLE pulseops_owner IN SCHEMA public
		    GRANT USAGE, SELECT ON SEQUENCES TO pulseops_app;
	EOSQL
done
