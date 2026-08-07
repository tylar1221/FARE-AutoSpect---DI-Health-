# services/google_drive_service.py
import os
import pickle
from typing import Dict, List, Optional
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from datetime import datetime
from app.config import settings

class GoogleDriveService:
    """Handles all Google Drive operations using OAuth."""
    
    def __init__(self, credentials_file: str = "credentials.json"):
        self.credentials_file = credentials_file
        self.token_file = "token_combined.pickle"
        self.service = None
        self.main_folder_name = "di_cases"
        self.drive_parent_folder_id = settings.DRIVE_PARENT_FOLDER_ID
        print(f"📁 Using Drive Parent Folder ID: {self.drive_parent_folder_id}")
        self.authenticate()
    
    def authenticate(self) -> bool:
        """Authenticate with Google Drive API using existing token."""
        try:
            creds = None
            
            if os.path.exists(self.token_file):
                with open(self.token_file, "rb") as f:
                    creds = pickle.load(f)
                    print(f"📁 Loaded Drive token from {self.token_file}")
            
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                print("🔄 Drive token refreshed")
            elif not creds or not creds.valid:
                print("❌ No valid token found. Run Calendar auth first.")
                return False
            
            self.service = build("drive", "v3", credentials=creds)
            print("✅ Connected to Google Drive (OAuth)")
            return True
            
        except Exception as e:
            print(f"❌ Drive authentication failed: {e}")
            return False
    def find_subfolder(self, parent_folder_id: str, subfolder_name: str) -> Optional[str]:
        """Find a subfolder by name inside parent folder"""
        try:
            query = (
                f"name='{subfolder_name}' "
                f"and '{parent_folder_id}' in parents "
                f"and mimeType='application/vnd.google-apps.folder' "
                f"and trashed=false"
            )
            
            results = self.service.files().list(
                q=query,
                spaces='drive',
                fields='files(id, name)',
                pageSize=10
            ).execute()
            
            files = results.get('files', [])
            
            if files:
                return files[0].get('id')
            return None
            
        except Exception as e:
            print(f"❌ Error finding subfolder: {e}")
            return None




    def get_or_create_subfolder(self, parent_folder_id: str, subfolder_name: str) -> Optional[str]:
        """Get existing subfolder or create new one"""
        try:
            # First try to find existing
            subfolder_id = self.find_subfolder(parent_folder_id, subfolder_name)
            if subfolder_id:
                print(f"✓ Found existing subfolder: {subfolder_name}")
                return subfolder_id
            
            # Create new subfolder
            folder_metadata = {
                'name': subfolder_name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [parent_folder_id]
            }
            
            folder = self.service.files().create(
                body=folder_metadata,
                fields='id, webViewLink'
            ).execute()
            
            folder_id = folder.get('id')
            print(f"✅ Created subfolder: {subfolder_name}")
            return folder_id
            
        except Exception as e:
            print(f"❌ Error creating subfolder: {e}")
            return None
    def make_folder_public(self, folder_id: str) -> bool:
        """Make a Google Drive folder publicly accessible."""
        try:
            permission = {
                'type': 'anyone',
                'role': 'reader',  # Changed to 'reader' for security
                'allowFileDiscovery': False
            }
            
            self.service.permissions().create(
                fileId=folder_id,
                body=permission,
                fields='id'
            ).execute()
            
            print(f"🔓 Made folder public: https://drive.google.com/drive/folders/{folder_id}")
            return True
            
        except Exception as e:
            print(f"❌ Failed to make folder public: {e}")
            return False
    
    def find_case_folder(self, case_id: str) -> Optional[Dict]:
        """Check if a folder for this case already exists."""
        try:
            main_folder_id = self.get_or_create_main_folder()
            if not main_folder_id:
                return None
            
            query = (
                f"name contains 'Case_{case_id}_' "
                f"and '{main_folder_id}' in parents "
                f"and mimeType='application/vnd.google-apps.folder' "
                f"and trashed=false"
            )
            
            results = self.service.files().list(
                q=query,
                spaces='drive',
                fields='files(id, name, webViewLink, createdTime)',
                pageSize=10
            ).execute()
            
            files = results.get('files', [])
            
            if files:
                folder = files[0]
                folder_id = folder.get('id')
                drive_link = f"https://drive.google.com/drive/folders/{folder_id}"
                
                print(f"♻️ Found existing folder for case {case_id}")
                return {
                    'folder_id': folder_id,
                    'drive_link': drive_link,
                    'folder_name': folder.get('name'),
                    'is_existing': True
                }
            else:
                return None
                
        except Exception as e:
            print(f"❌ Error searching for folder: {e}")
            return None
    
    def get_or_create_main_folder(self) -> Optional[str]:
        """Get or create the main 'di_cases' folder INSIDE Health_DI."""
        try:
            print(f"🔍 Looking for '{self.main_folder_name}' inside folder: {self.drive_parent_folder_id}")
            
            query = (
                f"name='{self.main_folder_name}' "
                f"and '{self.drive_parent_folder_id}' in parents "
                f"and mimeType='application/vnd.google-apps.folder' "
                f"and trashed=false"
            )
            
            results = self.service.files().list(
                q=query,
                spaces='drive',
                fields='files(id, name, webViewLink)',
                pageSize=10
            ).execute()
            
            files = results.get('files', [])
            
            if files:
                main_folder = files[0]
                folder_id = main_folder.get('id')
                print(f"✓ Found existing folder: {main_folder['name']} (ID: {folder_id})")
                return folder_id
            else:
                folder_metadata = {
                    'name': self.main_folder_name,
                    'mimeType': 'application/vnd.google-apps.folder',
                    'parents': [self.drive_parent_folder_id]
                }
                
                main_folder = self.service.files().create(
                    body=folder_metadata,
                    fields='id, name, webViewLink'
                ).execute()
                
                folder_id = main_folder.get('id')
                print(f"✓ Created new folder: {self.main_folder_name}")
                print(f"   Folder ID: {folder_id}")
                self.make_folder_public(folder_id)
                return folder_id
                
        except Exception as e:
            print(f"❌ Error with main folder: {e}")
            return None
    
    def create_case_folder(self, case_id: str, case_data: Dict) -> Optional[Dict]:
        """Create a folder for a specific case."""
        try:
            existing_folder = self.find_case_folder(case_id)
            
            if existing_folder:
                print(f"♻️ REUSING existing folder for case {case_id}")
                self.make_folder_public(existing_folder['folder_id'])
                return existing_folder
            
            main_folder_id = self.get_or_create_main_folder()
            if not main_folder_id:
                return None
            
            patient_name = case_data.get('name', 'Unknown')
            folder_name = f"Case_{case_id}_{patient_name.replace(' ', '_')}"
            
            folder_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [main_folder_id]
            }
            
            folder = self.service.files().create(
                body=folder_metadata, 
                fields='id, webViewLink'
            ).execute()
            
            folder_id = folder.get('id')
            drive_link = f"https://drive.google.com/drive/folders/{folder_id}"
            
            self.make_folder_public(folder_id)
            
            # Create subfolders
            self.create_subfolder(folder_id, "documents")
            self.create_subfolder(folder_id, "meeting_rec")
            self.create_subfolder(folder_id, "whatsapp")
            
            print(f"✅ Created folder for case {case_id}: {folder_name}")
            
            return {
                'folder_id': folder_id,
                'drive_link': drive_link,
                'folder_name': folder_name,
                'is_existing': False
            }
            
        except Exception as e:
            print(f"❌ Error creating folder: {e}")
            return None
    
    def create_subfolder(self, parent_folder_id: str, subfolder_name: str) -> Optional[Dict]:
        """Create a subfolder inside an existing folder."""
        try:
            folder_metadata = {
                'name': subfolder_name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [parent_folder_id]
            }
            
            folder = self.service.files().create(
                body=folder_metadata,
                fields='id, webViewLink'
            ).execute()
            
            folder_id = folder.get('id')
            drive_link = f"https://drive.google.com/drive/folders/{folder_id}"
            
            print(f"✅ Created subfolder: {subfolder_name}")
            
            return {
                'folder_id': folder_id,
                'drive_link': drive_link,
                'folder_name': subfolder_name
            }
        except Exception as e:
            print(f"❌ Error creating subfolder: {e}")
            return None
    
    def upload_file_to_folder(self, folder_id: str, file_path: str, 
                              file_name: str, mime_type: str = None) -> Optional[Dict]:
        """Upload a file to Google Drive folder."""
        try:
            file_metadata = {
                'name': file_name,
                'parents': [folder_id]
            }
            
            # Add mime type if provided
            if mime_type:
                file_metadata['mimeType'] = mime_type
            
            media = MediaFileUpload(file_path, resumable=True)
            
            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink, name'
            ).execute()
            
            print(f"✓ Uploaded file: {file_name}")
            
            return {
                'file_id': file.get('id'),
                'file_name': file.get('name'),
                'file_link': file.get('webViewLink')
            }
        except Exception as e:
            print(f"❌ Error uploading file: {e}")
            return None
    
    def list_folder_contents(self, folder_id: str) -> List[Dict]:
        """List all files in a folder."""
        try:
            results = self.service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="files(id, name, mimeType, size, webViewLink, createdTime)",
                pageSize=100
            ).execute()
            
            files = results.get('files', [])
            
            return [{
                'id': f.get('id'),
                'name': f.get('name'),
                'mimeType': f.get('mimeType'),
                'size': f.get('size'),
                'link': f.get('webViewLink'),
                'created': f.get('createdTime')
            } for f in files]
        except Exception as e:
            print(f"❌ Error listing folder contents: {e}")
            return []