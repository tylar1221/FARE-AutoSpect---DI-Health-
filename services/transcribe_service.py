"""
Health Transcription Service
Processes only health files with (H- pattern)

Now mirrors the insurance pipeline's case-group logic:
  - Each case has a row in health_processing_groups with a status:
      pending -> merging -> transcribing -> completed / failed
  - A case is locked to 'processing' before work starts, so the same
    case is never picked up twice by an overlapping run.
  - retry_count caps automatic retries at 3.
  - A grace period (last_seen < NOW() - 5 min) lets more videos for the
    same case land before we start merging, instead of racing.
  - Multiple cases each move forward run-over-run instead of one case
    being reprocessed forever while others starve.
"""

import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import boto3
from google import genai
from google.genai import types

from app.database import get_db
from sqlalchemy import text

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

HEALTH_PATTERN = r"\(H-([A-Z]{2,}-\d{4,}-[A-Z0-9]+)\)"
INSURANCE_PATTERN = r"\(([A-Z]{2,}-\d{4,}-[A-Z0-9]+)\)"  # To skip

GRACE_PERIOD_MINUTES = 0.2      # let multi-part recordings finish landing before merging
MAX_RETRIES = 3


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


# ================================================================
# FILE PATTERN DETECTION
# ================================================================
def extract_health_case_id(filename: str) -> Optional[str]:
    m = re.search(HEALTH_PATTERN, filename)
    return f"H-{m.group(1)}" if m else None


def is_health_file(filename: str) -> bool:
    return bool(re.search(HEALTH_PATTERN, filename))


def is_insurance_file(filename: str) -> bool:
    return bool(re.search(INSURANCE_PATTERN, filename))


# ================================================================
# DB HELPERS — case_processing_groups equivalent for health
# ================================================================
async def _get_case_user_id(db, case_id: str):
    result = await db.execute(
        text("SELECT user_id FROM health_di_cases WHERE case_id = :case_id"),
        {"case_id": case_id}
    )
    row = result.first()
    return row[0] if row else None


async def create_health_processing_group(db, case_id: str):
    """Create the group row if it doesn't exist yet."""
    await db.execute(
        text("""
            INSERT INTO health_processing_groups (case_id, status, video_count, first_seen, last_seen)
            VALUES (:case_id, 'pending', 0, NOW(), NOW())
            ON CONFLICT (case_id) DO NOTHING
        """),
        {"case_id": case_id}
    )


async def bump_health_processing_group(db, case_id: str):
    """
    Called every time a new video lands for this case:
    - increments video_count
    - refreshes last_seen (resets the grace-period clock)
    - if the case was previously completed, resets it to pending so the
      new video gets picked up (reprocessing), instead of being ignored.
    """
    await db.execute(
        text("""
            UPDATE health_processing_groups
            SET video_count = video_count + 1,
                last_seen = NOW(),
                updated_at = NOW(),
                status = CASE WHEN status = 'completed' THEN 'pending' ELSE status END,
                retry_count = CASE WHEN status = 'completed' THEN 0 ELSE retry_count END,
                error_message = CASE WHEN status = 'completed' THEN NULL ELSE error_message END
            WHERE case_id = :case_id
        """),
        {"case_id": case_id}
    )


async def get_pending_health_groups(db, limit: int = 1):
    """
    Mirrors get_pending_case_groups() from the insurance pipeline:
    - only pending/failed groups
    - retry_count under the cap
    - past the grace period (so late-arriving videos for the same case
      have had a chance to land before we merge)
    """
    result = await db.execute(
        text(f"""
            SELECT
                hpg.case_id,
                hpg.status,
                hpg.retry_count,
                hpg.video_count,
                ARRAY_AGG(hcr.drive_file_id) as video_ids,
                ARRAY_AGG(hcr.file_name) as file_names
            FROM health_processing_groups hpg
            JOIN health_case_recordings hcr
                ON hcr.case_id = hpg.case_id
                AND hcr.processing_status = 'pending'
            WHERE hpg.status IN ('pending', 'failed')
            AND COALESCE(hpg.retry_count, 0) < {MAX_RETRIES}
            AND hpg.last_seen < NOW() - INTERVAL '{GRACE_PERIOD_MINUTES} minutes'
            GROUP BY hpg.case_id, hpg.status, hpg.retry_count, hpg.video_count, hpg.first_seen
            ORDER BY hpg.first_seen ASC
            LIMIT :limit
        """),
        {"limit": limit}
    )
    return result.all()


