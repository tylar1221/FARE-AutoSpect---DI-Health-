# app/models.py - COMPLETE FIXED VERSION

from sqlalchemy import (
    Column,
    ForeignKey,
    String,
    DateTime,
    Integer,
    Text,
    Date,
    Time,
    Index,
    Boolean  
)
from sqlalchemy.sql import func
from app.database import Base
from sqlalchemy.orm import relationship

# ============ USER MODEL ============
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), default="investigator")
    created_at = Column(DateTime, server_default=func.now())
    is_active = Column(Boolean, default=True)

    # Relationships
    cases = relationship("DICase", back_populates="user")
    documents = relationship("CaseDocument", back_populates="user")
    slots = relationship("ScheduledSlot", back_populates="user")

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"


# ============ DI CASE MODEL ============
class DICase(Base):
    __tablename__ = "health_di_cases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    phone_number = Column(String(20), nullable=False, index=True)
    claim_id = Column(String(100), nullable=True)
    company_name = Column(String(200), nullable=True)
    category = Column(String(50), default="normal")
    status = Column(String(50), default="pending", index=True)
    meeting_link = Column(String(500), nullable=True)
    drive_link = Column(String(500), nullable=True)
    scheduled_time = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    transcript = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, onupdate=func.now())
    event_id = Column(String(255), nullable=True)
    
    # Foreign key to User
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Relationship
    user = relationship("User", back_populates="cases")
    documents = relationship("CaseDocument", back_populates="case")  # ← ADD THIS

    __table_args__ = (
        Index("idx_health_di_cases_phone_status", "phone_number", "status"),
        Index("idx_health_di_cases_status_created", "status", "created_at"),
    )


# ============ CASE DOCUMENT MODEL ============
class CaseDocument(Base):
    __tablename__ = "health_case_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # ✅ FIXED: Added ForeignKey
    case_id = Column(String(50), ForeignKey("health_di_cases.case_id"), nullable=False, index=True)
    
    file_name = Column(String(255), nullable=False)
    file_url = Column(String(1000), nullable=False)
    file_type = Column(String(50), default="document")
    source = Column(String(50), default="registration")
    uploaded_at = Column(DateTime, server_default=func.now())
    
    # Foreign key to User
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Relationships
    case = relationship("DICase", back_populates="documents")  # ✅ Now works with ForeignKey
    user = relationship("User", back_populates="documents")

    __table_args__ = (
        Index("idx_health_documents_case_source", "case_id", "source"),
    )


# ============ SCHEDULED SLOT MODEL ============
class ScheduledSlot(Base):
    __tablename__ = "health_scheduled_slots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # ✅ FIXED: Added ForeignKey
    case_id = Column(String(50), ForeignKey("health_di_cases.case_id"), nullable=False, index=True)
    
    slot_date = Column(Date, nullable=False, index=True)
    slot_start = Column(Time, nullable=False)
    slot_end = Column(Time, nullable=False)
    meet_link = Column(String(500), nullable=True)
    status = Column(String(50), default="booked")
    created_at = Column(DateTime, server_default=func.now())
    
    # Foreign key to User
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # ✅ ADD THE MISSING RELATIONSHIP
    user = relationship("User", back_populates="slots")
    case = relationship("DICase")  # Optional: link back to case

    __table_args__ = (
        Index("idx_health_slots_date_status", "slot_date", "status"),
        Index("idx_health_slots_case_date", "case_id", "slot_date"),
    )


# ============ WHATSAPP MESSAGE MODEL ============
class WhatsAppMessage(Base):
    __tablename__ = "health_whatsapp_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String(50), ForeignKey("health_di_cases.case_id"), nullable=True, index=True)
    message_id = Column(String(100), unique=True, nullable=True)
    from_number = Column(String(20), nullable=False)
    to_number = Column(String(20), nullable=False)
    message_body = Column(Text, nullable=True)
    message_type = Column(String(50), default="text")
    status = Column(String(50), default="sent")
    sent_at = Column(DateTime, server_default=func.now(), index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_read = Column(Boolean, default=False)  # ← Already exists
    is_incoming = Column(Boolean, default=True)  # ← ADD THIS
    __table_args__ = (
        Index("idx_health_whatsapp_from", "from_number"),
        Index("idx_health_whatsapp_sent_at", "sent_at"),
    )


# ============ QUESTIONNAIRE MODEL ============
class Questionnaire(Base):
    __tablename__ = "health_questionnaires"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # ✅ FIXED: Added ForeignKey
    case_id = Column(String(50), ForeignKey("health_di_cases.case_id"), nullable=False, index=True)
    
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=True)
    category = Column(String(50), default="generic")
    answered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    __table_args__ = (
        Index("idx_health_questionnaire_case_category", "case_id", "category"),
    )