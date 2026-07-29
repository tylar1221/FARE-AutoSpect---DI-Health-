# complete_migration_fixed.py - Fixed version with correct database name
"""Complete migration script - Uses Health_DI database"""

import asyncio
import sqlite3
import sys
import os
import asyncpg
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ============================================
# CONFIGURATION - FIXED
# ============================================
RDS_CONFIG = {
    "host": "motor-v2-db.cn2euyuwcn9z.ap-south-1.rds.amazonaws.com",
    "port": 5432,
    "user": "motoradmin",
    "password": "ics_forensics",
    "database": "Health_DI"  # Fixed: Using Health_DI instead of fare_autospect
}

# Import app modules
from app.database import engine, AsyncSessionLocal, Base
from app.models import DICase, CaseDocument, ScheduledSlot, WhatsAppMessage, Questionnaire
from sqlalchemy import text, select

# ============================================
# STEP 1: CHECK DATABASE
# ============================================

async def check_database_exists() -> bool:
    """Check if Health_DI database exists"""
    print("\n" + "=" * 70)
    print("🏥 HEALTH - STEP 1: Checking Database")
    print("=" * 70)
    
    try:
        conn = await asyncpg.connect(
            host=RDS_CONFIG["host"],
            port=RDS_CONFIG["port"],
            user=RDS_CONFIG["user"],
            password=RDS_CONFIG["password"],
            database="postgres"
        )
        
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = 'Health_DI'"
        )
        
        await conn.close()
        
        if exists:
            print("✅ Database 'Health_DI' already exists")
            return True
        else:
            print("❌ Database 'Health_DI' does NOT exist")
            return False
            
    except Exception as e:
        print(f"❌ Error checking database: {e}")
        return False

# ============================================
# STEP 2: CREATE DATABASE
# ============================================

async def create_database():
    """Create Health_DI database"""
    print("\n" + "=" * 70)
    print("🏥 HEALTH - STEP 2: Creating Database")
    print("=" * 70)
    
    try:
        conn = await asyncpg.connect(
            host=RDS_CONFIG["host"],
            port=RDS_CONFIG["port"],
            user=RDS_CONFIG["user"],
            password=RDS_CONFIG["password"],
            database="postgres"
        )
        
        # Check if already exists
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = 'Health_DI'")
        
        if exists:
            print("✅ Database 'Health_DI' already exists!")
        else:
            await conn.execute("CREATE DATABASE \"Health_DI\"")
            print("✅ Database 'Health_DI' created successfully!")
        
        await conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Failed to create database: {e}")
        return False

# ============================================
# STEP 3: CHECK TABLES
# ============================================

async def check_tables():
    """Check what tables exist in Health_DI"""
    print("\n" + "=" * 70)
    print("🏥 HEALTH - STEP 3: Checking Existing Tables")
    print("=" * 70)
    
    try:
        conn = await asyncpg.connect(
            host=RDS_CONFIG["host"],
            port=RDS_CONFIG["port"],
            user=RDS_CONFIG["user"],
            password=RDS_CONFIG["password"],
            database=RDS_CONFIG["database"]
        )
        
        tables = await conn.fetch("""
            SELECT tablename 
            FROM pg_tables 
            WHERE schemaname = 'public'
            ORDER BY tablename
        """)
        
        if tables:
            print(f"📋 Found {len(tables)} table(s):")
            for table in tables:
                table_name = table["tablename"]
                try:
                    count = await conn.fetchval(f'SELECT COUNT(*) FROM "{table_name}"')
                    print(f"   ✅ {table_name}: {count:,} rows")
                except:
                    print(f"   ✅ {table_name}: (exists)")
        else:
            print("⚠️ No tables found in Health_DI database")
        
        await conn.close()
        return tables
        
    except Exception as e:
        print(f"❌ Error checking tables: {e}")
        return []

# ============================================
# STEP 4: CREATE TABLES
# ============================================

