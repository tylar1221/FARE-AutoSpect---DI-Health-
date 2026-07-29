"""
Webhook handlers for WhatsApp and external services
"""

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from fastapi.responses import PlainTextResponse, JSONResponse
from typing import Optional
import json
import logging
from datetime import datetime

from app.config import settings
from services.whatsapp_service import get_whatsapp_service
from api.logs import push_log

router = APIRouter(prefix="/webhook", tags=["Webhooks"])
logger = logging.getLogger(__name__)

# Store processed messages to prevent duplicates
processed_messages = set()
MAX_PROCESSED = 1000

# ============ WHATSAPP WEBHOOK VERIFICATION ============
@router.get("/whatsapp")
async def verify_whatsapp_webhook(
    hub_mode: str,
    hub_verify_token: str,
    hub_challenge: str
):
    """Verify WhatsApp webhook with Meta"""
    
    whatsapp = get_whatsapp_service()
    challenge = whatsapp.verify_webhook(hub_mode, hub_verify_token, hub_challenge)
    
    if challenge:
        logger.info("✅ WhatsApp webhook verified successfully")
        return PlainTextResponse(content=challenge)
    
    logger.warning("❌ WhatsApp webhook verification failed")
    raise HTTPException(status_code=403, detail="Verification failed")


# ============ WHATSAPP INCOMING MESSAGES ============
@router.post("/whatsapp")
async def handle_whatsapp_message(request: Request, background_tasks: BackgroundTasks):
    """Handle incoming WhatsApp messages"""
    
    try:
        data = await request.json()
        logger.info(f"📨 Webhook received: {json.dumps(data, indent=2)}")
        
        # Process each entry
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])
                
                for message in messages:
                    # Process message in background
                    background_tasks.add_task(
                        process_incoming_message,
                        message=message,
                        phone_number_id=value.get("metadata", {}).get("phone_number_id")
                    )
        
        return JSONResponse(content={"status": "ok"})
        
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return JSONResponse(content={"status": "error", "message": str(e)}, status_code=500)


# ============ PROCESS INCOMING MESSAGE ============
async def process_incoming_message(message: dict, phone_number_id: str):
    """Process a single incoming WhatsApp message"""
    
    from_number = message.get("from")
    message_type = message.get("type")
    message_id = message.get("id")
    
    # Check for duplicates
    if message_id in processed_messages:
        logger.warning(f"⚠️ Duplicate message: {message_id}")
        return
    
    processed_messages.add(message_id)
    if len(processed_messages) > MAX_PROCESSED:
        processed_messages.clear()
    
    logger.info(f"📥 Message from {from_number}, type: {message_type}")
    
    # Get message text based on type
    if message_type == "text":
        message_text = message["text"]["body"]
        await handle_text_message(from_number, message_text, message_id)
    
    elif message_type == "interactive":
        button_id = message["interactive"]["button_reply"]["id"]
        await handle_interactive_response(from_number, button_id, message_id)
    
    elif message_type == "image":
        image_data = message.get("image", {})
        media_id = image_data.get("id")
        caption = image_data.get("caption", "")
        await handle_media_message(from_number, "image", media_id, caption, message_id)
    
    elif message_type == "document":
        doc_data = message.get("document", {})
        media_id = doc_data.get("id")
        filename = doc_data.get("filename", "document.pdf")
        caption = doc_data.get("caption", "")
        await handle_media_message(from_number, "document", media_id, caption, message_id, filename)
    
    elif message_type == "audio":
        audio_data = message.get("audio", {})
        media_id = audio_data.get("id")
        duration = audio_data.get("duration", 0)
        await handle_media_message(from_number, "audio", media_id, "", message_id, duration=duration)
    
    elif message_type == "video":
        video_data = message.get("video", {})
        media_id = video_data.get("id")
        caption = video_data.get("caption", "")
        duration = video_data.get("duration", 0)
        await handle_media_message(from_number, "video", media_id, caption, message_id, duration=duration)
    
    elif message_type == "location":
        location = message.get("location", {})
        latitude = location.get("latitude")
        longitude = location.get("longitude")
        name = location.get("name", "")
        await handle_location_message(from_number, latitude, longitude, name, message_id)
    
    else:
        logger.info(f"⚠️ Unhandled message type: {message_type}")
        await push_log({
            "type": "whatsapp_unknown",
            "message": f"Unknown message type: {message_type} from {from_number}"
        })


