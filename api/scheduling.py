# api/scheduling.py - COMPLETE UPDATED VERSION with Per-User Calendar Support

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from datetime import datetime, date, time, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
import pytz
import re

from app.database import get_db
from app.models import DICase, ScheduledSlot, User, WhatsAppMessage
from app.auth_utils import get_current_user
from services.calendar_service import CalendarService
from services.whatsapp_service import get_whatsapp_service
from api.logs import push_log

router = APIRouter(prefix="/api/scheduling", tags=["Scheduling"])

# ============ TIMEZONE HELPER ============
def get_indian_timezone():
    """Get Indian timezone (Asia/Kolkata)"""
    return pytz.timezone('Asia/Kolkata')

def make_timezone_aware(dt: datetime) -> datetime:
    """Make a datetime timezone-aware using Indian timezone"""
    if dt.tzinfo is None:
        tz = get_indian_timezone()
        return tz.localize(dt)
    return dt

def make_timezone_naive(dt: datetime) -> datetime:
    """Make a datetime timezone-naive"""
    if dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt

# ============ MODELS ============
class BookingRequest(BaseModel):
    case_id: str
    slot_date: str
    slot_time: str
    duration_minutes: int = 10

class UpdateUserCalendarRequest(BaseModel):
    calendar_id: str

