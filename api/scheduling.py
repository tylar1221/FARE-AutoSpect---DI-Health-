# api/scheduling.py - COMPLETE FIXED VERSION

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime, date, time, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
import pytz
from app.models import User
from services.whatsapp_service import get_whatsapp_service

from app.database import get_db
from app.models import DICase, ScheduledSlot
from app.auth_utils import get_current_user
from services.calendar_service import CalendarService
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
    duration_minutes: int = 30

# ============ GET CALENDAR INFO ============
@router.get("/calendar-info")
async def get_calendar_info():
    """Get the current calendar ID, name, and status"""
    calendar = CalendarService()
    
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
        "status": "connected" if calendar.service else "disconnected"
    }

# ============ GET AVAILABLE SLOTS ============
@router.get("/slots")
async def get_available_slots(
    slot_date: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user) 
):
    """Get available time slots with metadata"""
    try:
        target_date = datetime.strptime(slot_date, "%Y-%m-%d").date()
        
        if target_date.weekday() >= 5:
            return {
                "date": slot_date,
                "working_day": False,
                "slots": [],
                "message": "Weekend - no slots available"
            }
        
        calendar = CalendarService()
        
        if not calendar.service:
            return {
                "date": slot_date,
                "working_day": True,
                "slots": [],
                "message": "Calendar service unavailable"
            }
        
        slots = await calendar.get_available_slots_with_metadata(
            date_obj=target_date,
            duration_minutes=30
        )
        
        result = await db.execute(
            select(ScheduledSlot).where(
                ScheduledSlot.slot_date == target_date,
                ScheduledSlot.status == "booked"
            )
        )
        db_booked = result.scalars().all()
        
        for slot in slots:
            for db_slot in db_booked:
                db_start = db_slot.slot_start.strftime("%H:%M")
                if slot["start"] == db_start:
                    slot["is_available"] = False
                    if not slot["booked_by"]:
                        slot["booked_by"] = f"DB: {db_slot.case_id}"
                    slot["case_id"] = db_slot.case_id
                    slot["meet_link"] = db_slot.meet_link
        
        return {
            "date": slot_date,
            "working_day": True,
            "slots": slots,
            "total_slots": len(slots),
            "available_slots": sum(1 for s in slots if s["is_available"]),
            "booked_slots": sum(1 for s in slots if not s["is_available"])
        }
        
    except ValueError:
        raise HTTPException(400, "Invalid date format. Use YYYY-MM-DD")
    except Exception as e:
        print(f"❌ Error getting slots: {e}")
        raise HTTPException(500, f"Failed to get slots: {str(e)}")

# ============ BOOK A SLOT ============
@router.post("/book")
async def book_meeting(
    request: BookingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Book a meeting with proper timezone handling and WhatsApp notification"""
    try:
        # 1. Get case
        result = await db.execute(
            select(DICase).where(DICase.case_id == request.case_id, DICase.user_id == current_user.id)
        )
        case = result.scalar_one_or_none()
        
        if not case:
            raise HTTPException(404, f"Case {request.case_id} not found")
        
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
        
        # 3. Check if slot is already booked in calendar
        calendar = CalendarService()
        
        if not calendar.service:
            raise HTTPException(500, "Calendar service not available")
        
        busy_times = await calendar.get_busy_times(slot_date)
        
        for busy_start, busy_end, _, _, _ in busy_times:
            if busy_start.tzinfo is None:
                busy_start = tz.localize(busy_start)
            if busy_end.tzinfo is None:
                busy_end = tz.localize(busy_end)
            
            if not (end_time <= busy_start or start_time >= busy_end):
                raise HTTPException(400, "This slot is already booked in calendar")
        
        # 4. Create event in calendar
        start_naive = make_timezone_naive(start_time)
        end_naive = make_timezone_naive(end_time)
        
        event_id, meet_link = await calendar.create_meeting_event(
            case_name=case.name,
            case_id=case.case_id,
            date=slot_date,
            start_time=start_naive.time(),
            end_time=end_naive.time(),
            phone_number=case.phone_number
        )
        
        if not event_id or not meet_link:
            raise HTTPException(500, "Failed to create calendar event")
        
        # 5. Save booking to database
        booking = ScheduledSlot(
            case_id=case.case_id,
            slot_date=slot_date,
            slot_start=start_naive.time(),
            slot_end=end_naive.time(),
            meet_link=meet_link,
            status="booked"
        )
        db.add(booking)
        
        # 6. Update case
        case.status = "scheduled"
        case.meeting_link = meet_link
        case.event_id = event_id
        case.scheduled_time = start_naive
        
        await db.commit()
        
        # ============================================================
        # ✅ SEND WHATSAPP CONFIRMATION
        # ============================================================
       # ============================================================
        # ✅ SEND WHATSAPP CONFIRMATION
        # ============================================================
        try:
            from services.whatsapp_service import get_whatsapp_service
            from app.models import WhatsAppMessage
            
            whatsapp = get_whatsapp_service()
            confirm_success = whatsapp.send_booking_confirmation(
                to_number=case.phone_number,
                case_id=case.case_id,
                name=case.name,
                meeting_date=start_time,
                meeting_link=meet_link,
                drive_link=None,  # ← ADD THIS
                claim_id=case.claim_id
            )
            
            if confirm_success:
                print(f"✅ WhatsApp confirmation sent for {case.case_id}")
                
                # Save to database
                confirm_msg = WhatsAppMessage(
                    case_id=case.case_id,
                    from_number="System",
                    to_number=case.phone_number,
                    message_body=f"📋 Booking confirmation sent",
                    message_type="confirmation",
                    status="sent",
                    sent_at=datetime.now(),
                    is_read=True,
                    is_incoming=False
                )
                db.add(confirm_msg)
                await db.commit()
            else:
                print(f"⚠️ Failed to send WhatsApp confirmation for {case.case_id}")
        except Exception as whatsapp_error:
            print(f"⚠️ WhatsApp error: {whatsapp_error}")
            # Don't fail the booking if WhatsApp fails
            
        
        return {
            "message": "Meeting scheduled successfully",
            "meet_link": meet_link,
            "event_id": event_id,
            "case_id": case.case_id,
            "scheduled_time": start_time.isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        print(f"❌ Booking failed: {e}")
        raise HTTPException(500, f"Failed to book: {str(e)}")