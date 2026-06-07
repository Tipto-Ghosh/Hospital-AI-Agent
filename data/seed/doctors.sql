USE hospital_ai;

SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE TABLE doctor_schedules;
TRUNCATE TABLE doctors;
SET FOREIGN_KEY_CHECKS = 1;

INSERT INTO doctors (
    doctor_id,
    full_name,
    specialization,
    department_id,
    qualification,
    experience_years,
    consultation_fee,
    phone,
    email,
    bio,
    is_active
)
VALUES

-- Emergency (dept 1)
(1, 'Dr. Arif Hossain', 'Emergency Medicine', 1,
 'MBBS, MD (Emergency Medicine)', 15, 700.00,
 '01711000001', 'arif.hossain@cityhospital.com',
 'Senior emergency physician with 15 years of trauma and critical care experience.', 1),

(2, 'Dr. Nusrat Jahan', 'Emergency Medicine', 1,
 'MBBS, FCPS (Emergency Medicine)', 8, 700.00,
 '01711000002', 'nusrat.jahan@cityhospital.com',
 'Specialises in acute cardiac emergencies and paediatric trauma.', 1),

-- Cardiology (dept 2)
(3, 'Dr. Kamal Uddin', 'Cardiologist', 2,
 'MBBS, MD (Cardiology), FRCP', 20, 1200.00,
 '01711000003', 'kamal.uddin@cityhospital.com',
 'Interventional cardiologist. Expertise in angioplasty and cardiac stenting.', 1),

(4, 'Dr. Fatema Begum', 'Cardiologist', 2,
 'MBBS, MD (Cardiology)', 12, 1000.00,
 '01711000004', 'fatema.begum@cityhospital.com',
 'Specialises in heart failure management and cardiac rehabilitation.', 1),

-- Neurology (dept 3)
(5, 'Dr. Shahriar Islam', 'Neurologist', 3,
 'MBBS, MD (Neurology), MRCP', 18, 1100.00,
 '01711000005', 'shahriar.islam@cityhospital.com',
 'Expert in stroke management, epilepsy, and movement disorders.', 1),

(6, 'Dr. Roksana Parvin', 'Neurologist', 3,
 'MBBS, FCPS (Neurology)', 10, 900.00,
 '01711000006', 'roksana.parvin@cityhospital.com',
 'Specialises in headache disorders and peripheral neuropathy.', 1),

-- Orthopedics (dept 4)
(7, 'Dr. Mizanur Rahman', 'Orthopedic Surgeon', 4,
 'MBBS, MS (Orthopedics)', 16, 1000.00,
 '01711000007', 'mizanur.rahman@cityhospital.com',
 'Joint replacement specialist: hip, knee, and shoulder arthroplasty.', 1),

(8, 'Dr. Tania Akter', 'Orthopedic Surgeon', 4,
 'MBBS, FCPS (Orthopedics)', 9, 850.00,
 '01711000008', 'tania.akter@cityhospital.com',
 'Sports medicine and arthroscopic surgery specialist.', 1),

-- Pediatrics (dept 5)
(9, 'Dr. Mahbub Alam', 'Pediatrician', 5,
 'MBBS, DCH, FCPS (Pediatrics)', 14, 800.00,
 '01711000009', 'mahbub.alam@cityhospital.com',
 'General paediatrics with subspecialty in neonatal care.', 1),

(10, 'Dr. Sadia Islam', 'Pediatrician', 5,
 'MBBS, MD (Pediatrics)', 7, 750.00,
 '01711000010', 'sadia.islam@cityhospital.com',
 'Specialises in paediatric infectious disease and immunisation.', 1),

-- General Medicine (dept 6)
(11, 'Dr. Rafiqul Haque', 'General Physician', 6,
 'MBBS, FCPS (Medicine)', 22, 600.00,
 '01711000011', 'rafiqul.haque@cityhospital.com',
 'Senior internist with expertise in diabetes and hypertension management.', 1),

(12, 'Dr. Nasreen Sultana', 'General Physician', 6,
 'MBBS, MCPS (Medicine)', 11, 500.00,
 '01711000012', 'nasreen.sultana@cityhospital.com',
 'Primary care physician with interest in preventive medicine.', 1),

-- Radiology (dept 7)
(13, 'Dr. Faisal Ahmed', 'Radiologist', 7,
 'MBBS, MD (Radiology)', 13, 800.00,
 '01711000013', 'faisal.ahmed@cityhospital.com',
 'Diagnostic and interventional radiologist. Expert in CT-guided procedures.', 1),

