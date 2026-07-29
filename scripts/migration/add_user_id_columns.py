# migrations/add_user_id_columns.py
import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine

async def add_user_id_columns():
    async with engine.begin() as conn:
        print("🔄 Adding user_id columns to tables...")
        
        # 1. Add user_id to health_di_cases
        try:
            await conn.execute(text(
                "ALTER TABLE health_di_cases ADD COLUMN user_id INTEGER REFERENCES users(id)"
            ))
            print("✅ Added user_id to health_di_cases")
        except Exception as e:
            print(f"⚠️ health_di_cases: {e}")
        
        # 2. Add user_id to health_case_documents
        try:
            await conn.execute(text(
                "ALTER TABLE health_case_documents ADD COLUMN user_id INTEGER REFERENCES users(id)"
            ))
            print("✅ Added user_id to health_case_documents")
        except Exception as e:
            print(f"⚠️ health_case_documents: {e}")
        
        # 3. Add user_id to health_scheduled_slots
        try:
            await conn.execute(text(
                "ALTER TABLE health_scheduled_slots ADD COLUMN user_id INTEGER REFERENCES users(id)"
            ))
            print("✅ Added user_id to health_scheduled_slots")
        except Exception as e:
            print(f"⚠️ health_scheduled_slots: {e}")
        
        # 4. Add user_id to health_questionnaires
        try:
            await conn.execute(text(
                "ALTER TABLE health_questionnaires ADD COLUMN user_id INTEGER REFERENCES users(id)"
            ))
            print("✅ Added user_id to health_questionnaires")
        except Exception as e:
            print(f"⚠️ health_questionnaires: {e}")
        
        # 5. Add user_id to health_whatsapp_messages
        try:
            await conn.execute(text(
                "ALTER TABLE health_whatsapp_messages ADD COLUMN user_id INTEGER REFERENCES users(id)"
            ))
            print("✅ Added user_id to health_whatsapp_messages")
        except Exception as e:
            print(f"⚠️ health_whatsapp_messages: {e}")
        
        # 6. Create indexes for performance
        try:
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_cases_user_id ON health_di_cases(user_id)"
            ))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_documents_user_id ON health_case_documents(user_id)"
            ))
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_slots_user_id ON health_scheduled_slots(user_id)"
            ))
            print("✅ Created indexes")
        except Exception as e:
            print(f"⚠️ Index creation: {e}")
        
        print("🎉 Migration complete!")

if __name__ == "__main__":
    asyncio.run(add_user_id_columns())