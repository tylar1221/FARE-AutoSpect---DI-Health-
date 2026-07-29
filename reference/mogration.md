# 📋 Complete Migration Guide: SQLite to AWS RDS PostgreSQL

Here's a comprehensive README documenting everything we did:

```markdown
# 🏥 HEALTH Application - Database Migration Guide

## 📌 Migration Overview

**Migration Date:** June 16, 2026  
**Source:** SQLite (local file-based database)  
**Target:** AWS RDS PostgreSQL (cloud-based)  
**Status:** ✅ SUCCESSFUL

---

## 🗄️ Database Configuration

### AWS RDS PostgreSQL Details

| Parameter | Value |
|-----------|-------|
| **Host** | `motor-v2-db.cn2euyuwcn9z.ap-south-1.rds.amazonaws.com` |
| **Port** | `5432` |
| **Database Name** | `Health_DI` |
| **Username** | `motoradmin` |
| **Password** | `ics_forensics` |
| **Region** | `ap-south-1` (Mumbai) |
| **Engine** | PostgreSQL 17.9 |
| **SSL Mode** | `require` |

### Connection String
```
postgresql+asyncpg://motoradmin:ics_forensics@motor-v2-db.cn2euyuwcn9z.ap-south-1.rds.amazonaws.com:5432/Health_DI
```

---

## 📊 Database Tables Structure

All tables use the `health_` prefix for clarity and organization.

### 1. `health_di_cases` - Main Cases Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL | Primary Key (auto-increment) |
| `case_id` | VARCHAR(50) | Unique case identifier (INDEXED) |
| `name` | VARCHAR(200) | Patient name |
| `phone_number` | VARCHAR(20) | Contact number (INDEXED) |
| `claim_id` | VARCHAR(100) | Insurance claim ID |
| `company_name` | VARCHAR(200) | Insurance company name |
| `category` | VARCHAR(50) | `normal` or `pre_existing` |
| `status` | VARCHAR(50) | `pending`, `scheduled`, `completed`, `non_workable` |
| `meeting_link` | VARCHAR(500) | Google Meet URL |
| `drive_link` | VARCHAR(500) | Google Drive folder link |
| `scheduled_time` | TIMESTAMP | Scheduled meeting time |
| `notes` | TEXT | Case notes |
| `transcript` | TEXT | Meeting transcript |
| `created_at` | TIMESTAMP | Record creation time (INDEXED) |
| `updated_at` | TIMESTAMP | Last update time |

**Indexes:**
- `idx_health_di_cases_case_id` (UNIQUE)
- `idx_health_di_cases_phone_number`
- `idx_health_di_cases_status`
- `idx_health_di_cases_created_at`
- `idx_health_di_cases_phone_status` (composite)
- `idx_health_di_cases_status_created` (composite)

### 2. `health_case_documents` - Documents Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL | Primary Key |
| `case_id` | VARCHAR(50) | Foreign key to cases (INDEXED) |
| `file_name` | VARCHAR(255) | Original filename |
| `file_url` | VARCHAR(1000) | Storage URL |
| `file_type` | VARCHAR(50) | `image`, `pdf`, `document` |
| `source` | VARCHAR(50) | `registration` or `whatsapp` |
| `uploaded_at` | TIMESTAMP | Upload timestamp |

**Indexes:**
- `idx_health_case_documents_case_id`
- `idx_health_documents_case_source` (composite)

### 3. `health_scheduled_slots` - Meeting Slots Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL | Primary Key |
| `case_id` | VARCHAR(50) | Foreign key to cases (INDEXED) |
| `slot_date` | DATE | Meeting date (INDEXED) |
| `slot_start` | TIME | Start time |
| `slot_end` | TIME | End time |
| `meet_link` | VARCHAR(500) | Meeting URL |
| `status` | VARCHAR(50) | `booked`, `cancelled`, `completed` |
| `created_at` | TIMESTAMP | Creation timestamp |

**Indexes:**
- `idx_health_scheduled_slots_case_id`
- `idx_health_scheduled_slots_slot_date`
- `idx_health_slots_date_status` (composite)
- `idx_health_slots_case_date` (composite)

### 4. `health_whatsapp_messages` - WhatsApp Messages Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL | Primary Key |
| `case_id` | VARCHAR(50) | Related case (INDEXED) |
| `message_id` | VARCHAR(100) | WhatsApp message ID (UNIQUE) |
| `from_number` | VARCHAR(20) | Sender number (INDEXED) |
| `to_number` | VARCHAR(20) | Recipient number |
| `message_body` | TEXT | Message content |
| `message_type` | VARCHAR(50) | `text`, `image`, `document` |
| `status` | VARCHAR(50) | `sent`, `delivered`, `read` |
| `sent_at` | TIMESTAMP | Sent timestamp (INDEXED) |

**Indexes:**
- `idx_health_whatsapp_messages_case_id`
- `idx_health_whatsapp_messages_sent_at`
- `idx_health_whatsapp_from` (composite)

### 5. `health_questionnaires` - Medical Questionnaire Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL | Primary Key |
| `case_id` | VARCHAR(50) | Foreign key to cases (INDEXED) |
| `question` | TEXT | Question text |
| `answer` | TEXT | Patient's answer |
| `category` | VARCHAR(50) | `generic` or `specific` |
| `answered_at` | TIMESTAMP | When answer was given |
| `created_at` | TIMESTAMP | Record creation |

**Indexes:**
- `idx_health_questionnaires_case_id`
- `idx_health_questionnaire_case_category` (composite)

---

## 📁 Migrated Data Statistics

### Before Migration (SQLite)
- **Database file:** `di_health.db`
- **Cases:** 3 records
- **Documents:** 3 records
- **Slots:** 0 records
- **WhatsApp messages:** 0 records
- **Questionnaires:** 0 records

### After Migration (PostgreSQL RDS)
- **Database name:** `Health_DI`
- **Database size:** 8.13 MB
- **Cases:** 3 records ✅
- **Documents:** 3 records ✅
- **Slots:** 0 records
- **WhatsApp messages:** 0 records
- **Questionnaires:** 0 records

### Migrated Case Data

| Case ID | Patient Name | Status | Category |
|---------|--------------|--------|----------|
| ICS-150626-8CEF | Tejas Salvi | scheduled | normal |
| ICS-150626-6DF4 | Tejas Salvi22 | pending | pre_existing |
| ICS-150626-3743 | Tejas Salvi 3 | pending | pre_existing |

### Migrated Documents

| Document Name | Case ID | Type |
|---------------|---------|------|
| output.png | ICS-150626-6DF4 | image |
| Tejas Salvi Undergraduate Degree_compressed-compressed.pdf | ICS-150626-6DF4 | document |
| Key_Report_ICSA_KA_2024-25_001234_20260613_163922.pdf | ICS-150626-3743 | document |

---

## 🔧 Environment Configuration

### `.env` File Settings

```env
# ============================================
# DATABASE CONFIGURATION - AWS RDS POSTGRESQL
# ============================================
DB_TYPE=postgresql
RDS_HOST=motor-v2-db.cn2euyuwcn9z.ap-south-1.rds.amazonaws.com
RDS_PORT=5432
RDS_USER=motoradmin
RDS_PASSWORD=ics_forensics
RDS_DATABASE=Health_DI