# ============ HANDLE TEXT MESSAGES ============
async def handle_text_message(from_number: str, message_text: str, message_id: str):
    """Handle text messages - check for yes/no responses"""
    
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy import select
    from app.database import get_db
    from app.models import DICase, WhatsAppMessage
    
    message_lower = message_text.lower().strip()
    
    # Find case by phone number
    async for db in get_db():
        result = await db.execute(
            select(DICase).where(DICase.phone_number == from_number)
        )
        case = result.scalar_one_or_none()
        
        if not case:
            # Try to find by phone number with different formatting
            # For now, just log
            logger.warning(f"No case found for {from_number}")
            break
        
        case_id = case.case_id
        
        # Save message to database
        whatsapp_msg = WhatsAppMessage(
            case_id=case_id,
            from_number=from_number,
            to_number=settings.WHATSAPP_PHONE_NUMBER_ID,
            message_body=message_text,
            message_type="text",
            status="received"
        )
        db.add(whatsapp_msg)
        await db.commit()
        
        # Check for confirmation responses
        if message_lower in ["yes", "available", "ok", "confirm"]:
            await handle_yes_response(case_id, from_number)
        elif message_lower in ["no", "not available", "unavailable"]:
            await handle_no_response(case_id, from_number)
        
        break


# ============ HANDLE YES RESPONSE ============
async def handle_yes_response(case_id: str, from_number: str):
    """Handle when customer confirms availability"""
    
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy import select, update
    from app.database import get_db
    from app.models import DICase, ScheduledSlot
    from services.whatsapp_service import get_whatsapp_service
    from services.calendar_service import CalendarService
    from datetime import datetime, timedelta, date, time
    import pytz
    
    IST = pytz.timezone('Asia/Kolkata')
    whatsapp = get_whatsapp_service()
    calendar = CalendarService()
    
    async for db in get_db():
        # Get case and pending slot
        result = await db.execute(
            select(DICase, ScheduledSlot).join(
                ScheduledSlot, DICase.case_id == ScheduledSlot.case_id
            ).where(
                DICase.case_id == case_id,
                ScheduledSlot.status == "pending"
            )
        )
        row = result.first()
        
        if not row:
            logger.warning(f"No pending slot for {case_id}")
            break
        
        case, slot = row
        
        # Create calendar event
        slot_datetime = datetime.combine(slot.slot_date, slot.slot_start)
        slot_datetime = IST.localize(slot_datetime)
        end_datetime = slot_datetime + timedelta(minutes=30)
        
        event_id, meet_link = await calendar.create_meeting_event(
            case_name=case.name,
            case_id=case.case_id,
            date=slot.slot_date,
            start_time=slot.slot_start,
            end_time=slot.slot_end,
            phone_number=case.phone_number
        )
        
        if not event_id or not meet_link:
            logger.error(f"Failed to create calendar event for {case_id}")
            break
        
        # Update case
        await db.execute(
            update(DICase)
            .where(DICase.case_id == case_id)
            .values(
                status="scheduled",
                meeting_link=meet_link,
                event_id=event_id,
                scheduled_time=slot_datetime
            )
        )
        
        # Update slot
        await db.execute(
            update(ScheduledSlot)
            .where(ScheduledSlot.id == slot.id)
            .values(status="booked", meet_link=meet_link)
        )
        
        await db.commit()
        
        # Send confirmation
        success = whatsapp.send_booking_confirmation(
            to_number=from_number,
            case_id=case.case_id,
            name=case.name,
            meeting_date=slot_datetime,
            meeting_link=meet_link
        )
        
        if success:
            await push_log({
                "type": "whatsapp_confirmation",
                "message": f"Confirmation sent to {from_number} for case {case_id}"
            })
        
        break


