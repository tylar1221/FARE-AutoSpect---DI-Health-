# check_rds_complete.py
"""Complete RDS Database and Table Checker"""

import asyncpg
import asyncio
from datetime import datetime
from typing import Dict, List, Any

# RDS Configuration (from your .env)
RDS_CONFIG = {
    "host": "motor-v2-db.cn2euyuwcn9z.ap-south-1.rds.amazonaws.com",
    "port": 5432,
    "user": "motoradmin",
    "password": "ics_forensics",
}

# Databases to check
DATABASES_TO_CHECK = ["postgres", "fare_autospect", "postgres"]

async def check_all_databases():
    """Check all databases and their tables"""
    print("=" * 70)
    print("🏥 HEALTH - Complete RDS PostgreSQL Database Check")
    print("=" * 70)
    print(f"📍 Host: {RDS_CONFIG['host']}")
    print(f"👤 User: {RDS_CONFIG['user']}")
    print(f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    # First, connect to default 'postgres' database to list all databases
    try:
        conn = await asyncpg.connect(
            host=RDS_CONFIG["host"],
            port=RDS_CONFIG["port"],
            user=RDS_CONFIG["user"],
            password=RDS_CONFIG["password"],
            database="postgres"
        )
        
        # Get all databases
        databases = await conn.fetch("""
            SELECT datname 
            FROM pg_database 
            WHERE datistemplate = false 
            ORDER BY datname
        """)
        
        print(f"\n📁 DATABASES FOUND: {len(databases)}")
        print("-" * 70)
        
        for db in databases:
            db_name = db["datname"]
            print(f"\n📀 Database: {db_name}")
            
            # Try to connect to each database
            try:
                db_conn = await asyncpg.connect(
                    host=RDS_CONFIG["host"],
                    port=RDS_CONFIG["port"],
                    user=RDS_CONFIG["user"],
                    password=RDS_CONFIG["password"],
                    database=db_name
                )
                
                # Get all tables in this database
                tables = await db_conn.fetch("""
                    SELECT 
                        tablename,
                        schemaname
                    FROM pg_tables 
                    WHERE schemaname = 'public'
                    ORDER BY tablename
                """)
                
                if tables:
                    print(f"   📋 Tables in '{db_name}': {len(tables)}")
                    for table in tables:
                        table_name = table["tablename"]
                        
                        # Get row count
                        try:
                            count = await db_conn.fetchval(f'SELECT COUNT(*) FROM "{table_name}"')
                            # Get column count
                            columns = await db_conn.fetch("""
                                SELECT COUNT(*) 
                                FROM information_schema.columns 
                                WHERE table_name = $1
                            """, table_name)
                            col_count = columns[0][0]
                            
                            print(f"      ✅ {table_name}: {count:,} rows, {col_count} columns")
                        except Exception as e:
                            print(f"      ⚠️ {table_name}: Error - {str(e)[:50]}")
                else:
                    print(f"   📋 Tables in '{db_name}': 0 (empty database)")
                
                await db_conn.close()
                
            except Exception as e:
                print(f"   ❌ Cannot connect: {str(e)[:100]}")
        
        await conn.close()
        
    except Exception as e:
        print(f"❌ Failed to connect to PostgreSQL: {e}")
        return

async def check_specific_tables():
    """Check specific tables we care about"""
    print("\n" + "=" * 70)
    print("🎯 CHECKING SPECIFIC TABLES (health_* and original names)")
    print("=" * 70)
    
    # Try to connect to fare_autospect database
    try:
        conn = await asyncpg.connect(
            host=RDS_CONFIG["host"],
            port=RDS_CONFIG["port"],
            user=RDS_CONFIG["user"],
            password=RDS_CONFIG["password"],
            database="fare_autospect"
        )
        
        print("\n✅ Connected to 'fare_autospect' database\n")
        
        # Check for health_ prefixed tables
        health_tables = await conn.fetch("""
            SELECT tablename 
            FROM pg_tables 
            WHERE schemaname = 'public' 
            AND tablename LIKE 'health_%'
            ORDER BY tablename
        """)
        
        if health_tables:
            print(f"📋 Health-prefixed tables found: {len(health_tables)}")
            print("-" * 50)
            for table in health_tables:
                table_name = table["tablename"]
                try:
                    count = await conn.fetchval(f'SELECT COUNT(*) FROM "{table_name}"')
                    print(f"   🏥 {table_name}: {count:,} rows")
                except:
                    print(f"   🏥 {table_name}: (exists, can't count)")
        else:
            print("⚠️ No 'health_' prefixed tables found")
        
        # Check for original table names
        original_tables = ["di_cases", "case_documents", "scheduled_slots", "whatsapp_messages", "questionnaires"]
        print("\n📋 Checking original table names:")
        print("-" * 50)
        
        for table_name in original_tables:
            try:
                count = await conn.fetchval(f'SELECT COUNT(*) FROM "{table_name}"')
                print(f"   ✅ {table_name}: {count:,} rows")
            except Exception as e:
                print(f"   ❌ {table_name}: Not found")
        
        # Get database size info
        size_info = await conn.fetchrow("""
            SELECT 
                pg_database_size(current_database()) as size_bytes,
                pg_size_pretty(pg_database_size(current_database())) as size_pretty
        """)
        
        print("\n💾 Database Size Info:")
        print("-" * 50)
        print(f"   Size: {size_info['size_pretty']} ({size_info['size_bytes']:,} bytes)")
        
        await conn.close()
        
    except asyncpg.InvalidCatalogNameError:
        print("\n❌ Database 'fare_autospect' does not exist!")
        print("   You need to create it first with: python create_db_now.py")
    except Exception as e:
        print(f"\n❌ Error connecting to fare_autospect: {e}")

async def check_connection_details():
    """Check connection and get PostgreSQL version"""
    print("\n" + "=" * 70)
    print("🔌 CONNECTION DETAILS")
    print("=" * 70)
    
    try:
        conn = await asyncpg.connect(
            host=RDS_CONFIG["host"],
            port=RDS_CONFIG["port"],
            user=RDS_CONFIG["user"],
            password=RDS_CONFIG["password"],
            database="postgres"
        )
        
        # Get PostgreSQL version
        version = await conn.fetchval("SELECT version()")
        print(f"✅ PostgreSQL Version: {version.split(',')[0]}")
        
        # Get connection info
        settings = await conn.fetchrow("""
            SELECT 
                current_setting('server_version') as version,
                current_setting('max_connections') as max_conn,
                current_setting('shared_buffers') as buffers
        """)
        
        print(f"📊 Server Settings:")
        print(f"   Max Connections: {settings['max_conn']}")
        print(f"   Shared Buffers: {settings['buffers']}")
        
        await conn.close()
        
    except Exception as e:
        print(f"❌ Connection failed: {e}")

async def quick_summary():
    """Quick summary of what exists"""
    print("\n" + "=" * 70)
    print("📊 QUICK SUMMARY")
    print("=" * 70)
    
    try:
        # Check if fare_autospect exists
        conn = await asyncpg.connect(
            host=RDS_CONFIG["host"],
            port=RDS_CONFIG["port"],
            user=RDS_CONFIG["user"],
            password=RDS_CONFIG["password"],
            database="postgres"
        )
        
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = 'fare_autospect'"
        )
        
        if exists:
            print("✅ Database 'fare_autospect' EXISTS")
            
            # Check tables in fare_autospect
            db_conn = await asyncpg.connect(
                host=RDS_CONFIG["host"],
                port=RDS_CONFIG["port"],
                user=RDS_CONFIG["user"],
                password=RDS_CONFIG["password"],
                database="fare_autospect"
            )
            
            table_count = await db_conn.fetchval("""
                SELECT COUNT(*) FROM pg_tables 
                WHERE schemaname = 'public'
            """)
            
            if table_count > 0:
                print(f"✅ {table_count} tables found in fare_autospect")
                
                # Check if health_ tables exist
                health_count = await db_conn.fetchval("""
                    SELECT COUNT(*) FROM pg_tables 
                    WHERE schemaname = 'public' 
                    AND tablename LIKE 'health_%'
                """)
                
                if health_count > 0:
                    print(f"✅ {health_count} health_ prefixed tables found")
                else:
                    print("⚠️ No health_ prefixed tables found")
            else:
                print("⚠️ No tables found in fare_autospect (run migration)")
            
            await db_conn.close()
        else:
            print("❌ Database 'fare_autospect' does NOT exist")
            print("   Run: python create_db_now.py to create it")
        
        await conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")

async def main():
    """Run all checks"""
    await check_connection_details()
    await check_all_databases()
    await check_specific_tables()
    await quick_summary()
    
    print("\n" + "=" * 70)
    print("🏥 HEALTH - Check Complete")
    print("=" * 70)
    print("\n💡 Next Steps:")
    print("   1. If database missing: python create_db_now.py")
    print("   2. If tables missing: python migrate_sqlite_to_rds.py")
    print("   3. If all good: python main.py")
    print()

if __name__ == "__main__":
    asyncio.run(main())