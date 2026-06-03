-- ============================================================
-- Hospital Multi-Agent AI System
-- FILE: 01_create_schema.sql
-- PURPOSE: Create database and all tables
-- ============================================================

CREATE DATABASE IF NOT EXISTS hospital_ai
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE hospital_ai;

-- ─────────────────────────────────────────
-- 1. DEPARTMENTS
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS departments (
    department_id   INT AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    floor_location  VARCHAR(50),
    phone_extension VARCHAR(10),
    head_doctor_id  INT DEFAULT NULL,   -- FK added after doctors table
    description     TEXT,
    is_active       BOOLEAN DEFAULT TRUE
);

-- ─────────────────────────────────────────
-- 2. DOCTORS
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS doctors (
    doctor_id        INT AUTO_INCREMENT PRIMARY KEY,
    full_name        VARCHAR(100) NOT NULL,
    specialization   VARCHAR(100) NOT NULL,
    department_id    INT NOT NULL,
    qualification    VARCHAR(200),
    experience_years INT,
    consultation_fee DECIMAL(10, 2),
    phone            VARCHAR(15),
    email            VARCHAR(100),
    bio              TEXT,
    is_active        BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (department_id) REFERENCES departments(department_id)
);

-- Now add the FK on departments.head_doctor_id
ALTER TABLE departments
    ADD CONSTRAINT fk_dept_head_doctor
    FOREIGN KEY (head_doctor_id) REFERENCES doctors(doctor_id)
    ON DELETE SET NULL;

-- ─────────────────────────────────────────
-- 3. DOCTOR SCHEDULES
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS doctor_schedules (
    schedule_id       INT AUTO_INCREMENT PRIMARY KEY,
    doctor_id         INT NOT NULL,
    day_of_week       ENUM('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday') NOT NULL,
    start_time        TIME NOT NULL,
    end_time          TIME NOT NULL,
    slot_duration_min INT DEFAULT 20,
    max_appointments  INT DEFAULT 15,
    is_active         BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (doctor_id) REFERENCES doctors(doctor_id)
);

-- ─────────────────────────────────────────
-- 4. PATIENTS
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS patients (
    patient_id         VARCHAR(20) PRIMARY KEY,
    full_name          VARCHAR(100) NOT NULL,
    date_of_birth      DATE NOT NULL,
    gender             ENUM('Male','Female','Other') NOT NULL,
    blood_group        VARCHAR(5),
    phone              VARCHAR(15) UNIQUE NOT NULL,
    email              VARCHAR(100),
    address            TEXT,
    emergency_contact  VARCHAR(15),
    insurance_id       VARCHAR(50),
    insurance_provider VARCHAR(100),
    registration_date  DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_active          BOOLEAN DEFAULT TRUE
);

-- ─────────────────────────────────────────
-- 5. APPOINTMENTS
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS appointments (
    appointment_id      VARCHAR(20) PRIMARY KEY,
    patient_id          VARCHAR(20) NOT NULL,
    doctor_id           INT NOT NULL,
    scheduled_at        DATETIME NOT NULL,
    duration_min        INT DEFAULT 20,
    status              ENUM('pending','confirmed','completed','cancelled','no_show') DEFAULT 'pending',
    reason_for_visit    TEXT,
    notes               TEXT,
    booked_via          ENUM('ai_agent','web','phone','walk_in') DEFAULT 'ai_agent',
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME ON UPDATE CURRENT_TIMESTAMP,
    cancelled_at        DATETIME,
    cancellation_reason TEXT,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
    FOREIGN KEY (doctor_id)  REFERENCES doctors(doctor_id),
    INDEX idx_doctor_datetime (doctor_id, scheduled_at),
    INDEX idx_patient_status  (patient_id, status)
);

-- ─────────────────────────────────────────
-- 6. MEDICAL RECORDS
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS medical_records (
    record_id      INT AUTO_INCREMENT PRIMARY KEY,
    patient_id     VARCHAR(20) NOT NULL,
    appointment_id VARCHAR(20),
    doctor_id      INT NOT NULL,
    visit_date     DATE NOT NULL,
    chief_complaint TEXT,
    diagnosis      TEXT,
    treatment_plan TEXT,
    follow_up_date DATE,
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id)     REFERENCES patients(patient_id),
    FOREIGN KEY (doctor_id)      REFERENCES doctors(doctor_id),
    FOREIGN KEY (appointment_id) REFERENCES appointments(appointment_id)
);

-- ─────────────────────────────────────────
-- 7. LAB RESULTS
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lab_results (
    result_id         INT AUTO_INCREMENT PRIMARY KEY,
    patient_id        VARCHAR(20) NOT NULL,
    test_name         VARCHAR(100) NOT NULL,
    test_date         DATE NOT NULL,
    result_value      TEXT,
    unit              VARCHAR(30),
    reference_range   VARCHAR(50),
    is_abnormal       BOOLEAN DEFAULT FALSE,
    ordered_by_doctor INT,
    notes             TEXT,
    FOREIGN KEY (patient_id)        REFERENCES patients(patient_id),
    FOREIGN KEY (ordered_by_doctor) REFERENCES doctors(doctor_id)
);

-- ─────────────────────────────────────────
-- 8. PRESCRIPTIONS
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS prescriptions (
    prescription_id INT AUTO_INCREMENT PRIMARY KEY,
    patient_id      VARCHAR(20) NOT NULL,
    doctor_id       INT NOT NULL,
    prescribed_date DATE NOT NULL,
    medication_name VARCHAR(100) NOT NULL,
    dosage          VARCHAR(50),
    frequency       VARCHAR(50),
    duration_days   INT,
    is_active       BOOLEAN DEFAULT TRUE,
    notes           TEXT,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
    FOREIGN KEY (doctor_id)  REFERENCES doctors(doctor_id)
);