# ============ HANDLE NO RESPONSE ============
async def handle_no_response(case_id: str, from_number: str):
    """Handle when customer says not available"""
    
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy import update
    from app.database import get_db
    from app.models import DICase
    from services.whatsapp_service import get_whatsapp_service
    
    whatsapp = get_whatsapp_service()
    
    async for db in get_db():
        # Update case status
        await db.execute(
            update(DICase)
            .where(DICase.case_id == case_id)
            .values(status="pending")
        )
        await db.commit()
        
        break
    
    # Send manual contact message
    message = f"""No problem!

📋 Case ID: {case_id}

Our team will contact you to find a suitable time.

We apologise for the inconvenience!

Regards,
FARE AutoSpect Team"""

    whatsapp.send_message(from_number, message)


# ============ HANDLE INTERACTIVE RESPONSE ============
async def handle_interactive_response(from_number: str, button_id: str, message_id: str):
    """Handle button clicks from interactive messages"""
    
    if button_id.startswith("AVAILABLE_"):
        case_id = button_id.replace("AVAILABLE_", "")
        await handle_yes_response(case_id, from_number)
    
    elif button_id.startswith("UNAVAILABLE_"):
        case_id = button_id.replace("UNAVAILABLE_", "")
        await handle_no_response(case_id, from_number)


# ============ HANDLE MEDIA MESSAGES ============
async def handle_media_message(from_number: str, media_type: str, media_id: str, 
                              caption: str = "", message_id: str = "", 
                              filename: str = None, duration: int = 0):
    """Handle media messages (images, documents, audio, video)"""
    
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy import select
    from app.database import get_db
    from app.models import DICase, CaseDocument, WhatsAppMessage
    from services.storage_service import StorageFactory
    from services.whatsapp_service import get_whatsapp_service
    import os
    
    whatsapp = get_whatsapp_service()
    storage = StorageFactory.get_storage_service()
    
    # Find case
    async for db in get_db():
        result = await db.execute(
            select(DICase).where(DICase.phone_number == from_number)
        )
        case = result.scalar_one_or_none()
        
        if not case:
            logger.warning(f"No case found for {from_number}")
            break
        
        # Download media
        file_content, mime_type, downloaded_filename = whatsapp.download_media(media_id)
        
        if not file_content:
            logger.error(f"Failed to download {media_type} for {from_number}")
            break
        
        # Save file
        if not filename:
            extension = os.path.splitext(downloaded_filename)[1] if downloaded_filename else ".bin"
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{media_type}_{timestamp}{extension}"
        
        try:
            file_url = await storage.save_file(
                file_content=file_content,
                file_name=filename,
                file_type=media_type,
                case_id=case.case_id
            )
            
            # Save to database
            document = CaseDocument(
                case_id=case.case_id,
                file_name=filename,
                file_url=file_url,
                file_type=media_type,
                source="whatsapp"
            )
            db.add(document)
            
            # Save message
            message_body = f"{media_type.capitalize()}: {filename}"
            if caption:
                message_body += f"\nCaption: {caption}"
            if duration:
                message_body += f"\nDuration: {duration}s"
            
            whatsapp_msg = WhatsAppMessage(
                case_id=case.case_id,
                from_number=from_number,
                to_number=settings.WHATSAPP_PHONE_NUMBER_ID,
                message_body=message_body,
                message_type=media_type,
                status="received"
            )
            db.add(whatsapp_msg)
            
            await db.commit()
            logger.info(f"✅ {media_type} saved for case {case.case_id}")
            
        except Exception as e:
            logger.error(f"Error saving {media_type}: {e}")
            await db.rollback()
        
        break