-- Oncology (dept 8)
(14, 'Dr. Laila Hossain', 'Oncologist', 8,
 'MBBS, MD (Oncology), MRCP', 17, 1500.00,
 '01711000014', 'laila.hossain@cityhospital.com',
 'Medical oncologist specialising in breast, lung, and GI cancers.', 1),

(15, 'Dr. Imran Chowdhury', 'Radiation Oncologist', 8,
 'MBBS, MD (Radiation Oncology)', 12, 1300.00,
 '01711000015', 'imran.chowdhury@cityhospital.com',
 'Specialist in IMRT, SBRT, and brachytherapy for solid tumours.', 1),

-- Gynecology (dept 9)
(16, 'Dr. Shirin Akter', 'Gynecologist', 9,
 'MBBS, FCPS (Obs & Gynae)', 19, 1000.00,
 '01711000016', 'shirin.akter@cityhospital.com',
 'High-risk pregnancy management and minimally invasive gynaecological surgery.', 1),

(17, 'Dr. Parveen Chowdhury', 'Gynecologist', 9,
 'MBBS, DGO, MCPS', 8, 800.00,
 '01711000017', 'parveen.chowdhury@cityhospital.com',
 'Antenatal care, normal and complicated deliveries, and family planning.', 1),

-- Dermatology (dept 10)
(18, 'Dr. Asif Mahmud', 'Dermatologist', 10,
 'MBBS, DDV, FCPS (Dermatology)', 10, 750.00,
 '01711000018', 'asif.mahmud@cityhospital.com',
 'Skin disease management including acne, psoriasis, eczema, and skin cancer screening.', 1);

INSERT INTO doctor_schedules (
    doctor_id,
    day_of_week,
    start_time,
    end_time,
    slot_duration_min,
    max_appointments,
    is_active
)
VALUES

-- Dr. Arif Hossain (Emergency)
(1, 'Monday', '09:00:00', '17:00:00', 20, 24, 1),
(1, 'Tuesday', '09:00:00', '17:00:00', 20, 24, 1),
(1, 'Wednesday', '09:00:00', '17:00:00', 20, 24, 1),
(1, 'Thursday', '09:00:00', '17:00:00', 20, 24, 1),
(1, 'Friday', '09:00:00', '17:00:00', 20, 24, 1),
(1, 'Saturday', '09:00:00', '14:00:00', 20, 15, 1),
(1, 'Sunday', '09:00:00', '14:00:00', 20, 15, 1),

-- Dr. Nusrat Jahan (Emergency)
(2, 'Monday', '14:00:00', '22:00:00', 20, 24, 1),
(2, 'Tuesday', '14:00:00', '22:00:00', 20, 24, 1),
(2, 'Wednesday', '14:00:00', '22:00:00', 20, 24, 1),
(2, 'Thursday', '14:00:00', '22:00:00', 20, 24, 1),
(2, 'Friday', '14:00:00', '22:00:00', 20, 24, 1),
(2, 'Saturday', '14:00:00', '22:00:00', 20, 24, 1),
(2, 'Sunday', '14:00:00', '22:00:00', 20, 24, 1),

-- Dr. Kamal Uddin (Cardiology)
(3, 'Monday', '09:00:00', '17:00:00', 20, 20, 1),
(3, 'Tuesday', '09:00:00', '17:00:00', 20, 20, 1),
(3, 'Wednesday', '09:00:00', '17:00:00', 20, 20, 1),
(3, 'Thursday', '09:00:00', '17:00:00', 20, 20, 1),
(3, 'Friday', '09:00:00', '13:00:00', 20, 12, 1);

/* Remaining doctor_schedules rows follow the same formatting pattern */

-- Update department heads
UPDATE departments SET head_doctor_id = 1 WHERE department_id = 1;   -- Emergency
UPDATE departments SET head_doctor_id = 3 WHERE department_id = 2;   -- Cardiology
UPDATE departments SET head_doctor_id = 5 WHERE department_id = 3;   -- Neurology
UPDATE departments SET head_doctor_id = 7 WHERE department_id = 4;   -- Orthopedics
UPDATE departments SET head_doctor_id = 9 WHERE department_id = 5;   -- Pediatrics
UPDATE departments SET head_doctor_id = 11 WHERE department_id = 6;  -- General Medicine
UPDATE departments SET head_doctor_id = 13 WHERE department_id = 7;  -- Radiology
UPDATE departments SET head_doctor_id = 14 WHERE department_id = 8;  -- Oncology
UPDATE departments SET head_doctor_id = 16 WHERE department_id = 9;  -- Gynecology
UPDATE departments SET head_doctor_id = 18 WHERE department_id = 10; -- Dermatology