-- ─────────────────────────────────────────
-- 9. BILLING INVOICES
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS billing_invoices (
    invoice_id     VARCHAR(20) PRIMARY KEY,
    patient_id     VARCHAR(20) NOT NULL,
    appointment_id VARCHAR(20),
    total_amount   DECIMAL(10, 2) NOT NULL,
    paid_amount    DECIMAL(10, 2) DEFAULT 0.00,
    status         ENUM('unpaid','partial','paid','waived') DEFAULT 'unpaid',
    due_date       DATE,
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id)     REFERENCES patients(patient_id),
    FOREIGN KEY (appointment_id) REFERENCES appointments(appointment_id)
);

-- ─────────────────────────────────────────
-- 10. INVOICE ITEMS
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS invoice_items (
    item_id     INT AUTO_INCREMENT PRIMARY KEY,
    invoice_id  VARCHAR(20) NOT NULL,
    description VARCHAR(200) NOT NULL,
    quantity    INT DEFAULT 1,
    unit_price  DECIMAL(10, 2) NOT NULL,
    total_price DECIMAL(10, 2) NOT NULL,
    FOREIGN KEY (invoice_id) REFERENCES billing_invoices(invoice_id)
);

-- ─────────────────────────────────────────
-- 11. MEDICATIONS (reference)
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS medications (
    medication_id          INT AUTO_INCREMENT PRIMARY KEY,
    generic_name           VARCHAR(100) NOT NULL,
    brand_names            TEXT,
    drug_class             VARCHAR(100),
    common_uses            TEXT,
    side_effects           TEXT,
    contraindications      TEXT,
    general_dosage         TEXT,
    requires_prescription  BOOLEAN DEFAULT TRUE
);

-- ─────────────────────────────────────────
-- 12. DRUG INTERACTIONS (reference)
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS drug_interactions (
    interaction_id INT AUTO_INCREMENT PRIMARY KEY,
    drug_a         VARCHAR(100) NOT NULL,
    drug_b         VARCHAR(100) NOT NULL,
    severity       ENUM('mild','moderate','severe','contraindicated') NOT NULL,
    description    TEXT NOT NULL
);

-- ─────────────────────────────────────────
-- 13. HOSPITAL INFO (static lookup)
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS hospital_info (
    info_id      INT AUTO_INCREMENT PRIMARY KEY,
    category     VARCHAR(50) NOT NULL,
    topic        VARCHAR(100) NOT NULL,
    content      TEXT NOT NULL,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- ─────────────────────────────────────────
-- 14. FEEDBACK
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS feedback (
    feedback_id INT AUTO_INCREMENT PRIMARY KEY,
    patient_id  VARCHAR(20),
    category    ENUM('general','doctor','billing','facilities','staff','ai_agent') NOT NULL,
    message     TEXT NOT NULL,
    rating      TINYINT CHECK (rating BETWEEN 1 AND 5),
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
);

-- ─────────────────────────────────────────
-- 15. COMPLAINT TICKETS
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS complaint_tickets (
    ticket_id       VARCHAR(20) PRIMARY KEY,
    patient_id      VARCHAR(20),
    department      VARCHAR(100),
    description     TEXT NOT NULL,
    status          ENUM('open','in_review','resolved','escalated') DEFAULT 'open',
    priority        ENUM('low','medium','high','critical') DEFAULT 'medium',
    assigned_to     VARCHAR(100),
    resolution_note TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    resolved_at     DATETIME,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
);

-- ─────────────────────────────────────────
-- 16. AUDIT LOG (append-only)
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    log_id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id      VARCHAR(64),
    patient_id      VARCHAR(20),
    agent_name      VARCHAR(50) NOT NULL,
    action          VARCHAR(100) NOT NULL,
    resource_type   VARCHAR(50),
    resource_id     VARCHAR(50),
    payload_summary TEXT,
    ip_address      VARCHAR(45),
    timestamp       DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_patient_audit (patient_id, timestamp),
    INDEX idx_session_audit (session_id)
);

-- ─────────────────────────────────────────
-- 17. CONVERSATION SESSIONS
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversation_sessions (
    session_id     VARCHAR(64) PRIMARY KEY,
    patient_id     VARCHAR(20),
    started_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_active_at DATETIME,
    channel        ENUM('web','whatsapp','kiosk','api') DEFAULT 'web',
    is_active      BOOLEAN DEFAULT TRUE,
    metadata       JSON,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
);

-- ─────────────────────────────────────────
-- 18. CONVERSATION MEMORY
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversation_memory (
    memory_id  INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,
    patient_id VARCHAR(20),
    role       ENUM('human','ai','system') NOT NULL,
    content    TEXT NOT NULL,
    agent_name VARCHAR(50),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_session_memory (session_id, created_at),
    FOREIGN KEY (session_id) REFERENCES conversation_sessions(session_id)
);

-- ─────────────────────────────────────────
-- 19. PATIENT LONG-TERM CONTEXT
-- ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS patient_long_term_context (
    context_id            INT AUTO_INCREMENT PRIMARY KEY,
    patient_id            VARCHAR(20) NOT NULL UNIQUE,
    preferred_doctor      INT,
    preferred_time_slot   VARCHAR(20),
    language_preference   VARCHAR(10) DEFAULT 'en',
    communication_opt_in  BOOLEAN DEFAULT TRUE,
    last_concern          TEXT,
    updated_at            DATETIME ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id)       REFERENCES patients(patient_id),
    FOREIGN KEY (preferred_doctor) REFERENCES doctors(doctor_id)
);

-- ============================================================
-- Schema creation complete.
-- Run 02_seed_data.sql next.
-- ============================================================