async def create_tables_if_needed():
    """Create health_ prefixed tables if they don't exist"""
    print("\n" + "=" * 70)
    print("🏥 HEALTH - STEP 4: Creating Tables")
    print("=" * 70)
    print("📋 Creating tables: health_di_cases, health_case_documents, etc.")
    
    try:
        # Update engine with correct database
        from app.config import settings
        settings.RDS_DATABASE = "Health_DI"
        
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            
            # Create indexes
            try:
                await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_health_di_cases_status ON health_di_cases(status)"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_health_di_cases_phone ON health_di_cases(phone_number)"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_health_case_documents_case ON health_case_documents(case_id)"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_health_scheduled_slots_date ON health_scheduled_slots(slot_date)"))
                print("✅ Tables and indexes created successfully")
            except Exception as e:
                print(f"⚠️ Index warning: {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        return False

# ============================================
# STEP 5: MIGRATE DATA
# ============================================

async def migrate_data():
    """Migrate data from SQLite to PostgreSQL"""
    print("\n" + "=" * 70)
    print("🏥 HEALTH - STEP 5: Migrating Data")
    print("=" * 70)
    
    sqlite_db = "di_health.db"
    
    if not os.path.exists(sqlite_db):
        print(f"⚠️ SQLite database '{sqlite_db}' not found!")
        print("   Starting with empty database.")
        return {"cases": 0, "documents": 0, "slots": 0}
    
    print(f"📁 Source: {sqlite_db}")
    print(f"🎯 Target: PostgreSQL RDS (Health_DI database)")
    
    sqlite_conn = sqlite3.connect(sqlite_db)
    sqlite_conn.row_factory = sqlite3.Row
    stats = {"cases": 0, "documents": 0, "slots": 0}
    
    try:
        async with AsyncSessionLocal() as session:
            # Get existing IDs
            result = await session.execute(select(DICase.case_id))
            existing_case_ids = {row[0] for row in result.fetchall()}
            
            # Migrate Cases
            print("\n📦 Migrating cases...")
            cursor = sqlite_conn.cursor()
            try:
                cursor.execute("SELECT * FROM di_cases")
                rows = cursor.fetchall()
                
                for row in rows:
                    data = dict(row)
                    if data['case_id'] in existing_case_ids:
                        continue
                    
                    case = DICase(
                        case_id=data['case_id'],
                        name=data['name'],
                        phone_number=data['phone_number'],
                        claim_id=data.get('claim_id'),
                        company_name=data.get('company_name'),
                        category=data.get('category', 'normal'),
                        status=data.get('status', 'pending'),
                        meeting_link=data.get('meeting_link'),
                        drive_link=data.get('drive_link'),
                        scheduled_time=data.get('scheduled_time'),
                        notes=data.get('notes'),
                        transcript=data.get('transcript'),
                    )
                    session.add(case)
                    stats["cases"] += 1
                
                await session.commit()
                print(f"   ✅ Migrated {stats['cases']} cases")
            except Exception as e:
                print(f"   ⚠️ Cases error: {e}")
            
            # Migrate Documents
            print("\n📦 Migrating documents...")
            try:
                cursor.execute("SELECT * FROM case_documents")
                rows = cursor.fetchall()
                
                for row in rows:
                    data = dict(row)
                    doc = CaseDocument(
                        case_id=data['case_id'],
                        file_name=data['file_name'],
                        file_url=data['file_url'],
                        file_type=data.get('file_type', 'document'),
                        source=data.get('source', 'registration'),
                    )
                    session.add(doc)
                    stats["documents"] += 1
                
                await session.commit()
                print(f"   ✅ Migrated {stats['documents']} documents")
            except Exception as e:
                print(f"   ⚠️ Documents error: {e}")
            
            print(f"\n✅ Migration complete!")
            
    except Exception as e:
        print(f"❌ Migration failed: {e}")
    finally:
        sqlite_conn.close()
    
    return stats

# ============================================
# STEP 6: VERIFY
# ============================================

async def verify_migration():
    """Verify migration"""
    print("\n" + "=" * 70)
    print("🏥 HEALTH - STEP 6: Verifying Migration")
    print("=" * 70)
    
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(DICase))
            case_count = len(result.fetchall())
            
            result = await session.execute(select(CaseDocument))
            doc_count = len(result.fetchall())
            
            result = await session.execute(select(ScheduledSlot))
            slot_count = len(result.fetchall())
            
            print("\n📊 FINAL DATABASE STATUS:")
            print("-" * 50)
            print(f"   🏥 health_di_cases:           {case_count:>6,} records")
            print(f"   📎 health_case_documents:     {doc_count:>6,} records")
            print(f"   📅 health_scheduled_slots:    {slot_count:>6,} records")
            print("-" * 50)
            
            return case_count
            
    except Exception as e:
        print(f"❌ Verification failed: {e}")
        return 0

# ============================================
# MAIN
# ============================================

async def main():
    print("\n" + "=" * 70)
    print("🏥 HEALTH DATABASE MIGRATION TOOL")
    print("=" * 70)
    print(f"📍 Target Database: {RDS_CONFIG['database']}")
    print("📍 Table Prefix: health_")
    print("=" * 70)
    
    # Step 1 & 2: Create database if needed
    if not await check_database_exists():
        print("\n⚠️ Database not found. Creating...")
        if not await create_database():
            print("❌ Cannot proceed")
            return
    
    # Step 3: Check tables
    await check_tables()
    
    # Step 4: Create tables
    if not await create_tables_if_needed():
        print("❌ Failed to create tables")
        return
    
    # Step 5: Migrate data
    stats = await migrate_data()
    
    # Step 6: Verify
    final_count = await verify_migration()
    
    # Summary
    print("\n" + "=" * 70)
    print("🏥 HEALTH - MIGRATION COMPLETE!")
    print("=" * 70)
    print(f"\n📊 Summary:")
    print(f"   ✅ Cases migrated: {stats['cases']}")
    print(f"   ✅ Total in DB: {final_count}")
    print("\n💡 Next Steps:")
    print("   1. Update .env: RDS_DATABASE=Health_DI")
    print("   2. Run: python main.py")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())