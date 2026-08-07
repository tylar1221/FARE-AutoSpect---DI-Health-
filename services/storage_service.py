# services/storage_service.py
import os
from abc import ABC, abstractmethod
from typing import Optional
from app.config import settings

class StorageService(ABC):
    """Abstract base class for all storage services"""
    
    @abstractmethod
    async def save_file(self, file_content: bytes, file_name: str, 
                        folder_id: str = None, **kwargs) -> str:
        pass
    
    @abstractmethod
    async def delete_file(self, file_url: str) -> bool:
        pass


class LocalStorageService(StorageService):
    """Store files on local disk"""
    
    def __init__(self):
        self.upload_dir = "uploads"
        os.makedirs(self.upload_dir, exist_ok=True)
        print(f"📁 LocalStorage initialized: {self.upload_dir}")
    
    async def save_file(self, file_content: bytes, file_name: str, 
                        folder_id: str = None, **kwargs) -> str:
        """Save file to local folder"""
        case_id = kwargs.get('case_id', None)
        
        if case_id:
            folder_path = os.path.join(self.upload_dir, case_id)
        elif folder_id:
            folder_path = os.path.join(self.upload_dir, folder_id)
        else:
            folder_path = self.upload_dir
            
        os.makedirs(folder_path, exist_ok=True)
        
        file_path = os.path.join(folder_path, file_name)
        with open(file_path, "wb") as buffer:
            buffer.write(file_content)
        
        if case_id:
            file_url = f"/uploads/{case_id}/{file_name}"
        elif folder_id:
            file_url = f"/uploads/{folder_id}/{file_name}"
        else:
            file_url = f"/uploads/{file_name}"
            
        print(f"💾 File saved locally: {file_path}")
        return file_url
    
    async def delete_file(self, file_url: str) -> bool:
        """Delete file from local disk"""
        try:
            file_path = file_url.lstrip('/')
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"🗑️ Deleted: {file_path}")
                return True
            return False
        except Exception as e:
            print(f"Error deleting file: {e}")
            return False


class GoogleDriveStorageService(StorageService):
    """Store files on Google Drive - FIXED to use subfolders"""
    
    def __init__(self):
        from services.drive_storage import DriveStorageService
        self.drive_storage = DriveStorageService()
        print("✅ GoogleDriveStorage initialized")
    
    async def save_file(self, file_content: bytes, file_name: str, 
                        folder_id: str = None, **kwargs) -> str:
        """
        Save file to Google Drive
        - If case_id is provided, saves to case folder > subfolder
        - If folder_id is provided, saves directly to that folder
        """
        # Pass all kwargs to drive_storage (includes case_id, file_type)
        return await self.drive_storage.save_file(
            file_content=file_content,
            file_name=file_name,
            folder_id=folder_id,
            **kwargs  # ← KEY: Passes case_id and file_type
        )
    
    async def delete_file(self, file_url: str) -> bool:
        """Delete file from Google Drive"""
        import re
        match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', file_url)
        if match:
            file_id = match.group(1)
            return await self.drive_storage.delete_file(file_id)
        return False


class StorageFactory:
    """Factory to create storage service based on configuration"""
    
    _storage_service = None
    
    @classmethod
    def get_storage_service(cls) -> StorageService:
        if cls._storage_service is None:
            storage_type = settings.STORAGE_TYPE
            
            if storage_type == "google_drive":
                cls._storage_service = GoogleDriveStorageService()
            else:
                cls._storage_service = LocalStorageService()
            
            print(f"✅ Storage service initialized: {storage_type}")
        
        return cls._storage_service