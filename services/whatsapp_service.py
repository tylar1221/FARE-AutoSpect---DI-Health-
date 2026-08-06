"""
WhatsApp Service - Complete with Template Support
Handles sending messages, templates, media download, and webhook verification
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
    """WhatsApp Service with template support"""
    
    def __init__(self):
        self.api_url = settings.WHATSAPP_API_URL
        self.access_token = settings.WHATSAPP_ACCESS_TOKEN
        self.phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
        self.verify_token = settings.WHATSAPP_VERIFY_TOKEN
        self.base_url = f"{self.api_url}/{self.phone_number_id}/messages"
    
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
    
    # ============ TEMPLATE: BOOKING CONFIRMATION ============
    def send_booking_confirmation(
        self,
        to_number: str,
        case_id: str,
        name: str,
        meeting_date: datetime,
        meeting_link: str,
        drive_link: str = None,
        claim_id: str = None
    ) -> Tuple[bool, str, Optional[str]]:
        """Send booking confirmation using template"""
        
        from datetime import timezone, timedelta
        IST = timezone(timedelta(hours=5, minutes=30))
        
        if meeting_date.tzinfo is None:
            meeting_date = meeting_date.replace(tzinfo=timezone.utc)
        
        indian_time = meeting_date.astimezone(IST)
        formatted_time = indian_time.strftime('%I:%M %p').lstrip('0')
        formatted_date = indian_time.strftime('%A, %B %d, %Y')
        
        display_id = claim_id if claim_id else case_id
        
        # ✅ MATCHES YOUR APPROVED TEMPLATE: booking_confirmation
        # Variables: {{1}}=name, {{2}}=claim_id, {{3}}=date, {{4}}=time, {{5}}=meet_link
        # Generate the full template message
        template_message = f"""Dear {name},

        Your desktop verification call has been scheduled on behalf of the insurance company.

        Claim No: {display_id}
        Date: {formatted_date}
        Time: {formatted_time}

        Meeting Link: {meeting_link}

        Please keep the following documents ready:
        - Driving License of actual rider/driver at time of incident
        - ID Proof
        - RC Copy
        - Medical papers/injury photographs if any
        - Accident spot photographs
        - FIR/MCR/GD if available

        Kindly join 5 minutes before the scheduled time.

        Regards,
        Desktop Verification Team
        ICS Assure Services Pvt Ltd."""

        body_params = [
            {"type": "text", "text": name},
            {"type": "text", "text": display_id},
            {"type": "text", "text": formatted_date},
            {"type": "text", "text": formatted_time},
            {"type": "text", "text": meeting_link}
        ]

        success, msg_id = self.send_template_message(to_number, "booking_confirmation", body_params)

        if success:
            return True, msg_id, template_message

        success, msg_id = self.send_message(to_number, template_message)
        return success, msg_id, template_message

    # ============ TEMPLATE: MEETING REMINDER ============
    def send_meeting_reminder(
        self,
        to_number: str,
        name: str,
        case_id: str,
        meeting_time: datetime,
        meeting_link: str
    ) -> Tuple[bool, str, Optional[str]]:
        """Send meeting reminder using template"""
        
        from datetime import timezone, timedelta
        IST = timezone(timedelta(hours=5, minutes=30))
        
        if meeting_time.tzinfo is None:
            meeting_time = meeting_time.replace(tzinfo=timezone.utc)
        
        indian_time = meeting_time.astimezone(IST)
        formatted_time = indian_time.strftime('%I:%M %p').lstrip('0')
        formatted_date = indian_time.strftime('%A, %B %d, %Y')
        
        # ✅ MATCHES YOUR APPROVED TEMPLATE: meeting_reminder
        # Variables: {{1}}=name, {{2}}=case_id, {{3}}=date, {{4}}=time, {{5}}=meet_link
        # Generate the full template message
        template_message = f"""Dear {name},

        This is a reminder for your scheduled insurance claim verification call.

        Claim ID: {case_id}
        Date: {formatted_date}
        Time: {formatted_time}

        Please keep the following documents ready:

        - Driving License
        - ID Proof
        - RC Book
        - Medical Documents
        - FIR (if available)

        Please join the call 5 minutes before the scheduled time.

        Meeting Link: {meeting_link}

        Regards, 
        ICS Assure Services Pvt Ltd."""

        body_params = [
            {"type": "text", "text": name},
            {"type": "text", "text": case_id},
            {"type": "text", "text": formatted_date},
            {"type": "text", "text": formatted_time},
            {"type": "text", "text": meeting_link}
        ]

        success, msg_id = self.send_template_message(to_number, "meeting_reminder", body_params)

        if success:
            return True, msg_id, template_message

        success, msg_id = self.send_message(to_number, template_message)
        return success, msg_id, template_message

    # ============ TEMPLATE: VERIFICATION COMPLETE ============
    def send_verification_complete(
        self,
        to_number: str,
        name: str,
        case_id: str,
        claim_id: str = None
    ) -> Tuple[bool, str, Optional[str]]:
        """Send verification complete using template"""
        
        display_id = claim_id if claim_id else case_id
        
        # ✅ MATCHES YOUR APPROVED TEMPLATE: verification_complete
        # Variables: {{1}}=name, {{2}}=claim_id
        # Generate the full template message
        template_message = f"""Dear {name},

        Verification for claim ID {display_id} has been completed successfully.

        Your claim details have been recorded for processing.

        If additional documents are required, further communication may be shared regarding the claim process.

        Regards,
        ICS Assure Services Pvt Ltd."""

        body_params = [
            {"type": "text", "text": name},
            {"type": "text", "text": display_id}
        ]

        success, msg_id = self.send_template_message(to_number, "verification_complete", body_params)

        if success:
            return True, msg_id, template_message

        success, msg_id = self.send_message(to_number, template_message)
        return success, msg_id, template_message
    # ============ SEND CONFIRMATION (Plain Text Fallback) ============
    def send_confirmation(
        self,
        to_number: str,
        case_id: str,
        name: str,
        meeting_date: datetime,
        meeting_link: str,
        drive_link: str = None,
        claim_id: str = None
    ) -> Tuple[bool, str]:
        """Send booking confirmation - tries template first, falls back to plain text"""
        
        # Try template first
        success, msg_id = self.send_booking_confirmation(
            to_number, case_id, name, meeting_date, meeting_link, drive_link, claim_id
        )
        
        if success:
            return True, msg_id
        
        # Fallback to plain text
        from datetime import timezone, timedelta
        IST = timezone(timedelta(hours=5, minutes=30))
        
        if meeting_date.tzinfo is None:
            meeting_date = meeting_date.replace(tzinfo=timezone.utc)
        
        indian_time = meeting_date.astimezone(IST)
        formatted_time = indian_time.strftime('%I:%M %p').lstrip('0')
        formatted_date = indian_time.strftime('%A, %B %d, %Y')
        
        display_id = claim_id if claim_id else case_id
        
        # ✅ MATCHES YOUR TEMPLATE FORMAT
        message = f"""Dear {name},

    Your desktop verification call has been scheduled on behalf of the insurance company.

    Claim No: {display_id}
    Date: {formatted_date}
    Time: {formatted_time}

    Meeting Link: {meeting_link}

    Please keep the following documents ready:
    - Driving License of actual rider/driver at time of incident
    - ID Proof
    - RC Copy
    - Medical papers/injury photographs if any
    - Accident spot photographs
    - FIR/MCR/GD if available

    Kindly join 5 minutes before the scheduled time.

    Regards,
    Desktop Verification Team
    ICS Assure Services Pvt Ltd."""
        
        return self.send_message(to_number, message)
    
    # ============ SEND REMINDER (Plain Text Fallback) ============
    def send_reminder(
        self,
        to_number: str,
        name: str,
        case_id: str,
        meeting_time: datetime,
        meeting_link: str
    ) -> Tuple[bool, str,Optional[str]]:
        """Send meeting reminder - tries template first, falls back to plain text"""
        
        # Try template first
        success, msg_id , template_message = self.send_meeting_reminder(
            to_number, name, case_id, meeting_time, meeting_link
        )
        
        if success:
            return True, msg_id, template_message
        
        # Fallback to plain text
        from datetime import timezone, timedelta
        IST = timezone(timedelta(hours=5, minutes=30))
        
        if meeting_time.tzinfo is None:
            meeting_time = meeting_time.replace(tzinfo=timezone.utc)
        
        indian_time = meeting_time.astimezone(IST)
        formatted_time = indian_time.strftime('%I:%M %p').lstrip('0')
        formatted_date = indian_time.strftime('%A, %B %d, %Y')
        
        # ✅ MATCHES YOUR TEMPLATE FORMAT
        message = f"""Dear {name},

    This is a reminder for your scheduled insurance claim verification call.

    Claim ID: {case_id}
    Date: {formatted_date}
    Time: {formatted_time}

    Please keep the following documents ready:

    - Driving License
    - ID Proof
    - RC Book
    - Medical Documents
    - FIR (if available)

    Please join the call 5 minutes before the scheduled time.

    Meeting Link: {meeting_link}

    Regards, 
    ICS Assure Services Pvt Ltd."""
        
        return self.send_message(to_number, message)

    # ============ SEND COMPLETION (Plain Text Fallback) ============
    def send_completion(
    self,
    to_number: str,
    name: str,
    case_id: str,
    claim_id: str = None
) -> Tuple[bool, str, Optional[str]]:  # ← CHANGE TO 3
        """Send completion message - tries template first, falls back to plain text"""
        
        # Try template first
        success, msg_id, template_message = self.send_verification_complete(  # ← UNPACK 3
            to_number, name, case_id, claim_id
        )
        
        if success:
            return True, msg_id, template_message  # ← RETURN 3
        
        # Fallback to plain text
        display_id = claim_id if claim_id else case_id
        
        message = f"""Dear {name},

    Verification for claim ID {display_id} has been completed successfully.

    Your claim details have been recorded for processing.

    If additional documents are required, further communication may be shared regarding the claim process.

    Regards,
    ICS Assure Services Pvt Ltd."""
        
        success, msg_id = self.send_message(to_number, message)
        return success, msg_id, message  # ← RETURN 3
    
    # ============ SEND CUSTOM MESSAGE ============
    def send_custom_message(
        self,
        to_number: str,
        message: str
    ) -> Tuple[bool, str]:
        """Send a custom message"""
        return self.send_message(to_number, message)
    
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