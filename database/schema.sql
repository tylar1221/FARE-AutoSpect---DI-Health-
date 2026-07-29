-- database/schema.sql

-- Main cases table
CREATE TABLE IF NOT EXISTS di_cases (
    case_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    phone_number VARCHAR(20) NOT NULL,
    claim_id VARCHAR(50),
    company_name VARCHAR(200),
    category VARCHAR(20) DEFAULT 'normal',
    status VARCHAR(20) DEFAULT 'pending',
    meeting_link TEXT,
    drive_link TEXT,
    scheduled_time TIMESTAMP,
    notes TEXT,
    transcript TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Documents table
CREATE TABLE IF NOT EXISTS case_documents (
    id SERIAL PRIMARY KEY,
    case_id VARCHAR(50) REFERENCES di_cases(case_id) ON DELETE CASCADE,
    file_name VARCHAR(500),
    file_url TEXT,
    file_type VARCHAR(50),
    source VARCHAR(20),
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Scheduled slots
CREATE TABLE IF NOT EXISTS scheduled_slots (
    id SERIAL PRIMARY KEY,
    case_id VARCHAR(50) REFERENCES di_cases(case_id),
    slot_date DATE NOT NULL,
    slot_start TIME NOT NULL,
    slot_end TIME NOT NULL,
    meet_link TEXT,
    status VARCHAR(20) DEFAULT 'booked',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(slot_date, slot_start)
);

-- WhatsApp messages history
CREATE TABLE IF NOT EXISTS whatsapp_messages (
    id SERIAL PRIMARY KEY,
    message_id VARCHAR(100),
    from_number VARCHAR(20),
    to_number VARCHAR(20),
    case_id VARCHAR(50) REFERENCES di_cases(case_id),
    message_text TEXT,
    message_type VARCHAR(20),
    is_incoming BOOLEAN DEFAULT TRUE,
    is_read BOOLEAN DEFAULT FALSE,
    media_url TEXT,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Questionnaires
CREATE TABLE IF NOT EXISTS questionnaires (
    id SERIAL PRIMARY KEY,
    case_id VARCHAR(50) REFERENCES di_cases(case_id),
    question_category VARCHAR(50), -- 'generic' or 'specific'
    question_text TEXT,
    answer_text TEXT,
    answered_at TIMESTAMP,
    answered_by VARCHAR(100)
);

-- Create indexes
CREATE INDEX idx_cases_phone ON di_cases(phone_number);
CREATE INDEX idx_cases_status ON di_cases(status);
CREATE INDEX idx_documents_case ON case_documents(case_id);
CREATE INDEX idx_slots_date ON scheduled_slots(slot_date);
CREATE INDEX idx_messages_case ON whatsapp_messages(case_id);