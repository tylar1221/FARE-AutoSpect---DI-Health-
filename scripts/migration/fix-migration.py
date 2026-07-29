# migrate_fixed.py - Fixed date/time handling
import asyncio
import sqlite3
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import engine, AsyncSessionLocal
from app.models import DICase, CaseDocument, ScheduledSlot, WhatsAppMessage, Questionnaire
from sqlalchemy import select

async def fix_and_migrate():
    print("=" * 70)
    print("🏥 HEALTH - FIXED MIGRATION (Proper Date Handling)")
    print("=" * 70)
    
    sqlite_db = "di_health.db"
    
    if not os.path.exists(sqlite_db):
        print(f"❌ SQLite database '{sqlite_db}' not found!")
        return
    
    print(f"📁 Source: {sqlite_db}")
    
    # Connect to SQLite
    sqlite_conn = sqlite3.connect(sqlite_db)
    sqlite_conn.row_factory = sqlite3.Row
    
    async with AsyncSessionLocal() as session:
        # Get existing cases to avoid duplicates
        result = await session.execute(select(DICase.case_id))
        existing_ids = {row[0] for row in result.fetchall()}
        
        print(f"\n📊 Existing cases in PostgreSQL: {len(existing_ids)}")
        
        # Read cases from SQLite
        cursor = sqlite_conn.cursor()
        cursor.execute("SELECT * FROM di_cases")
        rows = cursor.fetchall()
        
        print(f"📊 Cases in SQLite: {len(rows)}")
        print("\n🔄 Migrating cases with proper date conversion...")
        
        migrated = 0
        skipped = 0
        
        for row in rows:
            data = dict(row)
            case_id = data['case_id']
            
            if case_id in existing_ids:
                skipped += 1
                continue
            
            # CONVERT DATE STRINGS TO DATETIME OBJECTS
            scheduled_time = None
            if data.get('scheduled_time'):
                try:
                    if isinstance(data['scheduled_time'], str):
                        # Parse the string to datetime
                        scheduled_time = datetime.fromisoformat(data['scheduled_time'].replace('Z', '+00:00'))
                    else:
                        scheduled_time = data['scheduled_time']
                except:
                    scheduled_time = None
            
            created_at = None
            if data.get('created_at'):
                try:
                    if isinstance(data['created_at'], str):
                        created_at = datetime.fromisoformat(data['created_at'].replace('Z', '+00:00'))
                    else:
                        created_at = data['created_at']
                except:
                    created_at = datetime.now()
            
            updated_at = None
            if data.get('updated_at'):
                try:
                    if isinstance(data['updated_at'], str):
                        updated_at = datetime.fromisoformat(data['updated_at'].replace('Z', '+00:00'))
                    else:
                        updated_at = data['updated_at']
                except:
                    updated_at = None
            
            # Create case with proper datetime objects
            case = DICase(
                case_id=case_id,
                name=data['name'],
                phone_number=data['phone_number'],
                claim_id=data.get('claim_id'),
                company_name=data.get('company_name'),
                category=data.get('category', 'normal'),
                status=data.get('status', 'pending'),
                meeting_link=data.get('meeting_link'),
                drive_link=data.get('drive_link'),
                scheduled_time=scheduled_time,  # Now a datetime object
                notes=data.get('notes'),
                transcript=data.get('transcript'),
                created_at=created_at or datetime.now(),
                updated_at=updated_at
            )
            session.add(case)
            migrated += 1
            
            if migrated % 10 == 0:
                print(f"   ... processed {migrated} cases")
        
        await session.commit()
        print(f"\n✅ Migrated {migrated} cases (skipped {skipped} existing)")
        
        # Now migrate documents
        print("\n📦 Migrating documents...")
        try:
            cursor.execute("SELECT * FROM case_documents")
            docs = cursor.fetchall()
            
            doc_count = 0
            for doc in docs:
                data = dict(doc)
                new_doc = CaseDocument(
                    case_id=data['case_id'],
                    file_name=data['file_name'],
                    file_url=data['file_url'],
                    file_type=data.get('file_type', 'document'),
                    source=data.get('source', 'registration'),
                    uploaded_at=datetime.now()
                )
                session.add(new_doc)
                doc_count += 1
            
            await session.commit()
            print(f"✅ Migrated {doc_count} documents")
        except Exception as e:
            print(f"⚠️ Documents error: {e}")
        
        # Verify final count
        result = await session.execute(select(DICase))
        final_count = len(result.fetchall())
        
        print("\n" + "=" * 70)
        print("📊 FINAL STATUS:")
        print("=" * 70)
        print(f"   ✅ Total cases in PostgreSQL: {final_count}")
        print("=" * 70)
    
    sqlite_conn.close()

async def check_tables():
    """Check what's in the database"""
    print("\n" + "=" * 70)
    print("🔍 CHECKING DATABASE CONTENTS")
    print("=" * 70)
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(DICase))
        cases = result.fetchall()
        
        print(f"\n📋 Cases in health_di_cases: {len(cases)}")
        
        if cases:
            print("\n📝 Sample cases:")
            for case in cases[:5]:
                print(f"   - {case.case_id}: {case.name} ({case.status})")

if __name__ == "__main__":
    asyncio.run(fix_and_migrate())
    asyncio.run(check_tables())