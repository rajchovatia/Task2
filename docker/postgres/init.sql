-- ============================================================
-- PostgreSQL Initialization Script
-- Replication user is created by 00-create-replicator.sh
-- ============================================================

-- ============================================================
-- Table Partitioning Setup
-- Monthly partitions on notifications table
-- Django creates the table first via migrations, then we
-- convert it to a partitioned table via a management command
-- or this init script creates the partition function/trigger
-- ============================================================

-- Function to auto-create monthly partitions
CREATE OR REPLACE FUNCTION create_monthly_partition()
RETURNS TRIGGER AS $func$
DECLARE
    partition_name TEXT;
    start_date DATE;
    end_date DATE;
BEGIN
    partition_name := 'notifications_' || to_char(NEW.created_at, 'YYYY_MM');
    start_date := date_trunc('month', NEW.created_at)::DATE;
    end_date := (date_trunc('month', NEW.created_at) + INTERVAL '1 month')::DATE;

    -- Check if partition exists, create if not
    IF NOT EXISTS (
        SELECT 1 FROM pg_class WHERE relname = partition_name
    ) THEN
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF notifications FOR VALUES FROM (%L) TO (%L)',
            partition_name, start_date, end_date
        );
        RAISE NOTICE 'Created partition: %', partition_name;
    END IF;

    RETURN NEW;
EXCEPTION
    WHEN duplicate_table THEN
        -- Partition already exists (race condition), safe to ignore
        RETURN NEW;
END;
$func$ LANGUAGE plpgsql;

-- Function to create partitions for the next N months (called by Celery Beat)
CREATE OR REPLACE FUNCTION ensure_future_partitions(months_ahead INTEGER DEFAULT 3)
RETURNS VOID AS $func$
DECLARE
    i INTEGER;
    partition_name TEXT;
    start_date DATE;
    end_date DATE;
    check_date DATE;
BEGIN
    FOR i IN 0..months_ahead LOOP
        check_date := CURRENT_DATE + (i || ' months')::INTERVAL;
        partition_name := 'notifications_' || to_char(check_date, 'YYYY_MM');
        start_date := date_trunc('month', check_date)::DATE;
        end_date := (date_trunc('month', check_date) + INTERVAL '1 month')::DATE;

        IF NOT EXISTS (
            SELECT 1 FROM pg_class WHERE relname = partition_name
        ) THEN
            BEGIN
                EXECUTE format(
                    'CREATE TABLE IF NOT EXISTS %I PARTITION OF notifications FOR VALUES FROM (%L) TO (%L)',
                    partition_name, start_date, end_date
                );
                RAISE NOTICE 'Created future partition: %', partition_name;
            EXCEPTION
                WHEN duplicate_table THEN
                    NULL; -- Already exists
                WHEN undefined_table THEN
                    -- notifications table not yet created by Django
                    RAISE NOTICE 'notifications table does not exist yet, skipping partition creation';
                    RETURN;
            END;
        END IF;
    END LOOP;
END;
$func$ LANGUAGE plpgsql;

-- Note: The actual conversion of Django's notifications table to a
-- partitioned table is handled by a Django migration. This script
-- provides the helper functions that are used by the system.
--
-- Partition maintenance (creating future partitions, dropping old ones)
-- is handled by the Celery Beat periodic task: cleanup_old_notifications
