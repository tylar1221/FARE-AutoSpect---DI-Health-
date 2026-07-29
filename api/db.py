# api/db.py - Complete Working Version
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime

from app.database import get_db

router = APIRouter(prefix="/api/db", tags=["Database"])

class QueryRequest(BaseModel):
    query: str

@router.post("/query")
async def execute_query(
    request: QueryRequest,
    db: AsyncSession = Depends(get_db)
):
    """Execute SQL query"""
    
    query = request.query.strip()
    
    # Log the query
    print(f"📝 Executing: {query[:100]}...")
    
    try:
        # Execute query
        result = await db.execute(text(query))
        
        # Check if this is a SELECT query
        if result.returns_rows:
            # Fetch all rows
            rows = result.fetchall()
            columns = list(result.keys())
            
            # Convert to list of dictionaries
            data = []
            for row in rows:
                row_dict = {}
                for i, col in enumerate(columns):
                    value = row[i]
                    # Convert datetime to string
                    if isinstance(value, datetime):
                        value = value.isoformat()
                    row_dict[col] = value
                data.append(row_dict)
            
            print(f"✅ Returned {len(data)} rows")
            
            return {
                "success": True,
                "data": data,
                "row_count": len(data)
            }
        else:
            # For INSERT, UPDATE, DELETE
            await db.commit()
            affected = result.rowcount
            
            print(f"✅ Affected {affected} rows")
            
            return {
                "success": True,
                "affected_rows": affected
            }
            
    except Exception as e:
        await db.rollback()
        print(f"❌ Error: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }


@router.get("/tables")
async def get_tables(db: AsyncSession = Depends(get_db)):
    """Get all tables"""
    result = await db.execute(text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"))
    tables = [row[0] for row in result.fetchall()]
    return {"tables": tables}


@router.get("/schema/{table_name}")
async def get_schema(table_name: str, db: AsyncSession = Depends(get_db)):
    """Get table schema"""
    result = await db.execute(text(f"PRAGMA table_info({table_name})"))
    columns = []
    for row in result.fetchall():
        columns.append({
            "name": row[1],
            "type": row[2],
            "nullable": not bool(row[3]),
            "primary_key": bool(row[5])
        })
    return {"table": table_name, "columns": columns}