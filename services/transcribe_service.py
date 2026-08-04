"""
Health Transcription Service
Processes only health files with (H- pattern)
"""

import os
import re
import io
import subprocess
import tempfile
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
import sys
import boto3
from google import genai
from google.genai import types

from app.config import settings
from app.database import get_db
from app.models import DICase, CaseDocument
from sqlalchemy import select, text

import logging
logger = logging.getLogger(__name__)


# ================================================================
# CONFIG
# ================================================================
S3_BUCKET_NAME = os.environ.get("AWS_BUCKET_NAME", "")
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")
GCP_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "ics-transcribe-project")
GCP_LOCATION = os.environ.get("GCP_LOCATION", "asia-south1")
MODEL_NAME = "gemini-2.5-flash"

# Health file pattern: (H-ICS-260425-DB660)
HEALTH_PATTERN = r"\(H-([A-Z]{2,}-\d{4,}-[A-Z0-9]+)\)"
INSURANCE_PATTERN = r"\(([A-Z]{2,}-\d{4,}-[A-Z0-9]+)\)"  # To skip


# ================================================================
# S3 HELPERS
# ================================================================
def _get_s3():
    return boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )


def _s3_key_exists(s3, key: str) -> bool:
    try:
        s3.head_object(Bucket=S3_BUCKET_NAME, Key=key)
        return True
    except Exception:
        return False


# ================================================================
# FILE PATTERN DETECTION
# ================================================================
def extract_health_case_id(filename: str) -> Optional[str]:
    """Extract case ID from health filename: (H-ICS-260425-DB660)"""
    m = re.search(HEALTH_PATTERN, filename)
    return f"H-{m.group(1)}" if m else None


def is_health_file(filename: str) -> bool:
    """Check if filename matches health pattern"""
    return bool(re.search(HEALTH_PATTERN, filename))


def is_insurance_file(filename: str) -> bool:
    """Check if filename matches insurance pattern (to skip)"""
    return bool(re.search(INSURANCE_PATTERN, filename))


# ================================================================
# GOOGLE DRIVE SYNC (HEALTH ONLY)
# ================================================================
async def health_sync_drive_to_db(drive_service):
    """
    Health-only sync: Process files with (H- pattern), skip insurance files
    """
    logger.info("🏥 Health Drive sync starting... (HEALTH ONLY)")
    
    # Find Meet Recordings folder
    try:
        results = drive_service.files().list(
            q="name='Meet Recordings' and mimeType='application/vnd.google-apps.folder' and trashed=false",
            fields="files(id, name)",
        ).execute()
        folders = results.get("files", [])
        if not folders:
            logger.error("❌ 'Meet Recordings' folder not found in Drive")
            return 0
        
        folder_id = folders[0]["id"]
        
        # Get already processed files from health DB
        async for db in get_db():
            # Get existing health videos
            result = await db.execute(
                text("SELECT file_url FROM health_case_documents WHERE source = 'meeting_recording'")
            )
            processed = [row[0] for row in result.all()]
            processed_ids = []
            for url in processed:
                # Extract drive file ID from URL
                if "file/d/" in url:
                    file_id = url.split("file/d/")[1].split("/")[0]
                    processed_ids.append(file_id)
            
            break
        
        page_token = None
        new_count = 0
        skipped_insurance_count = 0
        
        while True:
            resp = drive_service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="nextPageToken, files(id, name, mimeType, size)",
                pageSize=100,
                pageToken=page_token,
            ).execute()
            
            for item in resp.get("files", []):
                if not item["mimeType"].startswith("video/"):
                    continue
                
                # ════════════════════════════════════════════════════
                # 🔥 SKIP INSURANCE FILES (ICS- pattern)
                # ════════════════════════════════════════════════════
                if is_insurance_file(item["name"]):
                    logger.info(f"⏭️ Skipping insurance file: {item['name']}")
                    skipped_insurance_count += 1
                    continue
                
                # Skip already processed
                if item["id"] in processed_ids:
                    continue
                
                # Check if health file
                if not is_health_file(item["name"]):
                    logger.warning(f"⚠️ Unknown pattern (not health): {item['name']}")
                    continue
                
                case_id = extract_health_case_id(item["name"])
                if not case_id:
                    logger.warning(f"⚠️ Could not extract health case ID: {item['name']}")
                    continue
                
                logger.info(f"🏥 Health video found: {case_id} - {item['name']}")
                
                # Insert into health database
                file_url = f"https://drive.google.com/file/d/{item['id']}/view"
                
                async for db in get_db():
                    # Check if document already exists
                    result = await db.execute(
                        text("SELECT id FROM health_case_documents WHERE file_url = :url"),
                        {"url": file_url}
                    )
                    existing = result.first()
                    
                    if not existing:
                        # Insert new document
                        await db.execute(
                            text("""
                                INSERT INTO health_case_documents 
                                (case_id, file_name, file_url, file_type, source, uploaded_at)
                                VALUES (:case_id, :file_name, :file_url, 'video', 'meeting_recording', NOW())
                            """),
                            {
                                "case_id": case_id,
                                "file_name": item["name"],
                                "file_url": file_url
                            }
                        )
                        await db.commit()
                        new_count += 1
                        logger.info(f"✅ Inserted health video: {case_id}")
                    break
            
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        
        logger.info(f"✅ Health sync done — {new_count} new health video(s) queued, {skipped_insurance_count} insurance file(s) skipped")
        return new_count
        
    except Exception as e:
        logger.error(f"❌ Health Drive sync error: {e}")
        return 0


