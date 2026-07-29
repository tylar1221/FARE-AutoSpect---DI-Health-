# services/drive_storage.py
"""
Google Drive Storage Service - Wrapper for easy integration
"""

import os
import tempfile
from typing import Optional, Dict
from services.google_drive_service import GoogleDriveService
from app.config import settings

class DriveStorageService:
    """Storage service using Google Drive"""
    
    def __init__(self):
        self.drive = GoogleDriveService()
        print("✅ Google Drive Storage Service initialized")
    
    async def create_case_folder(self, case_id: str, case_data: dict) -> Optional[Dict]:
        """Create a folder for a case in Google Drive"""
        result = self.drive.create_case_folder(case_id, case_data)
        return result
    
    async def save_file(self, file_content: bytes, file_name: str, 
                        folder_id: str = None, **kwargs) -> str:
        """
        Save a file to Google Drive case folder
        Returns: Drive file URL
        """
        file_type = kwargs.get('file_type', 'application/octet-stream')
        case_id = kwargs.get('case_id', None)
        
        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{file_name}") as temp_file:
            temp_file.write(file_content)
            temp_path = temp_file.name
        
        try:
            # If no folder_id provided, try to find or create one
            if not folder_id and case_id:
                folder_info = await self.get_case_folder(case_id)
                if folder_info:
                    folder_id = folder_info.get('folder_id')
            
            # Upload to Google Drive
            result = self.drive.upload_file_to_folder(
                folder_id=folder_id,
                file_path=temp_path,
                file_name=file_name,
                mime_type=file_type  # ✅ Now passing mime_type
            )
            
            if result:
                return result.get('file_link', '')
            else:
                raise Exception("Upload failed")
                
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    
    async def get_case_folder(self, case_id: str) -> Optional[Dict]:
        """Get existing folder for a case"""
        folder_info = self.drive.find_case_folder(case_id)
        return folder_info
    
    async def delete_file(self, file_id: str) -> bool:
        """Delete a file from Google Drive"""
        try:
            self.drive.service.files().delete(fileId=file_id).execute()
            return True
        except Exception as e:
            print(f"Error deleting file: {e}")
            return False
    
    async def get_folder_contents(self, folder_id: str) -> list:
        """Get all files in a folder"""
        return self.drive.list_folder_contents(folder_id)
    
    async def make_folder_public(self, folder_id: str) -> bool:
        """Make a folder publicly accessible"""
        return self.drive.make_folder_public(folder_id)