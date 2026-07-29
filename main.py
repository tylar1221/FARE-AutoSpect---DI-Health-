# main.py - CORRECTED VERSION (Single lifespan function)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
from api import cases, scheduling, webhooks, auth, logs, db
from app.database import init_db, check_db_connection
from app.config import settings
from fastapi.responses import RedirectResponse

# ============ SINGLE LIFESPAN FUNCTION (MERGED) ============
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print(f"Starting {settings.APP_NAME}...")
    print(f"Database Type: {settings.DB_TYPE}")
    print(f"Storage Type: {settings.STORAGE_TYPE}")  # ✅ Added storage type
    
    if settings.STORAGE_TYPE == "google_drive":
        print(f"📁 Using Google Drive storage")
        print(f"   Drive Parent Folder ID: {settings.DRIVE_PARENT_FOLDER_ID}")
    else:
        print(f"💾 Using Local storage")
    
    # Check database connection
    if not await check_db_connection():
        print("⚠️ Database connection issue - continuing anyway...")
    else:
        print("✅ Database connection successful")
    
    # Initialize database (creates tables if they don't exist)
    await init_db()
    print("Database initialized")
    
    # Create uploads directory for file storage
    uploads_dir = "uploads"
    if not os.path.exists(uploads_dir):
        os.makedirs(uploads_dir, exist_ok=True)
        print(f"📁 Created uploads directory: {uploads_dir}")
    
    # For PostgreSQL, log the connection pool status
    if settings.DB_TYPE == "postgresql":
        print(f"🔗 PostgreSQL connection pool: size=10, max_overflow=20")
    
    yield  # ← This is what makes it a context manager!
    
    # Shutdown
    print("Shutting down...")

# ============ APP CREATION ============
app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    lifespan=lifespan  # ← Uses the single lifespan function
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(cases.router)
app.include_router(scheduling.router)
app.include_router(webhooks.router)
app.include_router(auth.router)
app.include_router(logs.router)
app.include_router(db.router)

# ============ STATIC FILES ============
static_dir = "static"
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir, html=True), name="static")
    print(f"✅ Static files mounted from {static_dir}")
else:
    print(f"⚠️ Static directory '{static_dir}' not found. Create it for frontend files.")

# ============ FILE UPLOADS STORAGE ============
uploads_dir = "uploads"
if not os.path.exists(uploads_dir):
    os.makedirs(uploads_dir, exist_ok=True)

app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")
print(f"✅ Uploads directory mounted: {uploads_dir}")

# ============ ROOT ENDPOINT ============
@app.get("/")
async def root():
    db_type = "postgresql" if settings.DB_TYPE == "postgresql" else "sqlite"
    
    return {
        "app": settings.APP_NAME,
        "status": "running",
        "version": "1.0.0",
        "database": db_type,
        "storage_type": settings.STORAGE_TYPE,  # ← Added storage type
        "storage_path": "uploads/",
        "endpoints": [
            {"path": "/api/cases", "methods": ["GET", "POST"]},
            {"path": "/api/cases/{case_id}", "methods": ["GET", "PUT", "DELETE"]},
            {"path": "/api/cases/{case_id}/upload", "methods": ["POST"]},
            {"path": "/api/cases/{case_id}/documents", "methods": ["GET"]},
            {"path": "/api/cases/{case_id}/documents/{doc_id}", "methods": ["DELETE"]},
            {"path": "/api/scheduling/slots", "methods": ["GET"]},
            {"path": "/api/scheduling/book", "methods": ["POST"]},
            {"path": "/api/auth/login", "methods": ["POST"]},
            {"path": "/webhook/whatsapp", "methods": ["GET", "POST"]},
        ]
    }

# ============ HEALTH CHECK ============
@app.get("/health")
async def health_check():
    db_status = "unknown"
    
    try:
        db_connected = await check_db_connection()
        db_status = "healthy" if db_connected else "unhealthy"
    except Exception as e:
        db_status = f"error: {str(e)}"
    
    return {
        "status": "healthy",
        "database": settings.DB_TYPE,
        "database_status": db_status,
        "storage": settings.STORAGE_TYPE,  # ← Updated to show actual storage type
        "storage_path": "uploads/"
    }

# ============ DATABASE INFO ============
@app.get("/db-info")
async def db_info():
    return {
        "database_type": settings.DB_TYPE,
        "host": settings.RDS_HOST if settings.DB_TYPE == "postgresql" else "local",
        "database_name": settings.RDS_DATABASE if settings.DB_TYPE == "postgresql" else "di_health.db",
        "pool_size": 10 if settings.DB_TYPE == "postgresql" else "N/A",
        "storage_type": settings.STORAGE_TYPE  # ← Added storage type
    }

# ============ MAIN ============
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    
    print(f"\n{'='*50}")
    print(f"🚀 Starting {settings.APP_NAME}")
    print(f"{'='*50}")
    print(f"📍 Server: http://localhost:{port}")
    print(f"🗄️  Database: {settings.DB_TYPE.upper()}")
    print(f"💾 Storage: {settings.STORAGE_TYPE.upper()}")  # ← Added storage type
    
    if settings.DB_TYPE == "postgresql":
        print(f"🔗 RDS Host: {settings.RDS_HOST}")
        print(f"💾 Database: {settings.RDS_DATABASE}")
    else:
        print(f"💾 Database: SQLite (di_health.db)")
    
    if settings.STORAGE_TYPE == "google_drive":
        print(f"📁 Drive Folder ID: {settings.DRIVE_PARENT_FOLDER_ID}")
    
    print(f"📁 Static files: http://localhost:{port}/static/login.html")
    print(f"💾 Uploads directory: {os.path.abspath('uploads')}")
    print(f"🔗 Health check: http://localhost:{port}/health")
    print(f"{'='*50}\n")
    
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=port,
        reload=settings.DEBUG
    )