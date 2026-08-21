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
    
    async def create_case_folder(self, case_id: str, case_data: Dict) -> Optional[Dict]:
        """Create a Drive folder for a case"""
        try:
            print(f"📁 Creating Drive folder for case {case_id}")
            existing = self.drive.find_case_folder(case_id)
            if existing:
                print(f"♻️ Folder already exists for {case_id}")
                return existing
            
            folder_info = self.drive.create_case_folder(case_id, case_data)
            if folder_info:
                print(f"✅ Created Drive folder: {folder_info.get('drive_link')}")
                return folder_info
            return None
        except Exception as e:
            print(f"❌ Error creating Drive folder: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def find_case_folder(self, case_id: str) -> Optional[Dict]:
        """Find a case folder in Drive"""
        try:
            return self.drive.find_case_folder(case_id)
        except Exception as e:
            print(f"❌ Error finding case folder: {e}")
            return None
    
    async def save_file(self, file_content: bytes, file_name: str, 
                        folder_id: str = None, **kwargs) -> str:
        """Save file to Google Drive"""
        try:
            case_id = kwargs.get('case_id')
            source = kwargs.get('source', 'unknown')
            
            print(f"📁 save_file: case_id={case_id}, folder_id={folder_id}, source={source}, file={file_name}")
            
            target_folder_id = folder_id
            
            if not target_folder_id and case_id:
                print(f"🔍 Finding/creating case folder for {case_id}")
                case_folder = self.drive.find_case_folder(case_id)
                
                if not case_folder:
                    case_data = await self._get_case_data(case_id)
                    if not case_data:
                        raise ValueError(f"Case {case_id} not found")
                    case_folder = self.drive.create_case_folder(case_id, case_data)
                
                if not case_folder:
                    raise ValueError(f"Could not find or create case folder for {case_id}")
                
                # Determine subfolder based on source
                if source == 'whatsapp' or source == 'whatsapp_media':
                    subfolder_name = 'whatsapp'
                else:
                    subfolder_name = 'documents'
                
                print(f"📁 Using {subfolder_name}/ subfolder for source={source}")
                target_folder_id = await self._get_or_create_subfolder(
                    case_folder['folder_id'], 
                    subfolder_name
                )
                
                if not target_folder_id:
                    target_folder_id = case_folder['folder_id']
            
            if not target_folder_id:
                raise ValueError("No target folder specified")
            
            print(f"📁 Target folder ID: {target_folder_id}")
            
            # Save temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{file_name}") as tmp:
                tmp.write(file_content)
                tmp_path = tmp.name
            
            result = self.drive.upload_file_to_folder(
                folder_id=target_folder_id,
                file_path=tmp_path,
                file_name=file_name
            )
            
            os.unlink(tmp_path)
            
            if not result:
                raise ValueError("Upload returned no result")
            
            print(f"✅ File uploaded: {file_name}")
            return result['file_link']
            
        except Exception as e:
            print(f"❌ DriveStorage error: {e}")
            import traceback
            traceback.print_exc()
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
    
    async def _get_or_create_subfolder(self, parent_folder_id: str, subfolder_name: str) -> Optional[str]:
        """Find existing subfolder or create new one"""
        try:
            existing_id = self.drive.find_subfolder(parent_folder_id, subfolder_name)
            if existing_id:
                print(f"✓ Found existing subfolder: {subfolder_name}")
                return existing_id
            
            subfolder = self.drive.create_subfolder(parent_folder_id, subfolder_name)
            if subfolder and subfolder.get('folder_id'):
                folder_id = subfolder['folder_id']
                print(f"✅ Created subfolder: {subfolder_name}")
                return folder_id
            return None
        except Exception as e:
            print(f"❌ Error in _get_or_create_subfolder: {e}")
            return None
    
    async def _get_case_data(self, case_id: str) -> Optional[Dict]:
        """Fetch case data from database"""
        try:
            from sqlalchemy import select
            from app.database import get_db
            from app.models import DICase
            
            async for db in get_db():
                try:
                    result = await db.execute(
                        select(DICase).where(DICase.case_id == case_id)
                    )
                    case = result.scalar_one_or_none()
                    if case:
                        return {
                            'name': case.name,
                            'phone_number': case.phone_number,
                            'claim_id': case.claim_id
                        }
                except Exception as e:
                    print(f"⚠️ DB query error: {e}")
                    continue
                finally:
                    break
            return None
        except Exception as e:
            print(f"❌ Error getting case data: {e}")
            return None