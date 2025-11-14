"""
Quick fix for FedEx sync errors
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.database import get_db_connection

def fix_sync_table():
    """Fix the fedex_sync_log table"""
    print("🔧 Fixing fedex_sync_log table...")
    
    try:
        with get_db_connection("send") as conn:
            cursor = conn.cursor()
            
            # Drop existing table if it has FK constraint issues
            cursor.execute("DROP TABLE IF EXISTS fedex_sync_log CASCADE;")
            
            # Recreate with correct schema
            cursor.execute("""
                CREATE TABLE fedex_sync_log (
                    id SERIAL PRIMARY KEY,
                    instance_id INTEGER,
                    hours_back INTEGER NOT NULL,
                    success BOOLEAN DEFAULT FALSE,
                    imported_count INTEGER DEFAULT 0,
                    skipped_count INTEGER DEFAULT 0,
                    error_message TEXT,
                    triggered_by INTEGER,
                    triggered_by_username TEXT,
                    triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE INDEX idx_fedex_sync_log_triggered_at 
                ON fedex_sync_log(triggered_at DESC);
                
                CREATE INDEX idx_fedex_sync_log_instance 
                ON fedex_sync_log(instance_id);
            """)
            
            conn.commit()
            cursor.close()
            
            print("✅ Table fixed successfully!")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False
    
    return True

if __name__ == "__main__":
    print("=" * 60)
    print("FedEx Sync Error Fix")
    print("=" * 60)
    
    if fix_sync_table():
        print("\n✅ All fixes applied! You can now run the sync.")
    else:
        print("\n❌ Fix failed. Check the errors above.")