# ============ GET CALENDAR INFO (Per-User) ============
@router.get("/calendar-info")
async def get_calendar_info(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get calendar info for the currently logged-in user.
    Uses the user's specific calendar_id from the users table.
    """
    # Get user's calendar ID from database
    user_result = await db.execute(
        select(User.calendar_id).where(User.id == current_user.id)
    )
    user_calendar_id = user_result.scalar_one_or_none()
    
    # Initialize calendar service with user_id
    calendar = CalendarService(user_id=current_user.id)
    
    # Get calendar name
    calendar_name = "FARE AutoSpect - DI Health"
    
    if calendar.service:
        try:
            calendar_metadata = calendar.service.calendarList().get(
                calendarId=calendar.calendar_id
            ).execute()
            calendar_name = calendar_metadata.get('summary', calendar_name)
            print(f"📋 Calendar Name: {calendar_name}")
        except Exception as e:
            print(f"⚠️ Could not fetch calendar name: {e}")
    
    return {
        "calendar_id": calendar.calendar_id,
        "calendar_name": calendar.get_calendar_name(),
        "is_authenticated": calendar.service is not None,
        "status": "connected" if calendar.service else "disconnected",
        "user_id": current_user.id,
        "username": current_user.username,
        "role": current_user.role,
        "has_custom_calendar": user_calendar_id is not None
    }

# ============ GET AVAILABLE SLOTS (Per-User) ============
@router.get("/slots")
async def get_available_slots(
    slot_date: str = Query(..., description="Date in YYYY-MM-DD format"),
    duration_minutes: int = Query(10, description="Slot duration in minutes"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get available time slots from the current user's specific calendar.
    Each user sees only their own calendar slots.
    """
    try:
        target_date = datetime.strptime(slot_date, "%Y-%m-%d").date()
        
        # Check if working day (Monday-Friday)
        if target_date.weekday() >= 5:
            return {
                "date": slot_date,
                "working_day": False,
                "slots": [],
                "message": "Weekend - no slots available",
                "calendar_id": None,
                "user_id": current_user.id
            }
        
        # Initialize calendar service for this user
        calendar = CalendarService(user_id=current_user.id)
        
        if not calendar.service:
            return {
                "date": slot_date,
                "working_day": True,
                "slots": [],
                "message": "Calendar service unavailable",
                "calendar_id": calendar.calendar_id,
                "user_id": current_user.id
            }
        
        # Get slots from user's calendar
        slots = await calendar.get_available_slots_with_metadata(
            date_obj=target_date,
            duration_minutes=duration_minutes
        )
        
        # Get user's calendar info
        user_result = await db.execute(
            select(User.calendar_id).where(User.id == current_user.id)
        )
        user_calendar_id = user_result.scalar_one_or_none()
        
        return {
            "date": slot_date,
            "working_day": True,
            "slots": slots,
            "total_slots": len(slots),
            "available_slots": sum(1 for s in slots if s["is_available"]),
            "booked_slots": sum(1 for s in slots if not s["is_available"]),
            "calendar_id": calendar.calendar_id,
            "calendar_name": calendar.get_calendar_name(),
            "user_id": current_user.id,
            "username": current_user.username,
            "has_custom_calendar": user_calendar_id is not None
        }
        
    except ValueError:
        raise HTTPException(400, "Invalid date format. Use YYYY-MM-DD")
    except Exception as e:
        print(f"❌ Error getting slots: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Failed to get slots: {str(e)}")

# ============ BOOK A SLOT (Per-User) ============
@router.post("/book")
async def book_meeting(
    request: BookingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Book a meeting in the current user's specific calendar.
    Creates event in the user's calendar, not a shared one.
    """
    try:
        # 1. Get case and verify ownership
        result = await db.execute(
            select(DICase).where(
                DICase.case_id == request.case_id,
                DICase.user_id == current_user.id
            )
        )
        case = result.scalar_one_or_none()
        
        if not case:
            raise HTTPException(404, f"Case {request.case_id} not found or you don't have permission")
        
        if case.status == "scheduled":
            raise HTTPException(400, "Case already scheduled")
        
        # 2. Parse date and time
        slot_date = datetime.strptime(request.slot_date, "%Y-%m-%d").date()
        slot_time = datetime.strptime(request.slot_time, "%H:%M").time()
        
        # Create timezone-aware datetime
        tz = get_indian_timezone()
        start_time = datetime.combine(slot_date, slot_time)
        start_time = tz.localize(start_time)
        end_time = start_time + timedelta(minutes=request.duration_minutes)
        
        # 3. Initialize calendar service for this user
        calendar = CalendarService(user_id=current_user.id)
        
        if not calendar.service:
            raise HTTPException(500, "Calendar service not available")
        
        # 4. Check if slot is already booked in user's calendar
        busy_times = await calendar.get_busy_times(slot_date)
        
        for busy_start, busy_end, _, _, _ in busy_times:
            if busy_start.tzinfo is None:
                busy_start = tz.localize(busy_start)
            if busy_end.tzinfo is None:
                busy_end = tz.localize(busy_end)
            
            if not (end_time <= busy_start or start_time >= busy_end):
                raise HTTPException(409, "This slot is already booked in your calendar")
        
        # 5. Create event in user's calendar
        start_naive = make_timezone_naive(start_time)
        end_naive = make_timezone_naive(end_time)
        
        event_id, meet_link, meeting_rec_id, event_summary = await calendar.create_meeting_event(
            case_name=case.name,
            case_id=case.case_id,
            date=slot_date,
            start_time=start_naive.time(),
            end_time=end_naive.time(),
            phone_number=case.phone_number
        )
        
        if not event_id or not meet_link:
            raise HTTPException(500, "Failed to create calendar event")
        
        # 6. Save scheduled slot to database
        new_slot = ScheduledSlot(
            case_id=case.case_id,
            slot_date=slot_date,
            slot_start=slot_time,
            slot_end=end_time.time(),
            meet_link=meet_link,
            status="booked",
            user_id=current_user.id
        )
        db.add(new_slot)
        
        # 7. Update case
        case.status = "scheduled"
        case.meeting_link = meet_link
        case.event_id = event_id
        case.scheduled_time = start_naive
        case.updated_at = datetime.now()
        
        await db.commit()
        await db.refresh(new_slot)
        
        # 8. Send WhatsApp confirmation
        try:
            whatsapp = get_whatsapp_service()
            confirm_success = whatsapp.send_booking_confirmation(
                to_number=case.phone_number,
                case_id=case.case_id,
                name=case.name,
                meeting_date=start_time,
                meeting_link=meet_link,
                drive_link=case.drive_link,
                claim_id=case.claim_id
            )
            
            if confirm_success:
                print(f"✅ WhatsApp confirmation sent for {case.case_id}")
                
                # Save confirmation message to database
                confirm_msg = WhatsAppMessage(
                    case_id=case.case_id,
                    from_number="System",
                    to_number=case.phone_number,
                    message_body=f"📋 Meeting booked: {request.slot_date} at {request.slot_time}",
                    message_type="confirmation",
                    status="sent",
                    sent_at=datetime.now(),
                    is_read=True,
                    is_incoming=False,
                    user_id=current_user.id
                )
                db.add(confirm_msg)
                await db.commit()
            else:
                print(f"⚠️ Failed to send WhatsApp confirmation for {case.case_id}")
        except Exception as whatsapp_error:
            print(f"⚠️ WhatsApp error: {whatsapp_error}")
            # Don't fail the booking if WhatsApp fails
        
        # 9. Log the booking
        await push_log({
            "type": "meeting_booked",
            "message": f"Meeting booked for {case.case_id} by {current_user.username}",
            "data": {
                "case_id": case.case_id,
                "user_id": current_user.id,
                "username": current_user.username,
                "calendar_id": calendar.calendar_id,
                "meeting_link": meet_link,
                "slot_date": request.slot_date,
                "slot_time": request.slot_time
            }
        })
        
        return {
            "success": True,
            "message": "Meeting scheduled successfully",
            "meet_link": meet_link,
            "event_id": event_id,
            "case_id": case.case_id,
            "scheduled_time": start_time.isoformat(),
            "calendar_id": calendar.calendar_id,
            "calendar_name": calendar.get_calendar_name(),
            "user_id": current_user.id,
            "username": current_user.username
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        print(f"❌ Booking failed: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Failed to book: {str(e)}")

# ============ ADMIN: UPDATE USER CALENDAR ============
@router.patch("/admin/users/{user_id}/calendar")
async def update_user_calendar(
    user_id: int,
    data: UpdateUserCalendarRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update a user's calendar ID (admin only).
    This allows admins to assign specific calendars to users.
    """
    # Check if current user is admin
    if current_user.role != "administrator":
        raise HTTPException(403, "Admin access required")
    
    # Find user
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(404, "User not found")
    
    # Prevent changing own calendar (optional safety)
    if user_id == current_user.id:
        raise HTTPException(400, "Cannot modify your own calendar ID")
    
    # Update calendar ID
    await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(calendar_id=data.calendar_id)
    )
    await db.commit()
    
    # Log the change
    await push_log({
        "type": "user_calendar_updated",
        "message": f"Calendar ID updated for {user.username}",
        "data": {
            "user_id": user_id,
            "username": user.username,
            "calendar_id": data.calendar_id,
            "updated_by": current_user.username
        }
    })
    
    return {
        "success": True,
        "message": f"Calendar ID updated for {user.username}",
        "user_id": user_id,
        "username": user.username,
        "calendar_id": data.calendar_id,
        "updated_by": current_user.username
    }

# ============ ADMIN: GET USER CALENDAR ============
@router.get("/admin/users/{user_id}/calendar")
async def get_user_calendar(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get a user's calendar ID (admin only).
    """
    # Check if current user is admin
    if current_user.role != "administrator":
        raise HTTPException(403, "Admin access required")
    
    # Get user
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(404, "User not found")
    
    return {
        "user_id": user_id,
        "username": user.username,
        "calendar_id": user.calendar_id,
        "role": user.role
    }

# ============ ADMIN: LIST ALL USERS WITH CALENDARS ============
@router.get("/admin/users/calendars")
async def list_all_user_calendars(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List all users and their calendar IDs (admin only).
    """
    # Check if current user is admin
    if current_user.role != "administrator":
        raise HTTPException(403, "Admin access required")
    
    result = await db.execute(
        select(User.id, User.username, User.role, User.calendar_id, User.is_active)
        .order_by(User.username)
    )
    users = result.all()
    
    return {
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "role": u.role,
                "calendar_id": u.calendar_id,
                "is_active": u.is_active,
                "has_calendar": u.calendar_id is not None
            }
            for u in users
        ],
        "total": len(users)
    }

