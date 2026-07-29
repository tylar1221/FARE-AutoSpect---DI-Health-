# app/database.py

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import text
from app.config import settings
import os

# Get database URL from settings
database_url = settings.get_database_url()
is_postgres = "postgresql" in database_url

print(f"🔗 Connecting to database: {'PostgreSQL' if is_postgres else 'SQLite'}")

# Engine configuration
if is_postgres:
    engine = create_async_engine(
        database_url,
        echo=settings.DEBUG,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=3600,
    )
else:
    db_path = database_url.replace("sqlite+aiosqlite:///", "")
    db_dir = os.path.dirname(db_path)

    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

    engine = create_async_engine(
        database_url,
        echo=settings.DEBUG,
        connect_args={"check_same_thread": False}
    )

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """
    Initialize database - creates all tables
    """

    from app.models import (
        DICase,
        CaseDocument,
        ScheduledSlot,
        WhatsAppMessage,
        Questionnaire
    )

    async with engine.begin() as conn:

        # Create all tables from SQLAlchemy models
        await conn.run_sync(Base.metadata.create_all)

        if is_postgres:
            try:
                # DICase indexes
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_health_di_cases_status
                    ON health_di_cases(status)
                """))

                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_health_di_cases_phone
                    ON health_di_cases(phone_number)
                """))

                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_health_di_cases_created
                    ON health_di_cases(created_at)
                """))

                # CaseDocument indexes
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_health_case_documents_case
                    ON health_case_documents(case_id)
                """))

                # ScheduledSlot indexes
                await conn.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_health_scheduled_slots_date
                    ON health_scheduled_slots(slot_date)
                """))

                print("✅ PostgreSQL indexes created")

            except Exception as e:
                print(f"⚠️ Index creation warning: {e}")

    print(
        f"✅ Database initialized "
        f"({'PostgreSQL' if is_postgres else 'SQLite'})"
    )


async def check_db_connection():
    """
    Check database connectivity
    """

    try:
        async with engine.connect() as conn:

            if is_postgres:
                result = await conn.execute(
                    text("SELECT version()")
                )
                version = result.scalar()

                print(
                    f"✅ PostgreSQL connected: "
                    f"{version[:50]}..."
                )

            else:
                result = await conn.execute(
                    text("SELECT sqlite_version()")
                )
                version = result.scalar()

                print(
                    f"✅ SQLite connected: version {version}"
                )

        return True

    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False