# api/auth.py - COMPLETE FIXED VERSION
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
import bcrypt
import logging

from app.database import get_db
from app.models import User
from app.auth_utils import create_token, get_current_user, get_current_admin_user
from app.auth_utils import create_token, get_current_user, get_current_admin_user  # ← IMPORT THESE

router = APIRouter(prefix="/api/auth", tags=["Authentication"])
logger = logging.getLogger(__name__)

# ============ MODELS ============
class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    token: str
    user: dict

class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "investigator"

class PasswordChangeRequest(BaseModel):  # ← ADD THIS
    username: str
    new_password: str

class UserUpdateRequest(BaseModel):  # ← ADD THIS
    role: Optional[str] = None

# ============ ENDPOINTS ============

@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """Authenticate user from database"""
    
    logger.info(f"Login attempt: {request.username}")
    
    # 1. Query user from database
    result = await db.execute(
        select(User).where(User.username == request.username)
    )
    user = result.scalar_one_or_none()
    
    # 2. Check if user exists
    if not user:
        logger.warning(f"User not found: {request.username}")
        raise HTTPException(
            status_code=401, 
            detail="Invalid username or password"
        )
    
    # 3. Verify password using bcrypt
    try:
        if not bcrypt.checkpw(
            request.password.encode('utf-8'),
            user.password_hash.encode('utf-8')
        ):
            logger.warning(f"Invalid password for: {request.username}")
            raise HTTPException(
                status_code=401, 
                detail="Invalid username or password"
            )
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Authentication error"
        )
    
    # 4. Create JWT token
    token = create_token(user)
    
    # 5. Return response
    user_info = {
        "username": user.username,
        "role": user.role,
        "id": user.id
    }
    
    logger.info(f"✅ Login successful: {request.username}")
    
    return LoginResponse(token=token, user=user_info)


@router.post("/logout")
async def logout():
    """Logout user"""
    return {"message": "Logged out successfully"}


@router.get("/verify")
async def verify_token(current_user: User = Depends(get_current_user)):
    """Verify if token is valid"""
    return {
        "valid": True,
        "user": {
            "id": current_user.id,
            "username": current_user.username,
            "role": current_user.role
        }
    }


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    """Get current user info"""
    return {
        "id": current_user.id,
        "username": current_user.username,
        "role": current_user.role,
        "created_at": current_user.created_at
    }


@router.post("/create-user")
async def create_user(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """Create new user (admin only)"""
    
    # Check if user exists
    result = await db.execute(
        select(User).where(User.username == user_data.username)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail="Username already exists"
        )
    
    # Hash password
    password_hash = bcrypt.hashpw(
        user_data.password.encode('utf-8'),
        bcrypt.gensalt()
    )
    
    # Create user
    new_user = User(
        username=user_data.username,
        password_hash=password_hash.decode(),
        role=user_data.role
    )
    
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    
    logger.info(f"✅ User created: {user_data.username}")
    
    return {
        "message": "User created successfully",
        "user": {
            "id": new_user.id,
            "username": new_user.username,
            "role": new_user.role,
            "created_at": new_user.created_at
        }
    }


@router.get("/users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """List all users (admin only)"""
    
    result = await db.execute(select(User))
    users = result.scalars().all()
    
    return {
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "role": u.role,
                "created_at": u.created_at,
                "is_active": getattr(u, 'is_active', True)
            }
            for u in users
        ],
        "count": len(users)
    }


@router.post("/change-password")
async def change_password(
    request: PasswordChangeRequest,  # ← FIXED: Uses Pydantic model
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """Change password for any user (admin only)"""
    
    # Validate password length
    if len(request.new_password) < 8:
        raise HTTPException(
            status_code=400, 
            detail="Password must be at least 8 characters"
        )
    
    # Find user
    result = await db.execute(
        select(User).where(User.username == request.username)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=404, 
            detail="User not found"
        )
    
    # Hash new password
    password_hash = bcrypt.hashpw(
        request.new_password.encode('utf-8'),
        bcrypt.gensalt()
    )
    user.password_hash = password_hash.decode()
    
    await db.commit()
    
    logger.info(f"✅ Password changed for: {request.username} by admin: {current_user.username}")
    
    return {
        "message": f"Password updated for {request.username}",
        "user": {
            "id": user.id,
            "username": user.username,
            "role": user.role
        }
    }


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """Hard delete a user (admin only)"""
    
    # Prevent self-deletion
    if user_id == current_user.id:
        raise HTTPException(
            status_code=400, 
            detail="Cannot delete yourself"
        )
    
    # Find user
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=404, 
            detail="User not found"
        )
    
    # Store username for logging
    username = user.username
    
    # Delete user
    await db.delete(user)
    await db.commit()
    
    logger.info(f"🗑️ User deleted: {username} by admin: {current_user.username}")
    
    return {
        "message": f"User {username} deleted successfully",
        "deleted_user_id": user_id
    }


@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    user_data: UserUpdateRequest,  # ← FIXED: Uses Pydantic model
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """Update user role (admin only)"""
    
    # Prevent self-role change
    if user_id == current_user.id:
        raise HTTPException(
            status_code=400, 
            detail="Cannot modify your own role"
        )
    
    # Find user
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=404, 
            detail="User not found"
        )
    
    # Update role if provided
    if user_data.role is not None:
        valid_roles = ['administrator', 'investigator', 'analyst', 'viewer']
        if user_data.role not in valid_roles:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}"
            )
        user.role = user_data.role
        await db.commit()
        await db.refresh(user)
        
        logger.info(f"✅ Role updated for: {user.username} → {user.role} by admin: {current_user.username}")
    
    return {
        "message": f"User {user.username} updated successfully",
        "user": {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "created_at": user.created_at
        }
    }


@router.post("/users/{user_id}/deactivate")
async def deactivate_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """Deactivate/Activate a user (admin only)"""
    
    # Prevent self-deactivation
    if user_id == current_user.id:
        raise HTTPException(
            status_code=400, 
            detail="Cannot deactivate yourself"
        )
    
    # Find user
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=404, 
            detail="User not found"
        )
    
    # Toggle is_active (if column exists)
    # For now, we'll just toggle if the column exists
    try:
        user.is_active = not user.is_active
        await db.commit()
        status = "activated" if user.is_active else "deactivated"
    except AttributeError:
        # If is_active column doesn't exist yet
        status = "deactivated (is_active column not found)"
        logger.warning(f"is_active column not found for user: {user.username}")
    
    logger.info(f"👤 User {status}: {user.username} by admin: {current_user.username}")
    
    return {
        "message": f"User {user.username} {status} successfully",
        "user_id": user_id,
        "is_active": getattr(user, 'is_active', None)
    }


@router.post("/users/{user_id}/activate")
async def activate_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)
):
    """Activate a user (admin only)"""
    
    # Find user
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=404, 
            detail="User not found"
        )
    
    try:
        user.is_active = True
        await db.commit()
        logger.info(f"👤 User activated: {user.username} by admin: {current_user.username}")
    except AttributeError:
        logger.warning(f"is_active column not found for user: {user.username}")
    
    return {
        "message": f"User {user.username} activated successfully",
        "user_id": user_id
    }