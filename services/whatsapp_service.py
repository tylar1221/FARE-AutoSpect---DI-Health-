# # services/whatsapp_service.py
# import httpx
# from datetime import datetime
# from typing import Optional
# from app.config import settings

# class WhatsAppService:
    
#     @staticmethod
#     async def send_message(to_number: str, message: str) -> bool:
#         """Send WhatsApp message"""
        
#         # Format phone number
#         if not to_number.startswith('91'):
#             to_number = f'91{to_number}'
        
#         headers = {
#             'Authorization': f'Bearer {settings.WHATSAPP_ACCESS_TOKEN}',
#             'Content-Type': 'application/json'
#         }
        
#         data = {
#             'messaging_product': 'whatsapp',
#             'to': to_number,
#             'type': 'text',
#             'text': {'body': message}
#         }
        
#         async with httpx.AsyncClient() as client:
#             response = await client.post(
#                 f'{settings.WHATSAPP_API_URL}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages',
#                 headers=headers,
#                 json=data
#             )
            
#             return response.status_code == 201
    
#     @staticmethod
#     async def send_meeting_confirmation(
#         phone_number: str,
#         case_name: str,
#         date: date,
#         time: time,
#         meet_link: str
#     ) -> bool:
#         """Send meeting confirmation message"""
        
#         message = f"""🏥 *Health Claim Verification Meeting Confirmed*

# Dear {case_name},

# Your health verification meeting has been scheduled:

# 📅 Date: {date.strftime('%A, %B %d, %Y')}
# 🕐 Time: {time.strftime('%I:%M %p')}
# 🔗 Join Link: {meet_link}

# Please join 5 minutes before the scheduled time.

# For any issues, contact us.

# - FARE AutoSpect Team"""
        
#         return await WhatsAppService.send_message(phone_number, message)
    
#     @staticmethod
#     async def send_reminder(
#         phone_number: str,
#         case_name: str,
#         scheduled_time: datetime,
#         meet_link: str
#     ) -> bool:
#         """Send meeting reminder"""
        
#         message = f"""⏰ *Meeting Reminder*

# Dear {case_name},

# This is a reminder for your health verification meeting.

# 📅 Today at {scheduled_time.strftime('%I:%M %p')}
# 🔗 Join: {meet_link}

# Please join on time.

# - FARE AutoSpect Team"""
        
#         return await WhatsAppService.send_message(phone_number, message)



# services/whatsapp_service.py
from typing import Optional
from datetime import datetime, date, time

class WhatsAppService:
    
    @staticmethod
    async def send_message(to_number: str, message: str) -> bool:
        """Mock send message"""
        print(f"\n📱 MOCK WhatsApp Message to: {to_number}")
        print("-" * 50)
        print(message)
        print("-" * 50)
        return True
    
    @staticmethod
    async def send_meeting_confirmation(
        phone_number: str,
        case_name: str,
        date: date,
        time: time,
        meet_link: str
    ) -> bool:
        message = f"""🏥 *Health Claim Verification Meeting Confirmed*

Dear {case_name},

Your health verification meeting has been scheduled:

📅 Date: {date.strftime('%A, %B %d, %Y')}
🕐 Time: {time.strftime('%I:%M %p')}
🔗 Join Link: {meet_link}

Please join 5 minutes before the scheduled time.

For any issues, contact us.

- FARE AutoSpect Team"""
        return await WhatsAppService.send_message(phone_number, message)
    
    @staticmethod
    async def send_reminder(
        phone_number: str,
        case_name: str,
        scheduled_time: datetime,
        meet_link: str
    ) -> bool:
        message = f"""⏰ *Meeting Reminder*

Dear {case_name},

This is a reminder for your health verification meeting.

📅 Today at {scheduled_time.strftime('%I:%M %p')}
🔗 Join: {meet_link}

Please join on time.

- FARE AutoSpect Team"""
        return await WhatsAppService.send_message(phone_number, message)
    
    @staticmethod
    async def send_completion_message(
        phone_number: str,
        case_name: str,
        case_id: str
    ) -> bool:
        message = f"""✅ *Verification Complete*

Dear {case_name},

Your health claim verification for case {case_id} has been completed.

The report has been generated and will be shared with the insurance company.

Thank you for your cooperation.

- FARE AutoSpect Team"""
        return await WhatsAppService.send_message(phone_number, message)