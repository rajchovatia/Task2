"""
Database Router for Read/Write Splitting.

Routes:
  - Write operations → 'default' (PostgreSQL Primary via PgBouncer)
  - Read operations  → 'replica' (PostgreSQL Read Replica via PgBouncer)

This prevents read-heavy operations (notification lists, unread counts,
analytics queries) from loading the primary database.
"""


class PrimaryReplicaRouter:
    """Route reads to replica, writes to primary."""

    # Apps that should always use the primary (write-heavy / migrations)
    ALWAYS_PRIMARY_APPS = {"auth", "authtoken", "admin", "sessions", "contenttypes"}

    def db_for_read(self, model, **hints):
        """Route read queries to the replica database."""
        if model._meta.app_label in self.ALWAYS_PRIMARY_APPS:
            return "default"
        return "replica"

    def db_for_write(self, model, **hints):
        """Route all write queries to the primary database."""
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        """Allow relations between objects in primary and replica."""
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """Only run migrations on the primary database."""
        return db == "default"