# ============================================
# ALTERNATIVE: Direct Connection String
# ============================================
# DATABASE_URL=postgresql+asyncpg://motoradmin:ics_forensics@motor-v2-db.cn2euyuwcn9z.ap-south-1.rds.amazonaws.com:5432/Health_DI

# ============================================
# APP CONFIGURATION
# ============================================
APP_NAME=FARE AutoSpect - DI Health
DEBUG=True
SECRET_KEY=your-secret-key-change-in-production

# ============================================
# GOOGLE SERVICES (Optional)
# ============================================
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_DRIVE_FOLDER_ID=

# ============================================
# WHATSAPP CLOUD API (Optional)
# ============================================
WHATSAPP_API_URL=https://graph.facebook.com/v25.0
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_VERIFY_TOKEN=

# ============================================
# GEMINI AI (Optional)
# ============================================
GEMINI_API_KEY=
```

---

## 📁 Project Structure & Key Files

### Configuration Files
```
backend/
├── .env                          # Environment variables (DB credentials)
├── app/
│   ├── config.py                 # Settings class with RDS config
│   ├── database.py               # Database connection (asyncpg + SQLAlchemy)
│   └── models.py                 # SQLAlchemy models with health_ prefix
├── main.py                       # FastAPI application entry point
└── scripts/
    ├── check_db.py               # Database verification script
    ├── verify_data.py            # Data verification script
    └── migrate_complete.py       # Complete migration script
