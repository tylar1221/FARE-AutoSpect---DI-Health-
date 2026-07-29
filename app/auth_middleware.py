# app/auth_middleware.py
from fastapi import Request, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional

security = HTTPBearer()

# List of public endpoints (no auth required)
PUBLIC_ENDPOINTS = [
    "/",
    "/health",
    "/docs",
    "/openapi.json",
    "/api/auth/login",
    "/static/login.html",
    "/static/dashboard.html",
    "/static/js/",
    "/static/css/"
]

async def verify_auth(request: Request):
    """Verify authentication for protected endpoints"""
    
    # Check if endpoint is public
    for endpoint in PUBLIC_ENDPOINTS:
        if request.url.path.startswith(endpoint):
            return True
    
    # Get token from header
    auth_header = request.headers.get("Authorization")
    
    if not auth_header:
        # For static files, allow access (UI handles auth)
        if request.url.path.startswith("/static/"):
            return True
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # In production, verify JWT token here
    return True