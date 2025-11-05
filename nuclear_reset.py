# nuclear_reset.py
"""
NUCLEAR RESET: Drop ALL tables and recreate from scratch
"""

from app.core.database import get_db_connection

print("💣 NUCLEAR RESET - Dropping ALL tables...\n")

# Drop all tables in CORE
print("🔥 Dropping CORE tables...")
with get_db_connection("core") as conn:
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS user_elevation_history CASCADE")
    cursor.execute("DROP TABLE IF EXISTS deletion_requests CASCADE")
    cursor.execute("DROP TABLE IF EXISTS audit_logs CASCADE")
    cursor.execute("DROP TABLE IF EXISTS instances CASCADE")
    cursor.execute("DROP TABLE IF EXISTS users CASCADE")
    cursor.close()
    print("✅ CORE tables dropped")

# Drop all tables in SEND
print("🔥 Dropping SEND tables...")
with get_db_connection("send") as conn:
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS package_manifest CASCADE")
    cursor.execute("DROP TABLE IF EXISTS cache CASCADE")
    cursor.execute("DROP TABLE IF EXISTS counters CASCADE")
    cursor.close()
    print("✅ SEND tables dropped")

# Drop all tables in INVENTORY
print("🔥 Dropping INVENTORY tables...")
with get_db_connection("inventory") as conn:
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS inventory_reports CASCADE")
    cursor.execute("DROP TABLE IF EXISTS inventory_transactions CASCADE")
    cursor.execute("DROP TABLE IF EXISTS asset_ledger CASCADE")
    cursor.execute("DROP TABLE IF EXISTS assets CASCADE")
    cursor.close()
    print("✅ INVENTORY tables dropped")

# Drop all tables in FULFILLMENT
print("🔥 Dropping FULFILLMENT tables...")
with get_db_connection("fulfillment") as conn:
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS fulfillment_requests CASCADE")
    cursor.execute("DROP TABLE IF EXISTS service_requests CASCADE")
    cursor.close()
    print("✅ FULFILLMENT tables dropped")

print("\n💥 ALL TABLES DROPPED!")
print("Now run: python complete_schema_setup.py")