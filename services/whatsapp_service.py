"""
WhatsApp Service - Complete Working Version
Handles sending messages, templates, media, and webhook verification
"""

import os
import requests
import json
from datetime import datetime, date, time, timedelta
from typing import Optional, Tuple, Dict, Any
from app.config import settings
import logging

logger = logging.getLogger(__name__)

class WhatsAppService:
    """Complete WhatsApp Service with all functionality"""
    
    def __init__(self):
        self.api_url = settings.WHATSAPP_API_URL
        self.access_token = settings.WHATSAPP_ACCESS_TOKEN
        self.phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
        self.verify_token = settings.WHATSAPP_VERIFY_TOKEN
        self.base_url = f"{self.api_url}/{self.phone_number_id}/messages"
        
        # Template names
        self.TEMPLATE_CONFIRMATION = "desktop_verification_with_button_v3"
        self.TEMPLATE_REMINDER = "insurance_claim_call_reminder_with_link"
        self.TEMPLATE_COMPLETION = "claim_verification_completed_v2"
        self.TEMPLATE_MEETING_MISSED = "missed_claim_verification_call"
        self.TEMPLATE_CALL_MISSED = "claim_contact_update_v2"
    
    # ============ WEBHOOK VERIFICATION ============
    def verify_webhook(self, hub_mode: str, hub_verify_token: str, hub_challenge: str) -> Optional[str]:
        """Verify webhook with Meta"""
        if hub_mode == "subscribe" and hub_verify_token == self.verify_token:
            return hub_challenge
        return None
    
    # ============ SEND TEXT MESSAGE ============
    def send_message(self, to_number: str, message: str) -> Tuple[bool, str]:
        """Send a plain text WhatsApp message"""
        to_number = to_number.lstrip("+")
        
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "text",
            "text": {"body": message}
        }
        
        try:
            response = requests.post(self.base_url, headers=headers, json=payload, timeout=15)
            
            if response.status_code == 200:
                msg_id = response.json().get("messages", [{}])[0].get("id", "")
                logger.info(f"✅ WhatsApp sent to {to_number}")
                return True, msg_id
            
            logger.error(f"❌ WhatsApp failed: {response.status_code} - {response.text}")
            return False, ""
            
        except Exception as e:
            logger.error(f"❌ WhatsApp error: {e}")
            return False, ""
    
    # ============ SEND TEMPLATE MESSAGE ============
    def send_template_message(self, to_number: str, template_name: str, 
                             body_params: list = None, button_params: list = None) -> Tuple[bool, str]:
        """Send a WhatsApp template message"""
        to_number = to_number.lstrip("+")
        
        # Build components
        components = []
        
        if body_params:
            components.append({
                "type": "body",
                "parameters": body_params
            })
        
        if button_params:
            components.append({
                "type": "button",
                "sub_type": "url",
                "index": 0,
                "parameters": button_params
            })
        
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": "en"}
            }
        }
        
        if components:
            payload["template"]["components"] = components
        
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        
        try:
            response = requests.post(self.base_url, headers=headers, json=payload, timeout=15)
            
            if response.status_code == 200:
                msg_id = response.json().get("messages", [{}])[0].get("id", "")
                logger.info(f"✅ Template '{template_name}' sent to {to_number}")
                return True, msg_id
            
            logger.error(f"❌ Template failed: {response.status_code} - {response.text}")
            return False, ""
            
        except Exception as e:
            logger.error(f"❌ Template error: {e}")
            return False, ""
    
    # ============ SEND CONFIRMATION (After Slot Assignment) ============
    def send_booking_confirmation(
        self,
        to_number: str,
        case_id: str,
        name: str,
        meeting_date: datetime,
        meeting_link: str,
        claim_id: str = None
    ) -> bool:
        """Send booking confirmation with meeting link"""
        
        # Convert to IST
        from datetime import timezone, timedelta
        IST = timezone(timedelta(hours=5, minutes=30))
        
        if meeting_date.tzinfo is None:
            meeting_date = meeting_date.replace(tzinfo=timezone.utc)
        
        indian_time = meeting_date.astimezone(IST)
        formatted_time = indian_time.strftime('%I:%M %p').lstrip('0')
        formatted_date = indian_time.strftime('%A, %B %d, %Y')
        
        display_id = claim_id if claim_id else case_id
        
        # Extract meeting ID from URL
        meeting_path = meeting_link.replace("https://", "").replace("http://", "")
        if meeting_path.startswith("meet.google.com/"):
            meeting_path = meeting_path.replace("meet.google.com/", "")
        if "?" in meeting_path:
            meeting_path = meeting_path.split("?")[0]
        if meeting_path.endswith("/"):
            meeting_path = meeting_path[:-1]
        
        # Template parameters
        body_params = [
            {"type": "text", "text": name},           # {{1}}
            {"type": "text", "text": display_id},     # {{2}}
            {"type": "text", "text": formatted_date}, # {{3}}
            {"type": "text", "text": formatted_time}, # {{4}}
            {"type": "text", "text": meeting_path},   # {{5}}
        ]
        
        button_params = [
            {"type": "text", "text": meeting_path}    # URL parameter
        ]
        
        success, _ = self.send_template_message(
            to_number,
            self.TEMPLATE_CONFIRMATION,
            body_params=body_params,
            button_params=button_params
        )
        
        if success:
            logger.info(f"✅ Confirmation sent to {to_number} for case {case_id}")
        else:
            # Fallback to plain text
            message = f"""✅ Your consultation is confirmed!

📋 Case: {case_id}
👤 {name}
📅 {formatted_date}
🕒 {formatted_time}

🔗 Join Meeting: {meeting_link}

Please join 5 minutes early."""
            success, _ = self.send_message(to_number, message)
        
        return success
    
    # ============ SEND REMINDER ============
    def send_reminder(self, to_number: str, name: str, case_id: str, 
                     meeting_time: datetime, meeting_link: str) -> bool:
        """Send meeting reminder"""
        
        from datetime import timezone, timedelta
        IST = timezone(timedelta(hours=5, minutes=30))
        
        if meeting_time.tzinfo is None:
            meeting_time = meeting_time.replace(tzinfo=timezone.utc)
        
        indian_time = meeting_time.astimezone(IST)
        formatted_time = indian_time.strftime('%I:%M %p').lstrip('0')
        formatted_date = indian_time.strftime('%A, %B %d, %Y')
        
        # Try template first
        body_params = [
            {"type": "text", "text": name},
            {"type": "text", "text": case_id},
            {"type": "text", "text": formatted_date},
            {"type": "text", "text": formatted_time},
            {"type": "text", "text": meeting_link}
        ]
        
        success, _ = self.send_template_message(
            to_number,
            self.TEMPLATE_REMINDER,
            body_params=body_params
        )
        
        if not success:
            # Fallback
            message = f"""🔔 REMINDER: Your consultation is today!

📅 {formatted_date}
🕒 {formatted_time}

🔗 Join: {meeting_link}

Please join 5 minutes early."""
            success, _ = self.send_message(to_number, message)
        
        return success
    
    # ============ SEND COMPLETION ============
    def send_completion(self, to_number: str, name: str, case_id: str, claim_id: str = None) -> bool:
        """Send completion message"""
        
        display_id = claim_id if claim_id else case_id
        
        body_params = [
            {"type": "text", "text": name},
            {"type": "text", "text": display_id}
        ]
        
        success, _ = self.send_template_message(
            to_number,
            self.TEMPLATE_COMPLETION,
            body_params=body_params
        )
        
        if not success:
            message = f"""✅ Verification Complete!

Dear {name},

Your health claim verification for case {display_id} has been completed.

The report has been generated and will be shared with the insurance company.

Thank you for your cooperation."""
            success, _ = self.send_message(to_number, message)
        
        return success
    
    # ============ SEND MEETING MISSED ============
    def send_meeting_missed(self, to_number: str, name: str, case_id: str, claim_id: str = None) -> bool:
        """Send meeting missed notification"""
        
        display_id = claim_id if claim_id else case_id
        
        body_params = [
            {"type": "text", "text": name},
            {"type": "text", "text": display_id}
        ]
        
        success, _ = self.send_template_message(
            to_number,
            self.TEMPLATE_MEETING_MISSED,
            body_params=body_params
        )
        
        if not success:
            message = f"""⚠️ You missed your verification meeting for case {display_id}.

Our team will contact you to reschedule.

Please respond to this message."""
            success, _ = self.send_message(to_number, message)
        
        return success
    
    # ============ SEND CALL MISSED ============
    def send_call_missed(self, to_number: str, name: str, case_id: str, claim_id: str = None) -> bool:
        """Send call missed notification"""
        
        display_id = claim_id if claim_id else case_id
        
        body_params = [
            {"type": "text", "text": name},
            {"type": "text", "text": display_id}
        ]
        
        success, _ = self.send_template_message(
            to_number,
            self.TEMPLATE_CALL_MISSED,
            body_params=body_params
        )
        
        if not success:
            message = f"""📞 We tried to contact you for claim {display_id}.

Please call us back or reply to this message.

Regards,
FARE AutoSpect Team"""
            success, _ = self.send_message(to_number, message)
        
        return success
    
    # ============ SEND AVAILABILITY CHECK (With Buttons) ============
    def send_availability_check(self, to_number: str, name: str, 
                               slot_date: date, slot_time: time, case_id: str) -> bool:
        """Send interactive availability check with buttons"""
        
        to_number = to_number.lstrip("+")
        
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        
        # Format time
        slot_datetime = datetime.combine(slot_date, slot_time)
        formatted_time = slot_datetime.strftime('%I:%M %p').lstrip('0')
        formatted_date = slot_datetime.strftime('%A, %B %d, %Y')
        
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {
                    "text": (
                        f"Hello {name}!\n\n"
                        f"Your consultation has been scheduled for:\n"
                        f"📅 {formatted_date}\n"
                        f"🕒 {formatted_time}\n"
                        f"Duration: 15 minutes\n\n"
                        f"Are you available at this time?"
                    )
                },
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {
                                "id": f"AVAILABLE_{case_id}",
                                "title": "Yes, Available"
                            }
                        },
                        {
                            "type": "reply",
                            "reply": {
                                "id": f"UNAVAILABLE_{case_id}",
                                "title": "Not Available"
                            }
                        }
                    ]
                }
            }
        }
        
        try:
            response = requests.post(self.base_url, headers=headers, json=payload, timeout=10)
            
            if response.status_code == 200:
                logger.info(f"✅ Availability check sent to {to_number}")
                return True
            
            logger.error(f"❌ Availability check failed: {response.text}")
            return False
            
        except Exception as e:
            logger.error(f"❌ Availability check error: {e}")
            return False
    
    # ============ DOWNLOAD MEDIA ============
    def download_media(self, media_id: str) -> Tuple[Optional[bytes], Optional[str], Optional[str]]:
        """Download media from WhatsApp"""
        
        try:
            # Get media URL
            url = f"https://graph.facebook.com/v25.0/{media_id}"
            headers = {"Authorization": f"Bearer {self.access_token}"}
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code != 200:
                logger.error(f"Failed to get media info: {response.text}")
                return None, None, None
            
            media_info = response.json()
            download_url = media_info.get("url")
            mime_type = media_info.get("mime_type", "application/octet-stream")
            
            if not download_url:
                return None, None, None
            
            # Download file
            file_response = requests.get(download_url, headers=headers, timeout=30)
            
            if file_response.status_code == 200:
                extension = self._get_extension_from_mime(mime_type)
                filename = f"whatsapp_{datetime.now().strftime('%Y%m%d_%H%M%S')}{extension}"
                return file_response.content, mime_type, filename
            
            return None, None, None
            
        except Exception as e:
            logger.error(f"Media download error: {e}")
            return None, None, None
    
    def _get_extension_from_mime(self, mime_type: str) -> str:
        """Get file extension from MIME type"""
        mime_map = {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
            "application/pdf": ".pdf",
            "application/msword": ".doc",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
            "text/plain": ".txt",
            "audio/mpeg": ".mp3",
            "audio/ogg": ".ogg",
            "video/mp4": ".mp4",
            "video/webm": ".webm"
        }
        return mime_map.get(mime_type, ".bin")


# Singleton instance
_whatsapp_service = None

def get_whatsapp_service() -> WhatsAppService:
    """Get or create WhatsApp service instance"""
    global _whatsapp_service
    if _whatsapp_service is None:
        _whatsapp_service = WhatsAppService()
    return _whatsapp_service