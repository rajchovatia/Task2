#!/bin/bash
set -e

# Wait for the primary to be ready
echo "Waiting for PostgreSQL primary to be ready..."
until PGPASSWORD=$POSTGRES_PASSWORD pg_isready -h postgres-primary -p 5432 -U $POSTGRES_USER; do
    echo "Primary not ready yet, waiting..."
    sleep 2
done
echo "Primary is ready!"

# Check if data directory is already initialized
if [ -s "/var/lib/postgresql/data/PG_VERSION" ]; then
    echo "Replica data directory already initialized, starting PostgreSQL..."
else
    echo "Initializing replica from primary via pg_basebackup..."

    rm -rf /var/lib/postgresql/data/*

    PGPASSWORD=${REPLICATION_PASSWORD} pg_basebackup \
        -h postgres-primary \
        -p 5432 \
        -U replicator \
        -D /var/lib/postgresql/data \
        -Fp -Xs -P -R


    echo "Base backup complete, replica initialized."
fi

# Configure hot standby (only if not already configured)
if ! grep -q "hot_standby" /var/lib/postgresql/data/postgresql.auto.conf 2>/dev/null; then
    cat >> /var/lib/postgresql/data/postgresql.auto.conf <<EOF
hot_standby = on
primary_conninfo = 'host=postgres-primary port=5432 user=replicator password=${REPLICATION_PASSWORD}'
EOF
fi

# Ensure standby.signal exists
touch /var/lib/postgresql/data/standby.signal

echo "Starting PostgreSQL replica..."
# Fix permissions for postgres user
chown -R postgres:postgres /var/lib/postgresql/data
chmod 700 /var/lib/postgresql/data
exec gosu postgres postgres
