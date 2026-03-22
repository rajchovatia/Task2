#!/bin/bash
set -e

echo "Waiting for PostgreSQL to be ready..."
while ! python -c "
import os, psycopg
try:
    conn = psycopg.connect(
        dbname=os.getenv('POSTGRES_DB', 'RNS'),
        user=os.getenv('POSTGRES_USER', 'postgres'),
        password=os.environ['POSTGRES_PASSWORD'],
        host=os.getenv('POSTGRES_HOST', 'localhost'),
        port=os.getenv('POSTGRES_PORT', '5432'),
    )
    conn.close()
except Exception:
    exit(1)
" 2>/dev/null; do
    echo "PostgreSQL not ready, waiting 2s..."
    sleep 2
done
echo "PostgreSQL is ready!"

echo "Running migrations..."
python manage.py migrate --noinput
echo "Migrations complete!"

echo "Starting: $@"
exec "$@"