async def update_health_group_status(db, case_id: str, status: str):
    await db.execute(
        text("""
            UPDATE health_processing_groups
            SET status = :status, updated_at = NOW()
            WHERE case_id = :case_id
        """),
        {"case_id": case_id, "status": status}
    )
    logger.info(f"📊 Health case group {case_id} status → {status}")


async def update_health_group_completed(db, case_id: str):
    await db.execute(
        text("""
            UPDATE health_processing_groups
            SET status = 'completed', completed_at = NOW(), updated_at = NOW()
            WHERE case_id = :case_id
        """),
        {"case_id": case_id}
    )


async def update_health_group_failed(db, case_id: str, error_msg: str):
    await db.execute(
        text("""
            UPDATE health_processing_groups
            SET status = 'failed',
                retry_count = COALESCE(retry_count, 0) + 1,
                error_message = :err,
                updated_at = NOW()
            WHERE case_id = :case_id
        """),
        {"case_id": case_id, "err": error_msg[:500]}
    )


async def mark_health_videos_completed(db, case_id: str):
    await db.execute(
        text("""
            UPDATE health_case_recordings
            SET processing_status = 'completed'
            WHERE case_id = :case_id AND processing_status = 'pending'
        """),
        {"case_id": case_id}
    )


# ================================================================
# GOOGLE DRIVE SYNC (HEALTH ONLY) — now creates/bumps processing groups
# ================================================================
async def health_sync_drive_to_db(drive_service):
    logger.info("🏥 Health Drive sync starting... (HEALTH ONLY)")

    try:
        # Step 1: Find root folder — renamed from "Meet Recordings" to "Google Meet"
        results = drive_service.files().list(
            q="name='Google Meet' and mimeType='application/vnd.google-apps.folder' and trashed=false",
            fields="files(id, name)",
        ).execute()
        root_folders = results.get("files", [])
        if not root_folders:
            logger.error("❌ 'Google Meet' folder not found in Drive")
            return 0

        root_folder_id = root_folders[0]["id"]

        # Step 2: List all per-meeting subfolders inside "Google Meet"
        case_subfolders = []
        page_token = None
        while True:
            resp = drive_service.files().list(
                q=f"'{root_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
                fields="nextPageToken, files(id, name)",
                pageSize=100,
                pageToken=page_token,
            ).execute()
            case_subfolders.extend(resp.get("files", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        async for db in get_db():
            result = await db.execute(
                text("SELECT drive_file_id FROM health_case_recordings")
            )
            processed_ids = [row[0] for row in result.all() if row[0]]
            break

        new_count = 0
        skipped_insurance_count = 0

        # Step 3: Walk into each subfolder and pull the video(s) inside it
        for subfolder in case_subfolders:
            sub_page_token = None
            while True:
                resp = drive_service.files().list(
                    q=f"'{subfolder['id']}' in parents and trashed=false",
                    fields="nextPageToken, files(id, name, mimeType, size)",
                    pageSize=100,
                    pageToken=sub_page_token,
                ).execute()

                for item in resp.get("files", []):
                    if not item["mimeType"].startswith("video/"):
                        continue

                    if is_insurance_file(item["name"]):
                        skipped_insurance_count += 1
                        continue

                    if item["id"] in processed_ids:
                        continue

                    # Try filename first, fall back to subfolder name
                    case_id = extract_health_case_id(item["name"]) or extract_health_case_id(subfolder["name"])
                    if not case_id:
                        logger.warning(f"⚠️ Unknown pattern (not health): {item['name']} in '{subfolder['name']}'")
                        continue

                    logger.info(f"🏥 Health video found: {case_id} - {item['name']}")
                    file_url = f"https://drive.google.com/file/d/{item['id']}/view"

                    async for db in get_db():
                        result = await db.execute(
                            text("SELECT id FROM health_case_recordings WHERE file_url = :url"),
                            {"url": file_url}
                        )
                        if result.first():
                            break

                        owner_user_id = await _get_case_user_id(db, case_id)
                        if owner_user_id is None:
                            logger.warning(
                                f"⚠️ No matching case / user_id for {case_id} — skipping {item['name']}"
                            )
                            break

                        await db.execute(
                            text("""
                                INSERT INTO health_case_recordings
                                (case_id, file_name, file_url, drive_file_id, uploaded_at, user_id, processing_status)
                                VALUES (:case_id, :file_name, :file_url, :drive_file_id, NOW(), :user_id, 'pending')
                            """),
                            {
                                "case_id": case_id,
                                "file_name": item["name"],
                                "file_url": file_url,
                                "drive_file_id": item["id"],
                                "user_id": owner_user_id,
                            }
                        )

                        await create_health_processing_group(db, case_id)
                        await bump_health_processing_group(db, case_id)

                        await db.commit()
                        new_count += 1
                        logger.info(f"✅ Inserted health video + updated group: {case_id}")
                        break

                sub_page_token = resp.get("nextPageToken")
                if not sub_page_token:
                    break

        logger.info(
            f"✅ Health sync done — {new_count} new video(s) queued, "
            f"{skipped_insurance_count} insurance file(s) skipped, "
            f"{len(case_subfolders)} case folder(s) scanned"
        )
        return new_count

    except Exception as e:
        logger.error(f"❌ Health Drive sync error: {e}")
        return 0
# ================================================================
# AUDIO EXTRACTION FUNCTIONS
# ================================================================
def download_from_drive(drive_service, file_id: str, file_name: str) -> str:
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
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        audio_path = tmp.name

    logger.info(f"   🎵 Extracting audio from part {part_num}...")
    result = subprocess.run([
        "ffmpeg", "-i", video_path,
        "-vn", "-c:a", "libmp3lame", "-b:a", "96k",
        "-ar", "22050", "-ac", "1",
        "-y", audio_path
    ], capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[:200]}")

    logger.info(f"   ✅ Audio extracted: {os.path.getsize(audio_path) / (1024*1024):.1f} MB")
    return audio_path


def merge_audio_files(audio_paths: list, case_id: str) -> str:
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
            "ffmpeg", "-f", "concat", "-safe", "0",
            "-i", list_path, "-c", "copy", "-y", merged_path
        ], capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg merge failed: {result.stderr[:200]}")

        logger.info(f"   ✅ Merge complete: {os.path.getsize(merged_path) / (1024*1024):.1f} MB")
    finally:
        if os.path.exists(list_path):
            os.remove(list_path)

    return merged_path


# ================================================================
# TRANSCRIPTION — single Gemini call, transcript only, no JSON
# ================================================================
TRANSCRIPT_PROMPT = """
You are a medical/health claim transcriptionist.

Detect primary language (Hindi, Marathi, Gujarati, Tamil, Telugu, Kannada, Malayalam, Bengali, Odia, or English) and use correct script.
Transcribe verbatim with speaker labels (Investigator:/Patient:/Doctor:).
Mark unclear audio as [अस्पष्ट].

CRITICAL: Output ONLY the two blocks below, in exactly this order, with exactly these headers.
Do not add any preamble, explanation, or markdown formatting outside the blocks.

--- ORIGINAL TRANSCRIPT ---
[Full verbatim transcript in primary language with speaker labels]
--- ENGLISH TRANSLATION ---
[Complete English translation line by line]
"""


def _transcribe_health(s3, s3_audio_key: str) -> str:
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

    logger.info(f"   🤖 [Call 1/1] Transcribing health audio...")
    resp = client.models.generate_content(
        model=MODEL_NAME,
        contents=[
            types.Content(role="user", parts=[
                types.Part(inline_data=types.Blob(mime_type="audio/mp3", data=audio_bytes)),
                types.Part(text=TRANSCRIPT_PROMPT),
            ])
        ],
        config=types.GenerateContentConfig(temperature=0.0),
    )

    raw = resp.text or ""
    if not raw:
        raise RuntimeError("Gemini returned empty response")

    hindi_transcript = ""
    english_transcript = ""

    if "--- ORIGINAL TRANSCRIPT ---" in raw and "--- ENGLISH TRANSLATION ---" in raw:
        parts = raw.split("--- ENGLISH TRANSLATION ---")
        hindi_transcript = parts[0].replace("--- ORIGINAL TRANSCRIPT ---", "").strip()
        english_transcript = parts[1].strip()
    else:
        logger.warning("⚠️ Unexpected response format, using raw text as fallback")
        clean_text = raw
        for header in ["--- ORIGINAL TRANSCRIPT ---", "--- ENGLISH TRANSLATION ---"]:
            clean_text = clean_text.replace(header, "").strip()
        hindi_transcript = clean_text
        english_transcript = clean_text

    return f"--- ORIGINAL TRANSCRIPT ---\n{hindi_transcript}\n\n--- ENGLISH TRANSLATION ---\n{english_transcript}"


# ================================================================
# MAIN PROCESSING FUNCTION — mirrors process_case_group()
# ================================================================
async def process_health_case_group(drive_service, case_group) -> bool:
    """
    case_group is a Row from get_pending_health_groups():
      case_id, status, retry_count, video_count, video_ids, file_names
    """
    case_id = case_group.case_id
    video_ids = case_group.video_ids or []
    file_names = case_group.file_names or []
    video_count = len(video_ids)

    if not video_ids:
        logger.warning(f"⚠️ No video ids resolved for case {case_id} — skipping")
        return False

    logger.info(f"🏥 Processing health case: {case_id} ({video_count} recordings)")

    s3 = _get_s3()
    merged_audio_key = f"Health_Recordings/{case_id}/merged_audio/{case_id}_merged.mp3"

    try:
        # ── Step 1: Mark merging ──
        async for db in get_db():
            await update_health_group_status(db, case_id, "merging")
            await db.commit()
            break

        # ── Step 2: Download & Extract Audio ──
        logger.info(f"🎵 Processing {video_count} recordings...")
        audio_files = []

        for idx, (video_id, file_name) in enumerate(zip(video_ids, file_names), 1):
            logger.info(f"   ─── Recording {idx}/{video_count} ───")
            video_path = download_from_drive(drive_service, video_id, file_name)
            audio_path = extract_audio_to_temp(video_path, case_id, idx)
            audio_files.append(audio_path)
            if os.path.exists(video_path):
                os.remove(video_path)

        # ── Step 3: Merge Audio ──
        if len(audio_files) == 1:
            merged_audio_path = audio_files[0]
        else:
            merged_audio_path = merge_audio_files(audio_files, case_id)
            for audio_file in audio_files:
                if os.path.exists(audio_file) and audio_file != merged_audio_path:
                    os.remove(audio_file)

        # ── Step 4: Upload merged audio to S3 ──
        logger.info(f"   📤 Uploading merged audio to S3...")
        s3.upload_file(
            merged_audio_path, S3_BUCKET_NAME, merged_audio_key,
            ExtraArgs={"ContentType": "audio/mpeg"}
        )
        if os.path.exists(merged_audio_path):
            os.remove(merged_audio_path)

        # ── Step 5: Mark transcribing, then transcribe (1 Gemini call) ──
        async for db in get_db():
            await update_health_group_status(db, case_id, "transcribing")
            await db.commit()
            break

        logger.info(f"🎤 Transcribing health case {case_id}...")
        transcript = _transcribe_health(s3, merged_audio_key)

        # ── Step 6: Save transcript, mark group + videos completed ──
        async for db in get_db():
            await db.execute(
                text("""
                    UPDATE health_di_cases
                    SET transcript = :transcript, updated_at = NOW()
                    WHERE case_id = :case_id
                """),
                {"transcript": transcript, "case_id": case_id}
            )
            await update_health_group_completed(db, case_id)
            await mark_health_videos_completed(db, case_id)
            await db.commit()
            break

        # ── Step 7: Clean up merged audio (transient working file only) ──
        s3.delete_object(Bucket=S3_BUCKET_NAME, Key=merged_audio_key)
        logger.info(f"🧹 Cleaned up merged audio for health case {case_id}")

        logger.info(f"✅ Health case {case_id} processed successfully")
        return True

    except Exception as e:
        err = str(e)
        logger.error(f"❌ Failed processing health case {case_id}: {err}")
        async for db in get_db():
            await update_health_group_failed(db, case_id, err)
            await db.commit()
            break
        return False


# ================================================================
# ENTRY POINT (Called by scheduler) — mirrors run_transcribe_cycle()
# ================================================================
async def run_health_transcribe_cycle(drive_service):
    logger.info("🏥 Health transcription cycle starting...")

    # Step 1: Sync Drive → Health DB (also creates/bumps processing groups)
    try:
        await health_sync_drive_to_db(drive_service)
    except Exception as e:
        logger.error(f"❌ Health Drive sync error: {e}")
        return

    # Step 2: Get pending case groups, past the grace period, under retry cap
    async for db in get_db():
        groups = await get_pending_health_groups(db, limit=10)  # TESTING — was limit=1

        if not groups:
            logger.info("📭 No pending health case groups ready for processing")
            return

        # Lock ALL of them up front so a second overlapping run can't grab them
        for group in groups:
            await db.execute(
                text("""
                    UPDATE health_processing_groups
                    SET status = 'processing', processing_started_at = NOW()
                    WHERE case_id = :case_id AND status = 'pending'
                """),
                {"case_id": group.case_id}
            )
        await db.commit()
        break

    logger.info(f"🏥 Processing {len(groups)} health case group(s) this cycle...")

    # Step 3: Process each one, one at a time (sequential to avoid overloading S3/Gemini)
    for group in groups:
        await process_health_case_group(drive_service, group)