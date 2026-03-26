#!/bin/bash
# Create separate databases for each environment.
# Mounted at /docker-entrypoint-initdb.d/
# Uses POSTGRES_DBS env var (comma-separated).

set -e
IFS=',' read -ra DBS <<< "${POSTGRES_DBS:-$POSTGRES_DB}"

for db in "${DBS[@]}"; do
    echo "Creating database: $db"
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
        CREATE DATABASE "$db" OWNER "$POSTGRES_USER";
EOSQL
done
