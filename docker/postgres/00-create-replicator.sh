#!/bin/bash
set -e

# Create replication user using env var for password
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'replicator') THEN
            CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD '${REPLICATION_PASSWORD}';
        END IF;
    END
    \$\$;
    GRANT ALL PRIVILEGES ON DATABASE "${POSTGRES_DB}" TO replicator;
EOSQL