# ============ HANDLE LOCATION MESSAGES ============
async def handle_location_message(from_number: str, latitude: float, longitude: float, 
                                 name: str, message_id: str):
    """Handle location messages"""
    
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy import select
    from app.database import get_db
    from app.models import DICase, WhatsAppMessage
    
    async for db in get_db():
        result = await db.execute(
            select(DICase).where(DICase.phone_number == from_number)
        )
        case = result.scalar_one_or_none()
        
        if case:
            maps_link = f"https://www.google.com/maps?q={latitude},{longitude}"
            location_text = f"📍 {name}\n🗺️ {maps_link}" if name else f"📍 {maps_link}"
            
            whatsapp_msg = WhatsAppMessage(
                case_id=case.case_id,
                from_number=from_number,
                to_number=settings.WHATSAPP_PHONE_NUMBER_ID,
                message_body=location_text,
                message_type="location",
                status="received"
            )
            db.add(whatsapp_msg)
            await db.commit()
        
        break


# ============ API ENDPOINTS FOR SENDING MESSAGES ============

class SendMessageRequest(BaseModel):
    case_id: str
    message: str

class SendReminderRequest(BaseModel):
    case_id: str

class SendCompletionRequest(BaseModel):
    case_id: str

@router.post("/send-whatsapp")
async def send_custom_whatsapp(request: SendMessageRequest):
    """Send a custom WhatsApp message"""
    
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy import select
    from app.database import get_db
    from app.models import DICase
    from services.whatsapp_service import get_whatsapp_service
    
    whatsapp = get_whatsapp_service()
    
    async for db in get_db():
        result = await db.execute(
            select(DICase).where(DICase.case_id == request.case_id)
        )
        case = result.scalar_one_or_none()
        
        if not case:
            raise HTTPException(404, "Case not found")
        
        success, msg_id = whatsapp.send_message(
            to_number=case.phone_number,
            message=request.message
        )
        
        if success:
            return {"success": True, "message_id": msg_id}
        else:
            raise HTTPException(500, "Failed to send message")


@router.post("/send-reminder")
async def send_reminder_whatsapp(request: SendReminderRequest):
    """Send reminder for a case"""
    
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy import select
    from app.database import get_db
    from app.models import DICase
    from services.whatsapp_service import get_whatsapp_service
    
    whatsapp = get_whatsapp_service()
    
    async for db in get_db():
        result = await db.execute(
            select(DICase).where(DICase.case_id == request.case_id)
        )
        case = result.scalar_one_or_none()
        
        if not case:
            raise HTTPException(404, "Case not found")
        
        if not case.scheduled_time or not case.meeting_link:
            raise HTTPException(400, "No meeting scheduled")
        
        success = whatsapp.send_reminder(
            to_number=case.phone_number,
            name=case.name,
            case_id=case.case_id,
            meeting_time=case.scheduled_time,
            meeting_link=case.meeting_link
        )
        
        if success:
            return {"success": True}
        else:
            raise HTTPException(500, "Failed to send reminder")


@router.post("/send-completion")
async def send_completion_whatsapp(request: SendCompletionRequest):
    """Send completion message for a case"""
    
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy import select
    from app.database import get_db
    from app.models import DICase
    from services.whatsapp_service import get_whatsapp_service
    
    whatsapp = get_whatsapp_service()
    
    async for db in get_db():
        result = await db.execute(
            select(DICase).where(DICase.case_id == request.case_id)
        )
        case = result.scalar_one_or_none()
        
        if not case:
            raise HTTPException(404, "Case not found")
        
        success = whatsapp.send_completion(
            to_number=case.phone_number,
            name=case.name,
            case_id=case.case_id,
            claim_id=case.claim_id
        )
        
        if success:
            return {"success": True}
        else:
            raise HTTPException(500, "Failed to send completion")