```

### Key Code Snippets

#### Database Connection (`app/database.py`)
```python
def get_database_url(self) -> str:
    if self.DB_TYPE == "postgresql" and self.RDS_HOST:
        return f"postgresql+asyncpg://{self.RDS_USER}:{self.RDS_PASSWORD}@{self.RDS_HOST}:{self.RDS_PORT}/{self.RDS_DATABASE}"
    else:
        return "sqlite+aiosqlite:///./di_health.db"
```

#### Model Definition (`app/models.py`)
```python
class DICase(Base):
    __tablename__ = "health_di_cases"  # Note the health_ prefix
    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String(50), unique=True, nullable=False, index=True)
    # ... other columns
```

---

## 🚀 Migration Process Steps

### Step 1: Install Required Packages
```bash
pip install asyncpg psycopg2-binary
```

### Step 2: Create Database on RDS
```python
# create_db.py
import asyncpg
import asyncio

async def create_database():
    conn = await asyncpg.connect(
        host="motor-v2-db.cn2euyuwcn9z.ap-south-1.rds.amazonaws.com",
        user="motoradmin",
        password="ics_forensics",
        database="postgres"
    )
    await conn.execute("CREATE DATABASE Health_DI")
    await conn.close()

asyncio.run(create_database())
```

### Step 3: Update Configuration Files
- Update `app/config.py` with RDS settings
- Update `app/database.py` with PostgreSQL connection logic
- Update `app/models.py` with `health_` table prefix
- Configure `.env` file with RDS credentials

### Step 4: Run Migration
```bash
python scripts/migrate_complete.py
```

### Step 5: Verify Migration
```bash
python scripts/verify_data.py
```

---

## 🔍 Verification Commands

### Check Database Connection
```bash
python -c "import asyncpg, asyncio; asyncio.run(asyncpg.connect(host='motor-v2-db.cn2euyuwcn9z.ap-south-1.rds.amazonaws.com', user='motoradmin', password='ics_forensics', database='Health_DI'))" && echo "✅ Connected"
```

### List All Tables
```bash
python -c "
import asyncpg, asyncio
async def main():
    conn = await asyncpg.connect(host='motor-v2-db.cn2euyuwcn9z.ap-south-1.rds.amazonaws.com', user='motoradmin', password='ics_forensics', database='Health_DI')
    tables = await conn.fetch(\"SELECT tablename FROM pg_tables WHERE schemaname='public'\")
    for t in tables: print(t['tablename'])
    await conn.close()
asyncio.run(main())
"
```

### Count Records in Each Table
```bash
python -c "
import asyncpg, asyncio
async def main():
    conn = await asyncpg.connect(host='motor-v2-db.cn2euyuwcn9z.ap-south-1.rds.amazonaws.com', user='motoradmin', password='ics_forensics', database='Health_DI')
    tables = ['health_di_cases', 'health_case_documents', 'health_scheduled_slots', 'health_whatsapp_messages', 'health_questionnaires']
    for t in tables:
        count = await conn.fetchval(f'SELECT COUNT(*) FROM {t}')
        print(f'{t}: {count} rows')
    await conn.close()
asyncio.run(main())
"
```

---

## 📊 Useful SQL Queries

### View All Cases
```sql
SELECT case_id, name, phone_number, status, created_at 
FROM health_di_cases 
ORDER BY created_at DESC;
```

### Cases by Status
```sql
SELECT status, COUNT(*) as count 
FROM health_di_cases 
GROUP BY status;
```

### Documents per Case
```sql
SELECT case_id, COUNT(*) as document_count, 
       string_agg(file_name, ', ') as files
FROM health_case_documents 
GROUP BY case_id;
```

### Today's Scheduled Meetings
```sql
SELECT case_id, name, scheduled_time, meeting_link
FROM health_di_cases 
WHERE status = 'scheduled' 
  AND DATE(scheduled_time) = CURRENT_DATE;
```

### Database Size
```sql
SELECT pg_database_size(current_database()) as size_bytes,
       pg_size_pretty(pg_database_size(current_database())) as size_pretty;
```

### Table Sizes
```sql
SELECT 
    tablename,
    pg_size_pretty(pg_total_relation_size('public.' || tablename)) as size
FROM pg_tables 
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size('public.' || tablename) DESC;
```

---

## 🐛 Common Issues & Solutions

### Issue 1: Database Doesn't Exist
**Error:** `database "Health_DI" does not exist`

**Solution:** Create database first
```bash
python create_db.py
```

### Issue 2: Date/Time Format Error
**Error:** `invalid input for query argument: expected datetime instance, got str`

**Solution:** Convert string dates to datetime objects
```python
from datetime import datetime
scheduled_time = datetime.fromisoformat(date_string)
```

### Issue 3: Connection Refused
**Error:** `could not connect to server`

**Solutions:**
- Check if RDS is accessible (security groups)
- Verify credentials in `.env`
- Test connection with psql

### Issue 4: Table Not Found
**Error:** `relation "health_di_cases" does not exist`

**Solution:** Run migration script to create tables
```bash
python migrate_complete.py
```

### Issue 5: Duplicate Key Violation
**Error:** `duplicate key value violates unique constraint`

**Solution:** Use `ON CONFLICT` or check existing records before insert

---

## 🔐 Security Best Practices

### Current Credentials (⚠️ For Reference Only)

**DO NOT COMMIT THESE TO GIT!** Use environment variables or secrets manager.

```
RDS_HOST: motor-v2-db.cn2euyuwcn9z.ap-south-1.rds.amazonaws.com
RDS_USER: motoradmin
RDS_PASSWORD: ics_forensics
RDS_DATABASE: Health_DI
```

### Recommended Security Improvements

1. **Use AWS Secrets Manager**
```python
import boto3
from botocore.exceptions import ClientError

def get_secret():
    session = boto3.session.Session()
    client = session.client('secretsmanager')
    response = client.get_secret_value(SecretId='rds/health-app')
    return json.loads(response['SecretString'])
```

2. **Use IAM Database Authentication**
```python
import boto3

def get_iam_token():
    client = boto3.client('rds')
    token = client.generate_db_auth_token(
        DBHostname=RDS_HOST,
        Port=RDS_PORT,
        DBUsername=RDS_USER,
        Region='ap-south-1'
    )
    return token
```

3. **Enable RDS Encryption at Rest**
- Already enabled for this RDS instance

4. **Use SSL/TLS for Connections**
```python
engine = create_async_engine(
    database_url,
    connect_args={"ssl": "require"}
)
```

---

## 📈 Performance Considerations

### Connection Pool Settings
```python
engine = create_async_engine(
    database_url,
    pool_size=10,        # Number of connections to maintain
    max_overflow=20,     # Extra connections when needed
    pool_pre_ping=True,  # Verify connections before using
    pool_recycle=3600    # Recycle connections every hour
)
```

### Recommended Indexes (Already Created)
- Primary keys on all `id` columns
- Foreign key indexes on `case_id` columns
- Status and date indexes for filtering
- Composite indexes for common query patterns

### Query Optimization Tips
1. Use `SELECT` only needed columns, not `*`
2. Add `LIMIT` to large queries
3. Use `EXPLAIN ANALYZE` to check query plans
4. Consider partitioning for very large tables

---

## 🔄 Backup & Recovery

### Automated Backups (RDS)
- **Retention period:** 7 days (default)
- **Backup window:** Daily during maintenance window
- **Point-in-time recovery:** Available within retention period

### Manual Backup Commands

#### Dump Entire Database
```bash
pg_dump -h motor-v2-db.cn2euyuwcn9z.ap-south-1.rds.amazonaws.com \
        -U motoradmin \
        -d Health_DI \
        -F c \
        -f health_db_backup_$(date +%Y%m%d).dump
```

#### Restore from Backup
```bash
pg_restore -h motor-v2-db.cn2euyuwcn9z.ap-south-1.rds.amazonaws.com \
           -U motoradmin \
           -d Health_DI \
           health_db_backup_20260616.dump
```

#### Export Specific Table
```bash
pg_dump -h motor-v2-db.cn2euyuwcn9z.ap-south-1.rds.amazonaws.com \
        -U motoradmin \
        -d Health_DI \
        -t health_di_cases \
        -F c \
        -f cases_backup.dump
```

---

## 📝 Migration Checklist

### Pre-Migration
- [x] Install required packages (`asyncpg`, `psycopg2-binary`)
- [x] Verify RDS connectivity
- [x] Create target database (`Health_DI`)
- [x] Backup SQLite database (`di_health.db`)
- [x] Update configuration files

### Migration
- [x] Create tables with `health_` prefix
- [x] Migrate cases data
- [x] Migrate documents data
- [x] Migrate slots data
- [x] Migrate WhatsApp messages
- [x] Migrate questionnaires

### Post-Migration
- [x] Verify row counts
- [x] Test application connectivity
- [x] Update `.env` to use RDS
- [x] Test all API endpoints
- [x] Document connection details

---

## 🎯 Success Indicators

### ✅ Migration Success Checklist
- [x] Database `Health_DI` exists on RDS
- [x] All 5 tables created with `health_` prefix
- [x] 3 cases successfully migrated
- [x] 3 documents successfully migrated
- [x] Database size: 8.13 MB
- [x] Application connects to RDS
- [x] Queries return expected results

---

## 📞 Support & Troubleshooting

### Useful Commands Quick Reference

| Task | Command |
|------|---------|
| Test connection | `python check_db.py` |
| Verify data | `python verify_data.py` |
| Run migration | `python migrate_complete.py` |
| Start app | `python main.py` |
| Check RDS status | AWS Console → RDS → Health_DI |

### Logs Location
- **Application logs:** Console output when running `python main.py`
- **RDS logs:** AWS Console → RDS → Health_DI → Logs & events
- **Migration logs:** Console output from migration script

---

## 📚 Additional Resources

- [AWS RDS PostgreSQL Documentation](https://docs.aws.amazon.com/rds/index.html)
- [SQLAlchemy Async Documentation](https://docs.sqlalchemy.org/en/latest/orm/extensions/asyncio.html)
- [asyncpg Documentation](https://magicstack.github.io/asyncpg/current/)
- [FastAPI Database Guide](https://fastapi.tiangolo.com/tutorial/sql-databases/)

---

## ✍️ Notes for Future Reference

### Important Timestamps
- **Migration Date:** June 16, 2026
- **PostgreSQL Version:** 17.9
- **Database Size at Migration:** 8.13 MB
- **Initial Data:** 3 cases, 3 documents

### Known Working Configurations
- Python 3.11+
- SQLAlchemy 2.0.23
- asyncpg 0.29.0
- FastAPI 0.104.1

### Things to Remember
1. Always backup before migration
2. Keep SQLite as backup until verified
3. Use `health_` prefix for all new tables
4. Connection pool settings are optimized for this workload
5. RDS auto-backups run daily

---

**Migration Status:** ✅ **COMPLETE & SUCCESSFUL**

**Documentation Last Updated:** June 16, 2026

**Maintained by:** HEALTH Application Team
```

This README documents everything we did - database details, table structures, migration steps, verification commands, and troubleshooting tips for future reference! 📚