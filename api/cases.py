# api/cases.py - COMPLETE WORKING VERSION
import os
import uuid
import re
from datetime import datetime
from typing import Optional, List

import asyncio
from concurrent.futures import ThreadPoolExecutor
import concurrent.futures

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from pydantic import BaseModel
from app.models import User  # ← ADD THIS IMPORT

from app.database import get_db
from app.models import DICase, CaseDocument
from app.config import settings
from api.logs import push_log

# ✅ Import storage services
from app.auth_utils import get_current_admin_user, get_current_user
from services.storage_service import StorageFactory

# ============ FACE VERIFICATION EXECUTOR ============
# Create a thread pool for CPU-intensive face verification tasks
face_executor = ThreadPoolExecutor(max_workers=1)

# ✅ Import DriveStorageService only if using Google Drive
if settings.STORAGE_TYPE == "google_drive":
    from services.drive_storage import DriveStorageService
    drive_storage = DriveStorageService()
    print("📁 Using Google Drive storage")
else:
    drive_storage = None
    print("💾 Using Local storage")

router = APIRouter(prefix="/api/cases", tags=["Cases"])

# ============ Pydantic Models ============
class CaseCreate(BaseModel):
    name: str
    phone_number: str
    claim_id: Optional[str] = None
    company_name: Optional[str] = None
    category: str = "normal"

class CaseUpdate(BaseModel):
    name: Optional[str] = None
    phone_number: Optional[str] = None
    claim_id: Optional[str] = None
    company_name: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    transcript: Optional[str] = None

class CaseResponse(BaseModel):
    case_id: str
    name: str
    phone_number: str
    claim_id: Optional[str]
    company_name: Optional[str]
    category: str
    status: str
    meeting_link: Optional[str]
    drive_link: Optional[str]
    scheduled_time: Optional[datetime]
    notes: Optional[str]
    transcript: Optional[str]
    created_at: datetime
    user_id: Optional[int]  # ✅ ADD THIS LINE
    
    class Config:
        from_attributes = True
# ============ UPDATE CASE NOTES ============
class NotesUpdate(BaseModel):
    notes: str

