# add_event_id_column.py
import asyncio
from sqlalchemy import text
from app.database import engine

async def add_event_id():
    async with engine.begin() as conn:
        # Check if column exists
        result = await conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'health_di_cases' 
            AND column_name = 'event_id'
        """))
        
        if result.fetchone() is None:
            print("📝 Adding event_id column...")
            await conn.execute(text("""
                ALTER TABLE health_di_cases 
                ADD COLUMN event_id VARCHAR(255)
            """))
            
            await conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_health_di_cases_event_id 
                ON health_di_cases(event_id)
            """))
            
            print("✅ event_id column added successfully!")
        else:
            print("✅ event_id column already exists")

if __name__ == "__main__":
    asyncio.run(add_event_id())