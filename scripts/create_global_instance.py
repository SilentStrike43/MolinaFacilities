"""
Create Global Sandbox Instance for L3/S1 Testing
"""

def upgrade(db):
    """Create the global sandbox instance"""
    
    # Check if global instance already exists
    cursor = db.cursor()
    cursor.execute("SELECT id FROM instances WHERE id = 0")
    if cursor.fetchone():
        print("Global instance already exists, skipping...")
        return
    
    # Create global instance
    cursor.execute("""
        INSERT INTO instances (
            id,
            instance_name,
            created_at,
            status,
            primary_color,
            primary_color_dark,
            primary_color_light,
            primary_color_pale
        ) VALUES (
            0,
            'Global Sandbox',
            datetime('now'),
            'active',
            '#FF8C42',
            '#E67800',
            '#FFAB6B',
            '#FFF4E6'
        )
    """)
    
    db.commit()
    print("✅ Global sandbox instance created (ID: 0)")

def downgrade(db):
    """Remove global sandbox instance"""
    cursor = db.cursor()
    cursor.execute("DELETE FROM instances WHERE id = 0")
    db.commit()
    print("❌ Global sandbox instance removed")