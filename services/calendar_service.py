# services/calendar_service.py - FULL UPDATED VERSION with Calendar Name

import os
import pickle
import re
from datetime import datetime, time, date, timedelta, timezone
from typing import Tuple, Optional, List, Dict, Any
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# IST Timezone
IST = timezone(timedelta(hours=5, minutes=30))

class CalendarService:
    """Google Calendar Service - Uses your DEDICATED calendar"""
    
    def __init__(self):
        self.service = None
        self.calendar_name = "FARE AutoSpect - DI Health"  # ✅ ADDED
        self.calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "c_deb63eb357ea9d479747664c03531500f234ef7485bc09f24fe2581a3134c508@group.calendar.google.com")
        self.authenticate()
        print(f"📅 Using Calendar: {self.calendar_id}")
    
    def authenticate(self) -> bool:
        """Authenticate with Google Calendar using OAuth token"""
        try:
            creds = None
            token_file = "token_combined.pickle"
            
            if os.path.exists(token_file):
                with open(token_file, "rb") as f:
                    creds = pickle.load(f)
                    print(f"📁 Loaded token from {token_file}")
            
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(token_file, "wb") as f:
                    pickle.dump(creds, f)
                print("🔄 Google OAuth token refreshed")
            elif not creds or not creds.valid:
                print("❌ No valid token.")
                self.service = None
                return False
            
            self.service = build("calendar", "v3", credentials=creds)
            
            # ✅ FETCH CALENDAR NAME FROM GOOGLE
            try:
                calendar_metadata = self.service.calendarList().get(
                    calendarId=self.calendar_id
                ).execute()
                self.calendar_name = calendar_metadata.get('summary', self.calendar_name)
                print(f"📋 Calendar Name: {self.calendar_name}")
            except Exception as e:
                print(f"⚠️ Could not fetch calendar name: {e}")
            
            print(f"✅ Connected to Google Calendar: {self.calendar_id}")
            return True
            
        except Exception as exc:
            print(f"❌ Calendar authentication failed: {exc}")
            self.service = None
            return False
    
    # ✅ NEW: Get calendar name
    def get_calendar_name(self) -> str:
        """Get the calendar name"""
        return self.calendar_name
    
    async def get_busy_times(self, date_obj: date) -> List[Tuple[datetime, datetime, str, str, str]]:
        """Get busy times WITH event details from YOUR calendar"""
        if not self.service:
            return []
        
        start_of_day = datetime.combine(date_obj, datetime.min.time()).replace(tzinfo=IST)
        end_of_day = datetime.combine(date_obj, datetime.max.time()).replace(tzinfo=IST)
        
        try:
            events_result = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=start_of_day.isoformat(),
                timeMax=end_of_day.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            ).execute()
            
            busy_times = []
            for event in events_result.get("items", []):
                start = event["start"].get("dateTime")
                end = event["end"].get("dateTime")
                if start and end:
                    s = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(IST)
                    e = datetime.fromisoformat(end.replace("Z", "+00:00")).astimezone(IST)
                    
                    summary = event.get("summary", "Busy")
                    description = event.get("description", "")
                    meet_link = event.get("hangoutLink", "")
                    
                    case_id = None
                    if "Case ID:" in description:
                        for line in description.split("\n"):
                            if "Case ID:" in line:
                                case_id = line.replace("Case ID:", "").strip()
                                break
                    
                    busy_times.append((s, e, summary, case_id, meet_link))
            
            return busy_times
            
        except Exception as e:
            print(f"⚠️ Failed to get busy times: {e}")
            return []
    
    async def create_meeting_event(
        self,
        case_name: str,
        case_id: str,
        date: date,
        start_time: time,
        end_time: time,
        phone_number: str
    ) -> Tuple[str, str]:
        """Create event in YOUR NEW calendar with Google Meet"""
        if not self.service:
            print("❌ Calendar service not authenticated")
            return None, None
        
        start_dt = datetime.combine(date, start_time).replace(tzinfo=IST)
        end_dt = datetime.combine(date, end_time).replace(tzinfo=IST)
        
        event = {
            "summary": f"Consultation - {case_name}",
            "description": (
                f"Case ID: {case_id}\n"
                f"Patient: {case_name}\n"
                f"Phone: {phone_number}\n"
                f"Scheduled via FARE AutoSpect"
            ),
            "start": {
                "dateTime": start_dt.isoformat(),
                "timeZone": "Asia/Kolkata"
            },
            "end": {
                "dateTime": end_dt.isoformat(),
                "timeZone": "Asia/Kolkata"
            },
            "conferenceData": {
                "createRequest": {
                    "requestId": f"meet-{case_id}-{datetime.now(IST).strftime('%Y%m%d%H%M%S')}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
        }
        
        try:
            created = self.service.events().insert(
                calendarId=self.calendar_id,
                body=event,
                conferenceDataVersion=1,
            ).execute()
            
            meet_link = created.get("hangoutLink")
            if not meet_link:
                for entry in created.get("conferenceData", {}).get("entryPoints", []):
                    if entry.get("entryPointType") == "video":
                        meet_link = entry.get("uri")
            
            event_id = created.get("id")
            
            print(f"✅ Created event in YOUR NEW calendar: {event_id}")
            print(f"📹 Meet link: {meet_link}")
            
            return event_id, meet_link
            
        except Exception as e:
            print(f"❌ Failed to create calendar event: {e}")
            return None, None
    
    async def get_available_slots_with_metadata(
        self,
        date_obj: date,
        duration_minutes: int = 30
    ) -> List[Dict[str, Any]]:
        """Get available slots with metadata from YOUR calendar"""
        busy_events = await self.get_busy_times(date_obj)
        
        if date_obj.weekday() >= 5:
            return []
        
        working_start = datetime.combine(date_obj, time(9, 0)).replace(tzinfo=IST)
        working_end = datetime.combine(date_obj, time(18, 0)).replace(tzinfo=IST)
        
        slots = []
        current = working_start
        
        while current + timedelta(minutes=duration_minutes) <= working_end:
            slot_end = current + timedelta(minutes=duration_minutes)
            
            is_available = True
            booked_by = None
            case_id = None
            meet_link = None
            
            for busy_start, busy_end, summary, busy_case_id, busy_meet_link in busy_events:
                if not (slot_end <= busy_start or current >= busy_end):
                    is_available = False
                    booked_by = summary
                    case_id = busy_case_id
                    meet_link = busy_meet_link
                    break
            
            slots.append({
                "start": current.strftime("%H:%M"),
                "end": slot_end.strftime("%H:%M"),
                "is_available": is_available,
                "booked_by": booked_by if not is_available else None,
                "case_id": case_id if not is_available else None,
                "meet_link": meet_link if not is_available else None
            })
            
            current += timedelta(minutes=15)
        
        return slots