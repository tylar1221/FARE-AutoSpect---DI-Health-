# services/drive_storage.py
import os
import tempfile
from typing import Optional, Dict, Any
from services.google_drive_service import GoogleDriveService

class DriveStorageService:
    """Handles file operations with Google Drive"""
    
    def __init__(self):
        self.drive = GoogleDriveService()
        print("✅ DriveStorageService initialized")
    
    async def save_file(self, file_content: bytes, file_name: str, 
                    folder_id: str = None, **kwargs) -> str:
        """
        Save file to Google Drive
        
        Args:
            file_content: Binary file content
            file_name: Name of the file
            folder_id: Specific folder ID (optional) - can be subfolder!
            **kwargs: Additional args (case_id, file_type, etc.)
        """
        try:
            case_id = kwargs.get('case_id')
            file_type = kwargs.get('file_type', 'document')
            
            # Determine target folder
            target_folder_id = folder_id
            
            # If no folder_id provided, use case_id to find/create
            if not target_folder_id and case_id:
                # Find or create case folder
                case_folder = self.drive.find_case_folder(case_id)
                if not case_folder:
                    # Get case data from database
                    case_data = await self._get_case_data(case_id)
                    if not case_data:
                        raise ValueError(f"Case {case_id} not found")
                    case_folder = self.drive.create_case_folder(case_id, case_data)
                
                # For WhatsApp files, use whatsapp/ subfolder
                # For website uploads, folder_id is already set to documents/
                if not folder_id:
                    subfolder_name = 'whatsapp'  # Default for WhatsApp
                    target_folder_id = await self._get_or_create_subfolder(
                        case_folder['folder_id'], 
                        subfolder_name
                    )
                else:
                    # folder_id already provided (e.g., documents/ subfolder)
                    target_folder_id = folder_id
            
            if not target_folder_id:
                raise ValueError("No target folder specified")
            
            # Save temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{file_name}") as tmp:
                tmp.write(file_content)
                tmp_path = tmp.name
            
            # Upload to Drive
            result = self.drive.upload_file_to_folder(
                folder_id=target_folder_id,
                file_path=tmp_path,
                file_name=file_name
            )
            
            # Cleanup
            os.unlink(tmp_path)
            
            return result['file_link']
            
        except Exception as e:
            print(f"❌ DriveStorage error: {e}")
            raise
    
    async def delete_file(self, file_id: str) -> bool:
        """Delete a file from Google Drive"""
        try:
            self.drive.service.files().delete(fileId=file_id).execute()
            print(f"🗑️ Deleted file: {file_id}")
            return True
        except Exception as e:
            print(f"❌ Delete error: {e}")
            return False
    
    def _get_subfolder_name(self, file_type: str) -> str:
        """✅ ALL WhatsApp files go to whatsapp folder"""
        # Everything from WhatsApp goes to whatsapp/
        return 'whatsapp'
    
    async def _get_or_create_subfolder(self, parent_folder_id: str, subfolder_name: str) -> str:
        """Find existing subfolder or create new one"""
        # List all contents
        contents = self.drive.list_folder_contents(parent_folder_id)
        
        # Look for subfolder
        for item in contents:
            if (item['mimeType'] == 'application/vnd.google-apps.folder' and 
                item['name'] == subfolder_name):
                return item['id']
        
        # Create if not exists
        subfolder = self.drive.create_subfolder(parent_folder_id, subfolder_name)
        return subfolder['folder_id']
    
    async def _get_case_data(self, case_id: str) -> Optional[Dict]:
        """Fetch case data from database"""
        from sqlalchemy.ext.asyncio import AsyncSession
        from sqlalchemy import select
        from app.database import get_db
        from app.models import DICase
        
        async for db in get_db():
            result = await db.execute(
                select(DICase).where(DICase.case_id == case_id)
            )
            case = result.scalars().first()
            if case:
                return {
                    'name': case.name,
                    'phone_number': case.phone_number,
                    'claim_id': case.claim_id
                }
        return None