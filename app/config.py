# app/config.py - ADD SECRET_KEY
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # App
    APP_NAME: str = "FARE AutoSpect - DI Health"
    DEBUG: bool = True
    SECRET_KEY: str = "dev-secret-key-change-in-production"  # ← ALREADY EXISTS
    STORAGE_TYPE: str = "google_drive"

    # Database
    DATABASE_URL: Optional[str] = None
    DB_TYPE: str = "postgresql"
    WHATSAPP_API_URL: str = "https://graph.facebook.com/v25.0"
    WHATSAPP_ACCESS_TOKEN: Optional[str] = None
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = None
    WHATSAPP_VERIFY_TOKEN: Optional[str] = None
    WEBHOOK_BASE_URL: str = "http://13.201.194.47:8000"
    # RDS Configuration
    RDS_HOST: Optional[str] = None
    RDS_PORT: str = "5432"
    RDS_USER: Optional[str] = None
    RDS_PASSWORD: Optional[str] = None
    RDS_DATABASE: str = "Health_DI"

    # Google
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_DRIVE_FOLDER_ID: Optional[str] = None
    DRIVE_PARENT_FOLDER_ID: Optional[str] = None

    # WhatsApp
    WHATSAPP_API_URL: str = "https://graph.facebook.com/v25.0"
    WHATSAPP_ACCESS_TOKEN: Optional[str] = None
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = None
    WHATSAPP_VERIFY_TOKEN: Optional[str] = None

    # Gemini
    GEMINI_API_KEY: Optional[str] = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    def get_database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL

        if self.DB_TYPE == "postgresql" and self.RDS_HOST:
            return (
                f"postgresql+asyncpg://"
                f"{self.RDS_USER}:{self.RDS_PASSWORD}"
                f"@{self.RDS_HOST}:{self.RDS_PORT}/{self.RDS_DATABASE}"
            )

        return "sqlite+aiosqlite:///./di_health.db"


settings = Settings()