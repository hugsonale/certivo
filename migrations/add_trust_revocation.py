"""
Database Migration: Add Trust Revocation Columns
Adds trust_revoked, revoked_at, and revocation_reason columns to trusted_devices table
"""

from sqlalchemy import create_engine, text
import sys
import os

# Add parent directory to path so we can import database
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import DATABASE_URL

print("=" * 60)
print("🔧 CERTIVO DATABASE MIGRATION")
print("=" * 60)
print(f"📁 Database: {DATABASE_URL}")
print("📝 Migration: Add trust revocation columns")
print("=" * 60)

# Create engine
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

try:
    with engine.connect() as conn:
        # Check if columns already exist
        result = conn.execute(text("PRAGMA table_info(trusted_devices)"))
        columns = [row[1] for row in result.fetchall()]
        
        print(f"\n📋 Current columns: {columns}")
        
        # Add trust_revoked column
        if 'trust_revoked' not in columns:
            print("\n➕ Adding column: trust_revoked (BOOLEAN)")
            conn.execute(text('ALTER TABLE trusted_devices ADD COLUMN trust_revoked BOOLEAN DEFAULT 0'))
            conn.commit()
            print("   ✅ Added successfully")
        else:
            print("\n⚠️  Column 'trust_revoked' already exists - skipping")
        
        # Add revoked_at column
        if 'revoked_at' not in columns:
            print("\n➕ Adding column: revoked_at (DATETIME)")
            conn.execute(text('ALTER TABLE trusted_devices ADD COLUMN revoked_at DATETIME'))
            conn.commit()
            print("   ✅ Added successfully")
        else:
            print("\n⚠️  Column 'revoked_at' already exists - skipping")
        
        # Add revocation_reason column
        if 'revocation_reason' not in columns:
            print("\n➕ Adding column: revocation_reason (TEXT)")
            conn.execute(text('ALTER TABLE trusted_devices ADD COLUMN revocation_reason TEXT'))
            conn.commit()
            print("   ✅ Added successfully")
        else:
            print("\n⚠️  Column 'revocation_reason' already exists - skipping")
        
        # Verify final schema
        print("\n" + "=" * 60)
        print("🔍 VERIFYING NEW SCHEMA")
        print("=" * 60)
        result = conn.execute(text("PRAGMA table_info(trusted_devices)"))
        rows = result.fetchall()
        
        print("\n📊 trusted_devices table schema:")
        for row in rows:
            print(f"   • {row[1]} ({row[2]})")
        
        # Check for our new columns
        final_columns = [row[1] for row in rows]
        required_columns = ['trust_revoked', 'revoked_at', 'revocation_reason']
        
        all_present = all(col in final_columns for col in required_columns)
        
        if all_present:
            print("\n" + "=" * 60)
            print("✅ MIGRATION SUCCESSFUL")
            print("=" * 60)
            print("All required columns are present.")
            print("Admin dashboard should now work without SQL errors.")
        else:
            print("\n" + "=" * 60)
            print("❌ MIGRATION INCOMPLETE")
            print("=" * 60)
            missing = [col for col in required_columns if col not in final_columns]
            print(f"Missing columns: {missing}")
            print("Please run the migration again.")

except Exception as e:
    print("\n" + "=" * 60)
    print("❌ MIGRATION FAILED")
    print("=" * 60)
    print(f"Error: {str(e)}")
    print("\nTroubleshooting:")
    print("1. Make sure certivo_v2.db exists")
    print("2. Make sure database.py is in the same directory")
    print("3. Make sure no other process is using the database")
    import traceback
    traceback.print_exc()

finally:
    engine.dispose()
    print("\n" + "=" * 60)