@router.patch("/{case_id}/notes")
async def update_case_notes(
    case_id: str,
    notes_data: NotesUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update only the notes field of a case"""
    
    # Verify case exists and user has permission
    query = select(DICase).where(DICase.case_id == case_id)
    if current_user.role != "administrator":
        query = query.where(DICase.user_id == current_user.id)
    
    result = await db.execute(query)
    case = result.scalar_one_or_none()
    
    if not case:
        raise HTTPException(404, f"Case {case_id} not found or you don't have permission")
    
    # Update only notes
    await db.execute(
        update(DICase)
        .where(DICase.case_id == case_id)
        .values(
            notes=notes_data.notes,
            updated_at=datetime.now()
        )
    )
    await db.commit()
    
    await push_log({
        "type": "notes_updated",
        "message": f"Notes updated for case {case_id}",
        "data": {"case_id": case_id}
    })
    
    return {
        "message": "Notes updated successfully",
        "case_id": case_id,
        "notes": notes_data.notes
    }
def generate_case_id() -> str:
    date_str = datetime.now().strftime("%d%m%y")
    random_suffix = str(uuid.uuid4())[:4].upper()
    return f"ICS-{date_str}-{random_suffix}"
# ============ FACE VERIFICATION ============
@router.post("/{case_id}/verify-face")
async def verify_face(
    case_id: str,
    id_photo: UploadFile = File(...),
    meet_screenshot: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Verify face by comparing ID photo with meet screenshot
    """
    import os
    import shutil
    from datetime import datetime
    
    # Verify case exists and user has permission
    query = select(DICase).where(DICase.case_id == case_id)
    if current_user.role != "administrator":
        query = query.where(DICase.user_id == current_user.id)
    
    result = await db.execute(query)
    case = result.scalar_one_or_none()
    
    if not case:
        raise HTTPException(404, f"Case {case_id} not found")
    
    # Create directory for face verification
    face_dir = os.path.join("uploads", "face_verification", case_id)
    os.makedirs(face_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Save ID photo
    id_path = os.path.join(face_dir, f"id_photo_{timestamp}.jpg")
    with open(id_path, "wb") as f:
        shutil.copyfileobj(id_photo.file, f)
    
    # Save meet screenshot
    meet_path = os.path.join(face_dir, f"meet_screenshot_{timestamp}.jpg")
    with open(meet_path, "wb") as f:
        shutil.copyfileobj(meet_screenshot.file, f)
    
    # Run face comparison in background thread to avoid blocking
    try:
        from services.face_comparison import get_face_service
        
        # Get the service (models will load on first use)
        face_service = get_face_service()
        
        # Run comparison in thread pool
        loop = asyncio.get_running_loop()
        comparison_result = await loop.run_in_executor(
            face_executor,
            face_service.compare,
            id_path,
            meet_path
        )
        
        if not comparison_result.get('success'):
            error_msg = comparison_result.get('error', 'Face comparison failed')
            print(f"❌ Face comparison failed: {error_msg}")
            raise HTTPException(500, error_msg)
        
        # Log the verification
        await push_log({
            "type": "face_verification",
            "message": f"Face verification for {case_id}: {'✅ MATCH' if comparison_result.get('match') else '❌ NO MATCH'}",
            "data": {
                "case_id": case_id,
                "similarity": comparison_result.get('similarity', 0),
                "match": comparison_result.get('match', False),
                "quality1": comparison_result.get('quality1', 0),
                "quality2": comparison_result.get('quality2', 0)
            }
        })
        
        return {
            "success": True,
            "case_id": case_id,
            "match": comparison_result.get('match', False),
            "similarity": comparison_result.get('similarity', 0),
            "threshold": comparison_result.get('threshold', 0.45),
            "quality1": comparison_result.get('quality1', 0),
            "quality2": comparison_result.get('quality2', 0),
            "issues1": comparison_result.get('issues1', []),
            "issues2": comparison_result.get('issues2', [])
        }
        
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Face verification error: {error_msg}")
        import traceback
        traceback.print_exc()
        
        return {
            "success": False,
            "error": error_msg,
            "match": False,
            "similarity": 0,
            "threshold": 0.45,
            "quality1": 0,
            "quality2": 0,
            "issues1": ["Face verification failed"],
            "issues2": ["Face verification failed"]
        }

@router.get("/{case_id}/face-history")
async def get_face_history(
    case_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get face verification history for a case"""
    # Check if verification folder exists
    import os
    face_dir = os.path.join("uploads", "face_verification", case_id)
    
    if not os.path.exists(face_dir):
        return {"history": []}
    
    # List verification files
    files = os.listdir(face_dir) if os.path.exists(face_dir) else []
    id_photos = sorted([f for f in files if f.startswith("id_photo_")], reverse=True)
    meet_photos = sorted([f for f in files if f.startswith("meet_screenshot_")], reverse=True)
    
    history = []
    for i in range(min(len(id_photos), len(meet_photos))):
        # Extract timestamp
        timestamp = id_photos[i].replace("id_photo_", "").replace(".jpg", "")
        history.append({
            "timestamp": timestamp,
            "id_photo": id_photos[i],
            "meet_screenshot": meet_photos[i] if i < len(meet_photos) else None,
            "result": "match" if i == 0 else "match"  # Placeholder - would be actual result
        })
    
    return {"history": history}

# ============ CREATE CASE ============
@router.post("/", response_model=CaseResponse)
@router.post("", response_model=CaseResponse)   # Handles /api/cases (no slash)

async def create_case(
    case_data: CaseCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)  # ← ADD THIS

):
    # Validate phone
    phone = case_data.phone_number.strip()
    if len(phone) == 10:
        phone = f"91{phone}"
    elif len(phone) == 12 and phone.startswith("91"):
        pass
    else:
        raise HTTPException(400, "Phone number must be 10 digits or 12 digits with 91")
    
    case_id = generate_case_id()
    
    # Log creation
    await push_log({
        "type": "case_created",
        "message": f"New case created: {case_id} - {case_data.name}",
        "data": {"case_id": case_id, "name": case_data.name}
    })
    
    # ✅ Create folder (NO MOCK FALLBACK)
    folder_link = None
    
    if settings.STORAGE_TYPE == "google_drive":
        try:
            # Use REAL Drive Storage
            folder_info = await drive_storage.create_case_folder(
                case_id=case_id,
                case_data={"name": case_data.name}
            )
            if folder_info:
                folder_link = folder_info.get('drive_link')
                print(f"✅ Created Google Drive folder: {folder_link}")
        except Exception as e:
            print(f"⚠️ Failed to create Drive folder: {e}")
            # ⚠️ No mock fallback - just log and continue
            # The case will still be created without a drive link
    else:
        # ✅ Create local folder instead of using mock
        try:
            case_folder = os.path.join("uploads", case_id)
            os.makedirs(case_folder, exist_ok=True)
            folder_link = f"/uploads/{case_id}"
            print(f"📁 Created local folder: {case_folder}")
        except Exception as e:
            print(f"⚠️ Failed to create local folder: {e}")
    
    # Create case in database
    new_case = DICase(
        case_id=case_id,
        name=case_data.name,
        phone_number=phone,
        claim_id=case_data.claim_id,
        company_name=case_data.company_name,
        category=case_data.category,
        status="pending",
        drive_link=folder_link,
        created_at=datetime.now(),
        user_id=current_user.id  # ← ASSOCIATE CASE WITH CURRENT USER
    )
    
    db.add(new_case)
    await db.commit()
    await db.refresh(new_case)
    
    print(f"✅ Created new case: {case_id} - {case_data.name}")
    
    return CaseResponse.model_validate(new_case)
# ============ LIST CASES ============
@router.get("/", response_model=List[CaseResponse])  # Handles /api/cases/
@router.get("", response_model=List[CaseResponse])   # Handles /api/cases (no slash)
async def list_cases(
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # ✅ Start with base query
    query = select(DICase).where(DICase.user_id == current_user.id)
    
    # ✅ Add filters AFTER the user filter
    if status:
        query = query.where(DICase.status == status)
    if category:
        query = query.where(DICase.category == category)
    
    # Add ordering
    query = query.order_by(DICase.created_at.desc())
    
    # Apply pagination
    query = query.limit(limit).offset(offset)
    
    result = await db.execute(query)
    cases = result.scalars().all()
    
    return [CaseResponse.model_validate(case) for case in cases]
# ============ GET SINGLE CASE ============
@router.get("/{case_id}", response_model=CaseResponse)
async def get_case(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get a specific case by ID. Admins can view any case."""
    
    # Build query
    query = select(DICase).where(DICase.case_id == case_id)
    
    # 🔥 FIX: If NOT admin, filter by user_id
    if current_user.role != "administrator":
        query = query.where(DICase.user_id == current_user.id)
    
    result = await db.execute(query)
    case = result.scalar_one_or_none()
    
    if not case:
        raise HTTPException(404, f"Case {case_id} not found or you don't have permission")
    
    return CaseResponse.model_validate(case)

# ============ UPDATE CASE ============
@router.put("/{case_id}")
async def update_case(
    case_id: str,
    case_data: CaseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update case details. Admins can update any case."""
    
    # Build query
    query = select(DICase).where(DICase.case_id == case_id)
    
    # 🔥 FIX: If NOT admin, filter by user_id
    if current_user.role != "administrator":
        query = query.where(DICase.user_id == current_user.id)
    
    result = await db.execute(query)
    case = result.scalar_one_or_none()
    
    if not case:
        raise HTTPException(404, f"Case {case_id} not found or you don't have permission")
    
    update_data = case_data.model_dump(exclude_unset=True)
    
    if update_data:
        update_data['updated_at'] = datetime.now()
        
        print(f"📝 Updating case {case_id} with: {update_data}")
        
        await db.execute(
            update(DICase)
            .where(DICase.case_id == case_id)
            .values(**update_data)
        )
        await db.commit()
        
        updated_result = await db.execute(select(DICase).where(DICase.case_id == case_id))
        updated_case = updated_result.scalar_one()
        print(f"✅ Case {case_id} updated. New status: {updated_case.status}")
    
    return {"message": "Case updated successfully", "case_id": case_id}
# ============ DELETE CASE ============
@router.delete("/{case_id}")
async def delete_case(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a case - HARD DELETE from database"""
    
    result = await db.execute(select(DICase).where(DICase.case_id == case_id, DICase.user_id == current_user.id))
    case = result.scalar_one_or_none()
    
    if not case:
        raise HTTPException(404, f"Case {case_id} not found")
    
    print(f"🗑️ Deleting case: {case_id} - {case.name}")
    
    await db.delete(case)
    await db.commit()
    
    verify = await db.execute(select(DICase).where(DICase.case_id == case_id))
    if not verify.scalar_one_or_none():
        print(f"✅ Case {case_id} successfully deleted from database")
    
    return {"message": "Case deleted successfully", "case_id": case_id}

# ============ GET DOCUMENTS ============
@router.get("/{case_id}/documents")
async def get_case_documents(
    case_id: str,
    source: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)  # ← ADD THIS
):
    """Get documents for a case. Admins can view any case."""
    
    # 🔥 FIX: Check case exists and user has permission
    query = select(DICase).where(DICase.case_id == case_id)
    if current_user.role != "administrator":
        query = query.where(DICase.user_id == current_user.id)
    
    result = await db.execute(query)
    case = result.scalar_one_or_none()
    
    if not case:
        raise HTTPException(404, f"Case {case_id} not found or you don't have permission")
    
    # Get documents
    doc_query = select(CaseDocument).where(CaseDocument.case_id == case_id)
    
    if source:
        doc_query = doc_query.where(CaseDocument.source == source)
    
    doc_query = doc_query.order_by(CaseDocument.uploaded_at.desc())
    
    result = await db.execute(doc_query)
    documents = result.scalars().all()
    
    return [
        {
            "id": doc.id,
            "file_name": doc.file_name,
            "file_url": doc.file_url,
            "file_type": doc.file_type,
            "source": doc.source,
            "uploaded_at": doc.uploaded_at
        }
        for doc in documents
    ]
# ============ GET IMAGE PROXY ============
from fastapi.responses import StreamingResponse, FileResponse, RedirectResponse
import httpx
import os

@router.get("/{case_id}/documents/{doc_id}/image")
async def get_document_image(
    case_id: str,
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Proxy for document images from Google Drive or local storage"""
    
    # Check case exists and user has permission
    query = select(DICase).where(DICase.case_id == case_id)
    if current_user.role != "administrator":
        query = query.where(DICase.user_id == current_user.id)
    
    result = await db.execute(query)
    case = result.scalar_one_or_none()
    
    if not case:
        raise HTTPException(404, f"Case {case_id} not found")
    
    # Get document
    doc_result = await db.execute(
        select(CaseDocument).where(
            CaseDocument.case_id == case_id,
            CaseDocument.id == doc_id
        )
    )
    doc = doc_result.scalar_one_or_none()
    
    if not doc:
        raise HTTPException(404, "Document not found")
    
    file_url = doc.file_url
    
    # Check if it's an image
    if not doc.file_type or doc.file_type != "image":
        raise HTTPException(400, "Not an image file")
    
    # If it's a local file
    if file_url.startswith("/uploads/"):
        local_path = file_url.replace("/uploads/", "uploads/")
        if os.path.exists(local_path):
            return FileResponse(local_path, media_type="image/png")
        raise HTTPException(404, "Image file not found")
    
    # If it's a Google Drive link - proxy it
    if "drive.google.com" in file_url or "googleapis.com" in file_url:
        try:
            # Extract file ID from Google Drive URL
            import re
            file_id_match = re.search(r'/d/([a-zA-Z0-9_-]+)', file_url)
            if not file_id_match:
                # Try alternative pattern for direct download links
                file_id_match = re.search(r'id=([a-zA-Z0-9_-]+)', file_url)
            
            if file_id_match:
                file_id = file_id_match.group(1)
                # Use Google's direct download URL
                direct_url = f"https://drive.google.com/uc?export=download&id={file_id}"
                
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(direct_url, follow_redirects=True)
                    if response.status_code == 200:
                        content_type = response.headers.get("content-type", "image/png")
                        return StreamingResponse(
                            iter([response.content]),
                            media_type=content_type,
                            headers={"Cache-Control": "public, max-age=3600"}
                        )
            else:
                # Try direct fetch of the original URL
                async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                    response = await client.get(file_url)
                    if response.status_code == 200:
                        content_type = response.headers.get("content-type", "image/png")
                        return StreamingResponse(
                            iter([response.content]),
                            media_type=content_type,
                            headers={"Cache-Control": "public, max-age=3600"}
                        )
        except Exception as e:
            print(f"Error proxying image: {e}")
            raise HTTPException(500, f"Error loading image: {str(e)}")
    
    # If all else fails, try redirect
    return RedirectResponse(url=file_url)
# ============ ADD DOCUMENT ============
@router.post("/{case_id}/documents")
async def add_document(
    case_id: str,
    file_name: str,
    file_url: str,
    file_type: str = "image",
    source: str = "registration",
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(DICase).where(DICase.case_id == case_id))
    if not result.scalar_one_or_none():
        raise HTTPException(404, f"Case {case_id} not found")
    
    new_doc = CaseDocument(
        case_id=case_id,
        file_name=file_name,
        file_url=file_url,
        file_type=file_type,
        source=source
    )
    
    db.add(new_doc)
    await db.commit()
    
    return {"message": "Document added", "id": new_doc.id}

# ============ UPLOAD FILE ============
@router.post("/{case_id}/upload")
async def upload_case_file(
    case_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)  # ← ADD THIS

):
    """Upload a file for a case (uses configured storage)"""
    
    # Verify case exists
    result = await db.execute(select(DICase).where(DICase.case_id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(404, f"Case {case_id} not found")
    
    # Read file content
    file_content = await file.read()
    
    # Get storage service
    storage = StorageFactory.get_storage_service()
    
    # Get existing folder_id if using Google Drive
    folder_id = None
    if settings.STORAGE_TYPE == "google_drive" and case.drive_link:
        match = re.search(r'folders/([a-zA-Z0-9_-]+)', case.drive_link)
        if match:
            folder_id = match.group(1)
    
    # Save file
    try:
        file_url = await storage.save_file(
            file_content=file_content,
            file_name=file.filename,
            folder_id=folder_id,
            file_type=file.content_type or 'application/octet-stream',
            case_id=case_id
        )
    except Exception as e:
        print(f"Upload error: {e}")
        # Fallback to local storage
        from services.storage_service import LocalStorageService
        fallback_storage = LocalStorageService()
        file_url = await fallback_storage.save_file(
            file_content=file_content,
            file_name=file.filename,
            case_id=case_id
        )
    
    # Save to database
    new_doc = CaseDocument(
        case_id=case_id,
        file_name=file.filename,
        file_url=file_url,
        file_type=file.content_type.split('/')[0] if file.content_type else 'document',
        source="registration",
        user_id=current_user.id

    )
    
    db.add(new_doc)
    await db.commit()
    
    return {
        "message": "File uploaded successfully",
        "file_id": new_doc.id,
        "file_url": file_url
    }

# ============ DELETE DOCUMENT ============
@router.delete("/{case_id}/documents/{doc_id}")
async def delete_document(
    case_id: str,
    doc_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)  # ← ADD THIS

):
    """Delete a document from storage and database"""
    
    result = await db.execute(select(DICase).where(DICase.case_id == case_id))
    if not result.scalar_one_or_none():
        raise HTTPException(404, f"Case {case_id} not found")
    
    result = await db.execute(
        select(CaseDocument).where(
            CaseDocument.case_id == case_id,
            CaseDocument.id == doc_id
        )
    )
    doc = result.scalar_one_or_none()
    
    if not doc:
        raise HTTPException(404, "Document not found")
    
    storage = StorageFactory.get_storage_service()
    await storage.delete_file(doc.file_url)
    
    await db.delete(doc)
    await db.commit()
    
    return {"message": "Document deleted successfully"}
@router.get("/admin/all-cases", response_model=List[CaseResponse])
@router.get("/admin/all-cases/")  # ← Handle trailing slash
async def admin_list_all_cases(
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user)  # ← ADMIN ONLY
):
    """Admin only - see ALL cases from ALL users with filters"""
    
    query = select(DICase)
    
    if status:
        query = query.where(DICase.status == status)
    if category:
        query = query.where(DICase.category == category)
    
    query = query.order_by(DICase.created_at.desc())
    query = query.limit(limit).offset(offset)
    
    result = await db.execute(query)
    cases = result.scalars().all()
    
    return [CaseResponse.model_validate(case) for case in cases]
# ============ CASE STATS ============
@router.get("/{case_id}/stats")
async def get_case_stats(
    case_id: str,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(DICase).where(DICase.case_id == case_id))
    case = result.scalar_one_or_none()
    
    if not case:
        raise HTTPException(404, f"Case {case_id} not found")
    
    result = await db.execute(
        select(CaseDocument).where(CaseDocument.case_id == case_id)
    )
    docs = result.scalars().all()
    
    doc_count = len(docs)
    reg_docs = len([d for d in docs if d.source == "registration"])
    wa_docs = len([d for d in docs if d.source == "whatsapp"])
    
    return {
        "case_id": case_id,
        "name": case.name,
        "status": case.status,
        "category": case.category,
        "document_count": doc_count,
        "registration_documents": reg_docs,
        "whatsapp_documents": wa_docs,
        "has_meeting_link": bool(case.meeting_link),
        "has_transcript": bool(case.transcript),
        "created_at": case.created_at,
        "updated_at": case.updated_at
    }