# ================================================================
# AUDIO EXTRACTION FUNCTIONS
# ================================================================
def download_from_drive(drive_service, file_id: str, file_name: str) -> str:
    """Download file from Google Drive to temp location"""
    from googleapiclient.http import MediaIoBaseDownload
    
    ext = os.path.splitext(file_name)[1] or ".webm"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        path = tmp.name
    
    logger.info(f"   📥 Downloading: {file_name[:50]}...")
    request = drive_service.files().get_media(fileId=file_id)
    downloader = MediaIoBaseDownload(open(path, 'wb'), request)
    
    done = False
    while not done:
        status, done = downloader.next_chunk()
        if status:
            logger.info(f"   ⬇️  Download progress: {int(status.progress() * 100)}%")
    
    logger.info(f"   ✅ Downloaded: {os.path.getsize(path) / (1024*1024):.1f} MB")
    return path


def extract_audio_to_temp(video_path: str, case_id: str, part_num: int) -> str:
    """Extract audio from video to MP3"""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        audio_path = tmp.name
    
    logger.info(f"   🎵 Extracting audio from part {part_num}...")
    
    result = subprocess.run([
        "ffmpeg", "-i", video_path,
        "-vn",
        "-c:a", "libmp3lame",
        "-b:a", "96k",
        "-ar", "22050",
        "-ac", "1",
        "-y", audio_path
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[:200]}")
    
    logger.info(f"   ✅ Audio extracted: {os.path.getsize(audio_path) / (1024*1024):.1f} MB")
    return audio_path


def merge_audio_files(audio_paths: list, case_id: str) -> str:
    """Merge multiple MP3 files into one"""
    if len(audio_paths) == 1:
        return audio_paths[0]
    
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        merged_path = tmp.name
    
    list_path = f"/tmp/{case_id}_filelist.txt"
    with open(list_path, "w") as f:
        for audio_path in audio_paths:
            f.write(f"file '{os.path.abspath(audio_path)}'\n")
    
    try:
        logger.info(f"   🔗 Merging {len(audio_paths)} audio files...")
        result = subprocess.run([
            "ffmpeg",
            "-f", "concat",
            "-safe", "0",
            "-i", list_path,
            "-c", "copy",
            "-y", merged_path
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg merge failed: {result.stderr[:200]}")
        
        logger.info(f"   ✅ Merge complete: {os.path.getsize(merged_path) / (1024*1024):.1f} MB")
    finally:
        if os.path.exists(list_path):
            os.remove(list_path)
    
    return merged_path


# ================================================================
# TRANSCRIPTION FUNCTIONS
# ================================================================
TRANSCRIPT_PROMPT = """
You are a medical/health claim transcriptionist.

CRITICAL: Detect primary language (Hindi, Marathi, Gujarati, Tamil, Telugu, Kannada, Malayalam, Bengali, Odia, or English) and use correct script.

Transcribe verbatim with speaker labels (Investigator:/Patient:/Doctor:).
Mark unclear audio as [अस्पष्ट].

OUTPUT FORMAT:
--- ORIGINAL TRANSCRIPT ---
[Full verbatim transcript in primary language with speaker labels]
--- ENGLISH TRANSLATION ---
[Complete English translation line by line]
"""

HEALTH_JSON_PROMPT = """
You are a medical health claim investigator. Extract data to ENGLISH JSON.

TRANSCRIPT (FULL ENGLISH):
{english_transcript}

OUTPUT JSON:
{{
  "patient_details": {{
    "name": "full name",
    "age": "age",
    "gender": "Male/Female/Other",
    "contact": "phone number",
    "address": "address"
  }},
  "medical_condition": {{
    "diagnosis": "condition",
    "symptoms": ["symptom1", "symptom2"],
    "severity": "mild/moderate/severe",
    "onset_date": "date"
  }},
  "treatment_history": {{
    "consulted_doctor": "Yes/No",
    "doctor_name": "name",
    "hospital_name": "name",
    "treatment_given": "description",
    "medications": ["med1", "med2"],
    "follow_up_required": "Yes/No"
  }},
  "claim_details": {{
    "claim_amount": "amount",
    "policy_number": "number",
    "insurance_company": "company",
    "admission_date": "date",
    "discharge_date": "date"
  }}
}}
"""


def _transcribe_health(s3, s3_audio_key: str) -> Tuple[str, str]:
    """
    Transcribe health audio using Gemini
    Returns: (full_transcript, json_summary)
    """
    import json as json_lib
    
    # Download audio
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        audio_path = tmp.name
    
    try:
        logger.info("   📥 Downloading MP3 from S3 for transcription...")
        s3.download_file(S3_BUCKET_NAME, s3_audio_key, audio_path)
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()
        logger.info(f"   ✅ Audio loaded: {len(audio_bytes) / (1024*1024):.1f} MB")
    finally:
        if os.path.exists(audio_path):
            os.remove(audio_path)
    
    client = genai.Client(
        vertexai=True,
        project=GCP_PROJECT_ID,
        location=GCP_LOCATION,
        http_options=types.HttpOptions(api_version="v1"),
    )
    
    # ── Call 1: Transcribe ──
    logger.info(f"   🤖 [Call 1/2] Transcribing health audio...")
    resp1 = client.models.generate_content(
        model=MODEL_NAME,
        contents=[
            types.Content(role="user", parts=[
                types.Part(inline_data=types.Blob(mime_type="audio/mp3", data=audio_bytes)),
                types.Part(text=TRANSCRIPT_PROMPT),
            ])
        ],
        config=types.GenerateContentConfig(temperature=0.0),
    )
    
    transcript_raw = resp1.text or ""
    if not transcript_raw:
        raise RuntimeError("Gemini returned empty transcript")
    
    # Parse transcript
    hindi_transcript = ""
    english_transcript = ""
    
    if "--- ORIGINAL TRANSCRIPT ---" in transcript_raw and "--- ENGLISH TRANSLATION ---" in transcript_raw:
        parts = transcript_raw.split("--- ENGLISH TRANSLATION ---")
        hindi_transcript = parts[0].replace("--- ORIGINAL TRANSCRIPT ---", "").strip()
        english_transcript = parts[1].strip()
        if "---" in english_transcript:
            english_transcript = english_transcript.split("---")[0].strip()
    else:
        # Fallback
        clean_text = transcript_raw
        for header in ["--- ORIGINAL TRANSCRIPT ---", "--- ENGLISH TRANSLATION ---"]:
            clean_text = clean_text.replace(header, "").strip()
        hindi_transcript = clean_text
        english_transcript = clean_text
    
    # ── Call 2: JSON Extraction ──
    logger.info(f"   🤖 [Call 2/2] Converting to health JSON...")
    health_prompt = HEALTH_JSON_PROMPT.format(english_transcript=english_transcript)
    
    resp2 = client.models.generate_content(
        model=MODEL_NAME,
        contents=health_prompt,
        config=types.GenerateContentConfig(temperature=0.0),
    )
    
    json_raw = resp2.text or "{}"
    
    # Clean JSON
    cleaned = json_raw.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    
    # Extract JSON
    json_match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if json_match:
        cleaned = json_match.group(0)
    
    # Validate JSON
    try:
        data = json_lib.loads(cleaned)
        final_json = json_lib.dumps(data, ensure_ascii=False, indent=2)
    except json_lib.JSONDecodeError:
        logger.warning("⚠️ JSON parse failed, using fallback")
        fallback = {
            "patient_details": {},
            "medical_condition": {},
            "treatment_history": {},
            "claim_details": {}
        }
        final_json = json_lib.dumps(fallback, ensure_ascii=False, indent=2)
    
    full_transcript = f"--- ORIGINAL TRANSCRIPT ---\n{hindi_transcript}\n\n--- ENGLISH TRANSLATION ---\n{english_transcript}"
    
    return full_transcript, final_json


# ================================================================
# MAIN PROCESSING FUNCTION
# ================================================================
async def process_health_case_group(drive_service, case_group: dict):
    """
    Process a health case group (all videos for one case)
    """
    case_id = case_group["case_id"]
    video_ids = case_group["video_ids"]
    file_names = case_group["file_names"]
    video_count = len(video_ids)
    
    logger.info(f"🏥 Processing health case: {case_id} ({video_count} recordings)")
    
    s3 = _get_s3()
    merged_audio_key = f"Health_Recordings/{case_id}/merged_audio/{case_id}_merged.mp3"
    
    try:
        # ── Step 1: Download & Extract Audio ──
        logger.info(f"🎵 Processing {video_count} recordings...")
        audio_files = []
        
        for idx, (video_id, file_name) in enumerate(zip(video_ids, file_names), 1):
            logger.info(f"   ─── Recording {idx}/{video_count} ───")
            
            video_path = download_from_drive(drive_service, video_id, file_name)
            audio_path = extract_audio_to_temp(video_path, case_id, idx)
            audio_files.append(audio_path)
            
            if os.path.exists(video_path):
                os.remove(video_path)
        
        # ── Step 2: Merge Audio ──
        if len(audio_files) == 1:
            merged_audio_path = audio_files[0]
        else:
            merged_audio_path = merge_audio_files(audio_files, case_id)
            for audio_file in audio_files:
                if os.path.exists(audio_file) and audio_file != merged_audio_path:
                    os.remove(audio_file)
        
        # ── Step 3: Upload to S3 ──
        logger.info(f"   📤 Uploading merged audio to S3...")
        s3.upload_file(
            merged_audio_path,
            S3_BUCKET_NAME,
            merged_audio_key,
            ExtraArgs={"ContentType": "audio/mpeg"}
        )
        
        if os.path.exists(merged_audio_path):
            os.remove(merged_audio_path)
        
        # ── Step 4: Transcribe ──
        logger.info(f"🎤 Transcribing health case {case_id}...")
        transcript, summary_json = _transcribe_health(s3, merged_audio_key)
        
        # ── Step 5: Save to Database ──
        async for db in get_db():
            # Update case with transcript
            await db.execute(
                text("""
                    UPDATE health_di_cases 
                    SET transcript = :transcript,
                        updated_at = NOW()
                    WHERE case_id = :case_id
                """),
                {"transcript": transcript, "case_id": case_id}
            )
            await db.commit()
            break
        
        # ── Step 6: Clean up S3 ──
        s3.delete_object(Bucket=S3_BUCKET_NAME, Key=merged_audio_key)
        logger.info(f"🧹 Cleaned up merged audio for health case {case_id}")
        
        # ── Step 7: Save to S3 Report ──
        s3_report_key = f"Health_Recordings/{case_id}/reports/{case_id}_health_report.txt"
        report = f"=== HEALTH CASE REPORT ===\n"
        report += f"Case ID: {case_id}\n"
        report += f"Recordings: {video_count}\n"
        report += f"\n{transcript}\n\n"
        report += f"=== HEALTH SUMMARY ===\n"
        report += summary_json
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(report)
            report_path = f.name
        
        try:
            s3.upload_file(
                report_path,
                S3_BUCKET_NAME,
                s3_report_key,
                ExtraArgs={"ContentType": "text/plain"}
            )
        finally:
            if os.path.exists(report_path):
                os.remove(report_path)
        
        logger.info(f"✅ Health case {case_id} processed successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed processing health case {case_id}: {e}")
        return False


# ================================================================
# ENTRY POINT (Called by scheduler)
# ================================================================
async def run_health_transcribe_cycle(drive_service):
    """
    Main entry point - called by health scheduler
    """
    logger.info("🏥 Health transcription cycle starting...")
    
    # Step 1: Sync Drive → Health DB
    try:
        new_count = await health_sync_drive_to_db(drive_service)
        if new_count == 0:
            logger.info("📭 No new health files found")
            return
    except Exception as e:
        logger.error(f"❌ Health Drive sync error: {e}")
        return
    
    # Step 2: Get pending health videos (grouped by case)
    async for db in get_db():
        result = await db.execute(
            text("""
                SELECT 
                    case_id,
                    ARRAY_AGG(file_url) as file_urls,
                    ARRAY_AGG(file_name) as file_names
                FROM health_case_documents 
                WHERE source = 'meeting_recording'
                AND file_type = 'video'
                ORDER BY uploaded_at ASC
                GROUP BY case_id
                LIMIT 1
            """)
        )
        rows = result.all()
        
        for row in rows:
            case_id = row[0]
            file_urls = row[1] or []
            file_names = row[2] or []
            
            if not file_urls:
                continue
            
            # Extract drive file IDs from URLs
            video_ids = []
            for url in file_urls:
                if "file/d/" in url:
                    file_id = url.split("file/d/")[1].split("/")[0]
                    video_ids.append(file_id)
            
            if video_ids:
                case_group = {
                    "case_id": case_id,
                    "video_ids": video_ids,
                    "file_names": file_names
                }
                await process_health_case_group(drive_service, case_group)
        break