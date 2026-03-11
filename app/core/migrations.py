# app/core/migrations.py
"""
Schema Migration Tracker

Replaces the scattered ALTER TABLE ADD COLUMN IF NOT EXISTS pattern with a
versioned migration system.  Each migration is a plain SQL string with a
unique ID.  Migrations run exactly once — the `schema_migrations` table
records which IDs have already been applied.

Usage (startup.py):
    from app.core.migrations import run_migrations
    run_migrations()
"""

import logging
from app.core.database import get_db_connection

logger = logging.getLogger(__name__)

# ── Migration registry ────────────────────────────────────────────────────────
# List of (migration_id, db_name, sql) tuples.
# - migration_id: unique slug, never reuse or rename
# - db_name:      which DB connection to use ('core', 'send', 'fulfillment', 'inventory')
# - sql:          one or more statements separated by semicolons
#
# ADD NEW MIGRATIONS AT THE BOTTOM.  Never modify existing entries.

MIGRATIONS: list[tuple[str, str, str]] = [

    # ── core / users ──────────────────────────────────────────────────────────
    (
        "core_users_add_user_preferences",
        "core",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS user_preferences TEXT DEFAULT '{}'"
    ),
    (
        "core_users_add_last_seen",
        "core",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen TIMESTAMP"
    ),
    (
        "core_users_add_force_logout",
        "core",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS force_logout BOOLEAN DEFAULT FALSE"
    ),
    (
        "core_users_add_failed_login_attempts",
        "core",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER DEFAULT 0"
    ),
    (
        "core_users_add_locked_until",
        "core",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMP NULL"
    ),
    (
        "core_audit_logs_add_instance_id",
        "core",
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS instance_id INTEGER"
    ),

    # ── send / package_manifest ───────────────────────────────────────────────
    (
        "send_manifest_add_carrier",
        "send",
        "ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS carrier VARCHAR(50)"
    ),
    (
        "send_manifest_add_recipient_fields",
        "send",
        """
        ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS recipient_name VARCHAR(255);
        ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS recipient_address TEXT;
        ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS recipient_city VARCHAR(100);
        ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS recipient_state VARCHAR(50);
        ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS recipient_zip VARCHAR(20);
        ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS recipient_country VARCHAR(50)
        """
    ),
    (
        "send_manifest_add_tracking_fields",
        "send",
        """
        ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS tracking_number VARCHAR(100);
        ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS tracking_status VARCHAR(50);
        ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS tracking_status_description TEXT;
        ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS estimated_delivery_date TIMESTAMP;
        ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS actual_delivery_date TIMESTAMP;
        ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS delivered_to VARCHAR(255);
        ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS delivery_signature VARCHAR(255);
        ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS delivery_location TEXT;
        ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS last_tracked_at TIMESTAMP;
        ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS tracking_last_updated TIMESTAMP;
        ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS tracking_error TEXT
        """
    ),
    (
        "send_manifest_add_service_fields",
        "send",
        """
        ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS service_type VARCHAR(100);
        ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS shipping_method VARCHAR(100);
        ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS package_weight NUMERIC(10,2)
        """
    ),
    (
        "send_manifest_add_deleted_at",
        "send",
        "ALTER TABLE package_manifest ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP"
    ),

    # ── fulfillment ───────────────────────────────────────────────────────────
    (
        "fulfillment_service_requests_add_instance_id",
        "fulfillment",
        "ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS instance_id INTEGER"
    ),
    (
        "fulfillment_service_requests_add_archived",
        "fulfillment",
        """
        ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS is_archived BOOLEAN DEFAULT FALSE;
        ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP
        """
    ),
    (
        "fulfillment_requests_add_tracking_fields",
        "fulfillment",
        """
        ALTER TABLE fulfillment_requests ADD COLUMN IF NOT EXISTS instance_id INTEGER;
        ALTER TABLE fulfillment_requests ADD COLUMN IF NOT EXISTS is_archived BOOLEAN DEFAULT FALSE;
        ALTER TABLE fulfillment_requests ADD COLUMN IF NOT EXISTS date_due DATE;
        ALTER TABLE fulfillment_requests ADD COLUMN IF NOT EXISTS total_pages INTEGER DEFAULT 0;
        ALTER TABLE fulfillment_requests ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP;
        ALTER TABLE fulfillment_requests ADD COLUMN IF NOT EXISTS completed_by_id INTEGER;
        ALTER TABLE fulfillment_requests ADD COLUMN IF NOT EXISTS completed_by_name VARCHAR(255);
        ALTER TABLE fulfillment_requests ADD COLUMN IF NOT EXISTS created_by_id INTEGER;
        ALTER TABLE fulfillment_requests ADD COLUMN IF NOT EXISTS created_by_name VARCHAR(255)
        """
    ),

    # ── inventory ─────────────────────────────────────────────────────────────
    (
        "inventory_assets_add_vendor_id",
        "inventory",
        "ALTER TABLE assets ADD COLUMN IF NOT EXISTS vendor_id INTEGER"
    ),

    # ── settings ─────────────────────────────────────────────────────────────
    # (user_preferences already covered by core_users_add_user_preferences above)
]


# ── Runner ────────────────────────────────────────────────────────────────────

def _ensure_migrations_table(db_name: str):
    """Create the schema_migrations tracking table in the given DB."""
    with get_db_connection(db_name) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id          VARCHAR(100) PRIMARY KEY,
                applied_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.close()


def run_migrations():
    """
    Apply all pending migrations in order.
    Safe to call on every startup — already-applied migrations are skipped.
    """
    # Collect unique DB names so we create the tracking table in each
    db_names = {db for _, db, _ in MIGRATIONS}
    for db_name in db_names:
        try:
            _ensure_migrations_table(db_name)
        except Exception as exc:
            logger.error(f"Could not create schema_migrations in {db_name}: {exc}", exc_info=True)
            return

    applied = 0
    skipped = 0
    for migration_id, db_name, sql in MIGRATIONS:
        try:
            with get_db_connection(db_name) as conn:
                cursor = conn.cursor()

                # Check if already applied
                cursor.execute(
                    "SELECT 1 FROM schema_migrations WHERE id = %s",
                    (migration_id,)
                )
                if cursor.fetchone():
                    skipped += 1
                    cursor.close()
                    continue

                # Run each semicolon-separated statement
                for statement in [s.strip() for s in sql.split(";") if s.strip()]:
                    cursor.execute(statement)

                # Record as applied
                cursor.execute(
                    "INSERT INTO schema_migrations (id) VALUES (%s)",
                    (migration_id,)
                )
                cursor.close()
                applied += 1
                logger.info(f"Migration applied: {migration_id}")

        except Exception as exc:
            logger.error(f"Migration failed [{migration_id}]: {exc}", exc_info=True)
            # Continue with remaining migrations rather than halting startup

    if applied:
        logger.info(f"Migrations complete: {applied} applied, {skipped} already up to date")
    else:
        logger.debug(f"Migrations: all {skipped} already up to date")
