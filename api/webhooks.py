from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Form, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
import httpx
import hashlib
import hmac
import os
from datetime import datetime

from app.database import get_db
from app.models import DICase, CaseDocument, WhatsAppMessage
from app.config import settings
from services.storage_service import StorageFactory

router = APIRouter(prefix="/webhook", tags=["Webhooks"])

@router.get("/whatsapp")
async def verify_whatsapp_webhook(
    hub_mode: str,
    hub_verify_token: str,
    hub_challenge: int
):
    """Verify WhatsApp webhook"""
    
    if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        return hub_challenge
    
    raise HTTPException(403, "Invalid verification token")

@router.post("/whatsapp")
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    """Receive WhatsApp messages and documents"""
    
    data = await request.json()
    
    # Process each entry
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", [])
            
            for message in messages:
                background_tasks.add_task(
                    process_whatsapp_message,
                    message=message,
                    phone_number_id=value.get("metadata", {}).get("phone_number_id")
                )
    
    return {"status": "ok"}

async def process_whatsapp_message(message: dict, phone_number_id: str):
    """Process incoming WhatsApp message"""
    
    from_number = message.get("from")
    message_type = message.get("type")
    
    # Find case by phone number
    async for db in get_db():
        result = await db.execute(
            select(DICase).where(DICase.phone_number == from_number)
        )
        case = result.scalar_one_or_none()
        
        if not case:
            # Store as unknown for now
            print(f"No case found for number: {from_number}")
            return
        
        # ✅ Use StorageFactory instead of DriveService
        storage = StorageFactory.get_storage_service()
        
        if message_type == "text":
            text_body = message.get("text", {}).get("body", "")
            
            # Store message
            whatsapp_msg = WhatsAppMessage(
                message_id=message.get("id"),
                from_number=from_number,
                case_id=case.case_id,
                message_text=text_body,
                message_type="text",
                is_incoming=True
            )
            db.add(whatsapp_msg)
            await db.commit()
            
        elif message_type in ["image", "document"]:
            # Get media ID
            media_id = message.get(message_type, {}).get("id")
            
            # Download media from WhatsApp
            media_content, file_extension = await download_whatsapp_media(media_id)
            
            if media_content:
                # Generate filename
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                file_name = f"{message_type}_{timestamp}.{file_extension or 'jpg'}"
                
                # ✅ Save file using storage service
                try:
                    file_url = await storage.save_file(
                        file_content=media_content,
                        file_name=file_name,
                        file_type=message_type,
                        case_id=case.case_id
                    )
                    
                    # Store in database
                    document = CaseDocument(
                        case_id=case.case_id,
                        file_name=file_name,
                        file_url=file_url,
                        file_type=message_type,
                        source="whatsapp"
                    )
                    db.add(document)
                    
                    # Store message record
                    whatsapp_msg = WhatsAppMessage(
                        message_id=message.get("id"),
                        from_number=from_number,
                        case_id=case.case_id,
                        message_type=message_type,
                        media_url=file_url,
                        is_incoming=True
                    )
                    db.add(whatsapp_msg)
                    
                    await db.commit()
                    print(f"✅ Saved WhatsApp {message_type} for case {case.case_id}")
                    
                except Exception as e:
                    print(f"❌ Error saving WhatsApp media: {e}")
                    await db.rollback()
        
        break  # Exit db session

async def download_whatsapp_media(media_id: str) -> tuple[Optional[bytes], Optional[str]]:
    """
    Download media from WhatsApp servers
    Returns: (file_content, file_extension)
    """
    
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            # Get media URL
            response = await client.get(
                f"{settings.WHATSAPP_API_URL}/{media_id}",
                headers=headers
            )
            
            if response.status_code != 200:
                print(f"❌ Failed to get media URL: {response.status_code}")
                return None, None
            
            media_data = response.json()
            media_url = media_data.get("url")
            mime_type = media_data.get("mime_type", "image/jpeg")
            
            if not media_url:
                print("❌ No media URL in response")
                return None, None
            
            # Download the actual media
            media_response = await client.get(media_url, headers=headers)
            
            if media_response.status_code != 200:
                print(f"❌ Failed to download media: {media_response.status_code}")
                return None, None
            
            # Determine file extension from mime type
            extension_map = {
                "image/jpeg": "jpg",
                "image/png": "png",
                "image/gif": "gif",
                "image/webp": "webp",
                "application/pdf": "pdf",
                "application/msword": "doc",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
                "text/plain": "txt",
            }
            file_extension = extension_map.get(mime_type, "bin")
            
            return media_response.content, file_extension
            
        except Exception as e:
            print(f"❌ Error downloading WhatsApp media: {e}")
            return None, None