# ============ GET USER'S CALENDAR INFO (for frontend) ============
@router.get("/user-calendar")
async def get_user_calendar_info(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get the current user's calendar information.
    Used by frontend to display which calendar is being used.
    """
    # Get user's calendar ID
    user_result = await db.execute(
        select(User.calendar_id).where(User.id == current_user.id)
    )
    user_calendar_id = user_result.scalar_one_or_none()
    
    # Initialize calendar service
    calendar = await CalendarService.create(user_id=current_user.id)    
    calendar_name = "FARE AutoSpect - DI Health"
    if calendar.service:
        try:
            calendar_metadata = calendar.service.calendarList().get(
                calendarId=calendar.calendar_id
            ).execute()
            calendar_name = calendar_metadata.get('summary', calendar_name)
        except Exception as e:
            print(f"⚠️ Could not fetch calendar name: {e}")
    
    return {
        "user_id": current_user.id,
        "username": current_user.username,
        "role": current_user.role,
        "calendar_id": calendar.calendar_id,
        "calendar_name": calendar_name,
        "has_custom_calendar": user_calendar_id is not None,
        "is_authenticated": calendar.service is not None,
        "status": "connected" if calendar.service else "disconnected"
    }

# ============ UPDATE USER'S OWN CALENDAR (for users) ============
@router.patch("/user-calendar")
async def update_my_calendar(
    data: UpdateUserCalendarRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update the current user's own calendar ID.
    Users can update their own calendar ID.
    """
    # Validate calendar ID format (optional)
    if not data.calendar_id or len(data.calendar_id) < 5:
        raise HTTPException(400, "Invalid calendar ID format")
    
    # Update user's calendar ID
    await db.execute(
        update(User)
        .where(User.id == current_user.id)
        .values(calendar_id=data.calendar_id)
    )
    await db.commit()
    
    # Log the change
    await push_log({
        "type": "user_calendar_updated",
        "message": f"User {current_user.username} updated their own calendar",
        "data": {
            "user_id": current_user.id,
            "username": current_user.username,
            "calendar_id": data.calendar_id
        }
    })
    
    return {
        "success": True,
        "message": "Your calendar ID has been updated",
        "calendar_id": data.calendar_id
    }