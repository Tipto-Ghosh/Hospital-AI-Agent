-- ============================================================
-- Hospital Multi-Agent AI System
-- FILE: 02_seed_data.sql
-- PURPOSE: Insert realistic dummy data into all tables
-- ============================================================

USE hospital_ai;

-- ─────────────────────────────────────────
-- 1. DEPARTMENTS (insert first, no FK yet)
-- ─────────────────────────────────────────
INSERT INTO departments (name, floor_location, phone_extension, description) VALUES
('Cardiology',          'Floor 3, Wing A', '301', 'Diagnosis and treatment of heart and cardiovascular diseases.'),
('Neurology',           'Floor 4, Wing B', '410', 'Disorders of the nervous system including brain and spinal cord.'),
('Orthopedics',         'Floor 2, Wing C', '215', 'Conditions involving the musculoskeletal system, bones and joints.'),
('Pediatrics',          'Floor 1, Wing D', '105', 'Medical care for infants, children and adolescents up to age 18.'),
('Oncology',            'Floor 5, Wing A', '502', 'Diagnosis and treatment of cancer.'),
('Gastroenterology',    'Floor 3, Wing B', '320', 'Diseases of the digestive system and gastrointestinal tract.'),
('Dermatology',         'Floor 2, Wing A', '210', 'Conditions affecting the skin, hair and nails.'),
('Emergency Medicine',  'Floor 1, Wing A', '100', '24/7 emergency and critical care services.'),
('Radiology',           'Floor 1, Wing B', '110', 'Medical imaging including X-ray, MRI, CT scan and ultrasound.'),
('Pathology',           'Basement, Lab 1',  '001', 'Laboratory diagnosis through examination of blood, tissues and other specimens.');

-- ─────────────────────────────────────────
-- 2. DOCTORS
-- ─────────────────────────────────────────
INSERT INTO doctors (full_name, specialization, department_id, qualification, experience_years, consultation_fee, phone, email, bio) VALUES
('Dr. Arif Hossain',      'Cardiologist',           1, 'MBBS, MD (Cardiology), FRCP',            18, 1500.00, '01711000001', 'arif.hossain@hospital.bd',    'Senior cardiologist with expertise in interventional cardiology and heart failure management.'),
('Dr. Nasrin Sultana',    'Neurologist',            2, 'MBBS, MD (Neurology)',                   12, 1400.00, '01711000002', 'nasrin.sultana@hospital.bd',  'Specialist in stroke management, epilepsy and movement disorders.'),
('Dr. Kamal Uddin',       'Orthopedic Surgeon',     3, 'MBBS, MS (Orthopedics)',                 15, 1600.00, '01711000003', 'kamal.uddin@hospital.bd',     'Experienced in joint replacement, sports injuries and spinal surgeries.'),
('Dr. Fatema Begum',      'Pediatrician',           4, 'MBBS, DCH, MD (Pediatrics)',             10, 1200.00, '01711000004', 'fatema.begum@hospital.bd',    'Child specialist focusing on neonatal care, vaccinations and developmental disorders.'),
('Dr. Rahim Chowdhury',   'Oncologist',             5, 'MBBS, MD (Oncology), MRCP',             20, 2000.00, '01711000005', 'rahim.chowdhury@hospital.bd', 'Expert in chemotherapy, targeted therapy and palliative cancer care.'),
('Dr. Shahida Islam',     'Gastroenterologist',     6, 'MBBS, MD (Gastroenterology)',            9,  1300.00, '01711000006', 'shahida.islam@hospital.bd',   'Specializes in IBS, liver diseases, colonoscopy and endoscopy procedures.'),
('Dr. Mizanur Rahman',    'Dermatologist',          7, 'MBBS, DDV, MD (Dermatology)',            7,  1100.00, '01711000007', 'mizanur.rahman@hospital.bd',  'Treats acne, eczema, psoriasis, and performs cosmetic dermatology procedures.'),
('Dr. Tahmina Akter',     'Emergency Physician',    8, 'MBBS, FCPS (Emergency Medicine)',        11, 800.00,  '01711000008', 'tahmina.akter@hospital.bd',   'Round-the-clock emergency and trauma care specialist.'),
('Dr. Jahangir Alam',     'Cardiologist',           1, 'MBBS, MD (Cardiology)',                  8,  1400.00, '01711000009', 'jahangir.alam@hospital.bd',   'Focuses on echocardiography, cardiac catheterization and preventive cardiology.'),
('Dr. Rubina Khanam',     'Neurologist',            2, 'MBBS, MD (Neurology), DM',               14, 1500.00, '01711000010', 'rubina.khanam@hospital.bd',   'Specialist in headache disorders, dementia and neuro-oncology.');

-- ─────────────────────────────────────────
-- Update department heads
-- ─────────────────────────────────────────
UPDATE departments SET head_doctor_id = 1  WHERE department_id = 1;  -- Cardiology → Dr. Arif
UPDATE departments SET head_doctor_id = 2  WHERE department_id = 2;  -- Neurology → Dr. Nasrin
UPDATE departments SET head_doctor_id = 3  WHERE department_id = 3;  -- Orthopedics → Dr. Kamal
UPDATE departments SET head_doctor_id = 4  WHERE department_id = 4;  -- Pediatrics → Dr. Fatema
UPDATE departments SET head_doctor_id = 5  WHERE department_id = 5;  -- Oncology → Dr. Rahim
UPDATE departments SET head_doctor_id = 6  WHERE department_id = 6;  -- Gastro → Dr. Shahida
UPDATE departments SET head_doctor_id = 7  WHERE department_id = 7;  -- Derma → Dr. Mizanur
UPDATE departments SET head_doctor_id = 8  WHERE department_id = 8;  -- Emergency → Dr. Tahmina

-- ─────────────────────────────────────────
-- 3. DOCTOR SCHEDULES
-- ─────────────────────────────────────────
INSERT INTO doctor_schedules (doctor_id, day_of_week, start_time, end_time, slot_duration_min, max_appointments) VALUES
-- Dr. Arif Hossain (Cardiologist)
(1, 'Sunday',    '09:00:00', '13:00:00', 20, 12),
(1, 'Tuesday',   '09:00:00', '13:00:00', 20, 12),
(1, 'Thursday',  '14:00:00', '18:00:00', 20, 12),
-- Dr. Nasrin Sultana (Neurologist)
(2, 'Monday',    '10:00:00', '14:00:00', 20, 12),
(2, 'Wednesday', '10:00:00', '14:00:00', 20, 12),
(2, 'Saturday',  '09:00:00', '12:00:00', 20, 9),
-- Dr. Kamal Uddin (Orthopedics)
(3, 'Sunday',    '14:00:00', '18:00:00', 20, 12),
(3, 'Tuesday',   '14:00:00', '18:00:00', 20, 12),
(3, 'Thursday',  '09:00:00', '13:00:00', 20, 12),
-- Dr. Fatema Begum (Pediatrics)
(4, 'Monday',    '09:00:00', '13:00:00', 20, 12),
(4, 'Wednesday', '09:00:00', '13:00:00', 20, 12),
(4, 'Friday',    '09:00:00', '12:00:00', 20, 9),
-- Dr. Rahim Chowdhury (Oncology)
(5, 'Sunday',    '10:00:00', '15:00:00', 30, 10),
(5, 'Wednesday', '10:00:00', '15:00:00', 30, 10),
-- Dr. Shahida Islam (Gastroenterology)
(6, 'Monday',    '14:00:00', '18:00:00', 20, 12),
(6, 'Thursday',  '14:00:00', '18:00:00', 20, 12),
(6, 'Saturday',  '10:00:00', '13:00:00', 20, 9),
-- Dr. Mizanur Rahman (Dermatology)
(7, 'Tuesday',   '10:00:00', '14:00:00', 15, 16),
(7, 'Friday',    '10:00:00', '14:00:00', 15, 16),
-- Dr. Tahmina Akter (Emergency — always on)
(8, 'Monday',    '00:00:00', '23:59:00', 20, 50),
(8, 'Tuesday',   '00:00:00', '23:59:00', 20, 50),
(8, 'Wednesday', '00:00:00', '23:59:00', 20, 50),
(8, 'Thursday',  '00:00:00', '23:59:00', 20, 50),
(8, 'Friday',    '00:00:00', '23:59:00', 20, 50),
(8, 'Saturday',  '00:00:00', '23:59:00', 20, 50),
(8, 'Sunday',    '00:00:00', '23:59:00', 20, 50),
-- Dr. Jahangir Alam (Cardiologist)
(9, 'Monday',    '09:00:00', '13:00:00', 20, 12),
(9, 'Wednesday', '14:00:00', '18:00:00', 20, 12),
(9, 'Friday',    '09:00:00', '12:00:00', 20, 9),
-- Dr. Rubina Khanam (Neurologist)
(10, 'Tuesday',  '14:00:00', '18:00:00', 20, 12),
(10, 'Thursday', '09:00:00', '13:00:00', 20, 12),
(10, 'Saturday', '14:00:00', '17:00:00', 20, 9);

-- ─────────────────────────────────────────
-- 4. PATIENTS
-- ─────────────────────────────────────────
INSERT INTO patients (patient_id, full_name, date_of_birth, gender, blood_group, phone, email, address, emergency_contact, insurance_id, insurance_provider) VALUES
('P-2024-00001', 'Md. Rafiqul Islam',     '1985-03-15', 'Male',   'B+',  '01811100001', 'rafiq@email.com',   'House 12, Road 5, Dhanmondi, Dhaka',        '01811100099', 'INS-0001', 'Green Life Insurance'),
('P-2024-00002', 'Sadia Akter',           '1992-07-22', 'Female', 'A+',  '01811100002', 'sadia@email.com',   'Flat 3B, Mirpur-10, Dhaka',                 '01811100098', 'INS-0002', 'Delta Life Insurance'),
('P-2024-00003', 'Karim Mia',             '1970-11-05', 'Male',   'O+',  '01811100003', 'karim@email.com',   'Village: Madhabpur, Habiganj, Sylhet',       '01811100097', NULL,       NULL),
('P-2024-00004', 'Nusrat Jahan',          '2000-01-30', 'Female', 'AB+', '01811100004', 'nusrat@email.com',  'Apt 5A, Uttara Sector 11, Dhaka',            '01811100096', 'INS-0004', 'Pragati Life Insurance'),
('P-2024-00005', 'Aminul Haque',          '1955-09-12', 'Male',   'A-',  '01811100005', 'aminul@email.com',  'House 7, Khilgaon, Dhaka',                  '01811100095', 'INS-0005', 'National Life Insurance'),
('P-2024-00006', 'Tahera Khanam',         '1988-04-18', 'Female', 'B-',  '01811100006', 'tahera@email.com',  'Road 2, Block D, Bashundhara R/A, Dhaka',   '01811100094', NULL,       NULL),
('P-2024-00007', 'Sabbir Ahmed',          '2015-06-25', 'Male',   'O-',  '01811100007', 'sabbir@email.com',  'Holding 22, Banani, Dhaka',                 '01811100093', 'INS-0007', 'MetLife Bangladesh'),
('P-2024-00008', 'Rokeya Begum',          '1960-12-10', 'Female', 'O+',  '01811100008', 'rokeya@email.com',  'Gulshan-2, Dhaka',                          '01811100092', 'INS-0008', 'Sunlife Insurance'),
('P-2024-00009', 'Tanvir Hossain',        '1998-08-03', 'Male',   'B+',  '01811100009', 'tanvir@email.com',  'Rajshahi City, Ward 14',                    '01811100091', NULL,       NULL),
('P-2024-00010', 'Morjina Akter',         '2010-02-14', 'Female', 'A+',  '01811100010', 'morjina@email.com', 'Village: Barishal Sadar, Barishal',         '01811100090', 'INS-0010', 'Popular Life Insurance');

-- ─────────────────────────────────────────
-- 5. APPOINTMENTS
-- ─────────────────────────────────────────
INSERT INTO appointments (appointment_id, patient_id, doctor_id, scheduled_at, duration_min, status, reason_for_visit, booked_via) VALUES
('APT-20241101-0001', 'P-2024-00001', 1,  '2025-07-06 09:00:00', 20, 'confirmed',  'Chest discomfort and shortness of breath',     'ai_agent'),
('APT-20241101-0002', 'P-2024-00002', 2,  '2025-07-07 10:00:00', 20, 'confirmed',  'Recurring severe headaches',                   'web'),
('APT-20241101-0003', 'P-2024-00003', 3,  '2025-07-06 14:00:00', 20, 'pending',    'Knee pain after sports injury',                'ai_agent'),
('APT-20241101-0004', 'P-2024-00004', 4,  '2025-07-07 09:00:00', 20, 'confirmed',  'Routine pediatric checkup',                    'phone'),
('APT-20241101-0005', 'P-2024-00005', 5,  '2025-07-09 10:00:00', 30, 'confirmed',  'Follow-up for chemotherapy plan',              'web'),
('APT-20241101-0006', 'P-2024-00006', 6,  '2025-07-07 14:00:00', 20, 'pending',    'Persistent stomach pain and bloating',         'ai_agent'),
('APT-20241101-0007', 'P-2024-00007', 7,  '2025-07-08 10:00:00', 15, 'confirmed',  'Skin rash and itching',                        'ai_agent'),
('APT-20241101-0008', 'P-2024-00008', 1,  '2025-07-08 09:00:00', 20, 'pending',    'Hypertension management review',               'walk_in'),
('APT-20241101-0009', 'P-2024-00009', 9,  '2025-07-07 09:00:00', 20, 'confirmed',  'Heart palpitations',                           'ai_agent'),
('APT-20241101-0010', 'P-2024-00010', 4,  '2025-07-07 09:20:00', 20, 'confirmed',  'Child fever and cough for 5 days',             'ai_agent'),
-- Completed appointments (past visits)
('APT-20241101-0011', 'P-2024-00001', 1,  '2025-06-01 09:00:00', 20, 'completed',  'Annual cardiac checkup',                       'web'),
('APT-20241101-0012', 'P-2024-00002', 2,  '2025-06-04 10:00:00', 20, 'completed',  'Migraine consultation',                        'ai_agent'),
('APT-20241101-0013', 'P-2024-00003', 3,  '2025-05-20 14:00:00', 20, 'completed',  'Post-operative follow-up',                     'phone'),
('APT-20241101-0014', 'P-2024-00005', 5,  '2025-05-14 10:00:00', 30, 'completed',  'Cancer screening results review',              'web'),
-- Cancelled appointment
('APT-20241101-0015', 'P-2024-00006', 6,  '2025-06-12 14:00:00', 20, 'cancelled',  'Acid reflux consultation',                     'ai_agent');

UPDATE appointments
SET cancelled_at = '2025-06-11 09:30:00', cancellation_reason = 'Patient could not attend due to travel'
WHERE appointment_id = 'APT-20241101-0015';

-- ─────────────────────────────────────────
-- 6. MEDICAL RECORDS
-- ─────────────────────────────────────────
INSERT INTO medical_records (patient_id, appointment_id, doctor_id, visit_date, chief_complaint, diagnosis, treatment_plan, follow_up_date) VALUES
('P-2024-00001', 'APT-20241101-0011', 1, '2025-06-01', 'Routine cardiac checkup',       'Mild hypertension, stable',                    'Continue Amlodipine 5mg. Lifestyle modification advised. Low-sodium diet.',             '2025-09-01'),
('P-2024-00002', 'APT-20241101-0012', 2, '2025-06-04', 'Recurring migraines',           'Chronic migraine without aura',                'Sumatriptan 50mg for acute attacks. Propranolol 40mg prophylaxis. Avoid triggers.',      '2025-08-04'),
('P-2024-00003', 'APT-20241101-0013', 3, '2025-05-20', 'Post knee surgery follow-up',  'Right knee ACL repair — healing well',         'Continue physiotherapy 3x/week. Avoid high-impact activity for 8 weeks.',               '2025-07-20'),
('P-2024-00005', 'APT-20241101-0014', 5, '2025-05-14', 'Cancer screening review',      'Stage II colorectal carcinoma',                'Initiate FOLFOX chemotherapy protocol. Review after 2 cycles.',                        '2025-07-09'),
('P-2024-00008', NULL,                1, '2025-04-10', 'Hypertension management',       'Uncontrolled hypertension (BP: 160/100)',      'Increase Amlodipine to 10mg. Add Losartan 50mg. Weekly BP monitoring.',                 '2025-05-10');

-- ─────────────────────────────────────────
-- 7. LAB RESULTS
-- ─────────────────────────────────────────
INSERT INTO lab_results (patient_id, test_name, test_date, result_value, unit, reference_range, is_abnormal, ordered_by_doctor, notes) VALUES
('P-2024-00001', 'Lipid Profile — Total Cholesterol', '2025-06-01', '215',  'mg/dL',   '< 200',         TRUE,  1, 'Borderline high. Dietary changes recommended.'),
('P-2024-00001', 'Fasting Blood Glucose',             '2025-06-01', '98',   'mg/dL',   '70 - 100',      FALSE, 1, 'Normal.'),
('P-2024-00001', 'ECG',                               '2025-06-01', 'Normal sinus rhythm, no ST changes', '', 'Normal', FALSE, 1, NULL),
('P-2024-00002', 'MRI Brain',                         '2025-06-05', 'No structural abnormality detected. No acute infarct.', '', 'Normal', FALSE, 2, 'Scan done at Radiology, Floor 1.'),
('P-2024-00003', 'Knee MRI',                          '2025-05-18', 'ACL graft intact. No re-tear. Mild effusion present.', '', 'Post-surgical normal', FALSE, 3, NULL),
('P-2024-00005', 'CEA Tumor Marker',                  '2025-05-12', '28.4', 'ng/mL',   '< 5.0',         TRUE,  5, 'Elevated. Consistent with active colorectal malignancy.'),
('P-2024-00005', 'CBC — Hemoglobin',                  '2025-05-12', '10.2', 'g/dL',    '13.5 - 17.5',   TRUE,  5, 'Mild anemia. Monitor during chemotherapy.'),
('P-2024-00008', 'Blood Pressure Monitoring',         '2025-04-10', '160/100', 'mmHg', '< 120/80',      TRUE,  1, 'Hypertensive. Medication adjustment initiated.'),
('P-2024-00009', 'Holter Monitor (24hr)',              '2025-05-28', 'Occasional PACs noted. No sustained arrhythmia.', '', 'Normal sinus rhythm', FALSE, 9, NULL),
('P-2024-00010', 'CBC — Total WBC',                   '2025-06-10', '12500','cells/µL','4500 - 11000',  TRUE,  4, 'Elevated WBC suggesting bacterial infection.');

-- ─────────────────────────────────────────
-- 8. PRESCRIPTIONS
-- ─────────────────────────────────────────
INSERT INTO prescriptions (patient_id, doctor_id, prescribed_date, medication_name, dosage, frequency, duration_days, is_active, notes) VALUES
('P-2024-00001', 1, '2025-06-01', 'Amlodipine',     '5mg',    'Once daily (morning)',      90,  TRUE,  'For blood pressure control. Monitor BP weekly.'),
('P-2024-00001', 1, '2025-06-01', 'Atorvastatin',   '10mg',   'Once daily (night)',        90,  TRUE,  'For high cholesterol. Avoid grapefruit juice.'),
('P-2024-00002', 2, '2025-06-04', 'Sumatriptan',    '50mg',   'As needed for migraine',    30,  TRUE,  'Do not take more than 2 doses in 24 hours.'),
('P-2024-00002', 2, '2025-06-04', 'Propranolol',    '40mg',   'Twice daily',               60,  TRUE,  'Migraine prophylaxis. Do not stop abruptly.'),
('P-2024-00005', 5, '2025-05-14', 'Ondansetron',    '8mg',    'Before chemotherapy',       7,   TRUE,  'Anti-nausea for chemo sessions.'),
('P-2024-00005', 5, '2025-05-14', 'Ferrous Sulfate', '200mg', 'Once daily with food',      60,  TRUE,  'For anemia correction.'),
('P-2024-00008', 1, '2025-04-10', 'Amlodipine',     '10mg',   'Once daily (morning)',      90,  TRUE,  'Increased dose for uncontrolled BP.'),
('P-2024-00008', 1, '2025-04-10', 'Losartan',       '50mg',   'Once daily',                90,  TRUE,  'ARB for hypertension. Monitor kidney function.'),
('P-2024-00010', 4, '2025-06-10', 'Amoxicillin',    '250mg',  'Three times daily',         7,   TRUE,  'Antibiotic for bacterial respiratory infection. Full course mandatory.'),
('P-2024-00010', 4, '2025-06-10', 'Paracetamol Syrup', '5ml', 'Every 6 hours if fever',   5,   TRUE,  'For fever management in child.');

-- ─────────────────────────────────────────
-- 9. BILLING INVOICES
-- ─────────────────────────────────────────
INSERT INTO billing_invoices (invoice_id, patient_id, appointment_id, total_amount, paid_amount, status, due_date) VALUES
('INV-20241101-0001', 'P-2024-00001', 'APT-20241101-0011', 3200.00, 3200.00, 'paid',    '2025-06-15'),
('INV-20241101-0002', 'P-2024-00002', 'APT-20241101-0012', 2600.00, 2600.00, 'paid',    '2025-06-20'),
('INV-20241101-0003', 'P-2024-00003', 'APT-20241101-0013', 1600.00, 800.00,  'partial', '2025-07-20'),
('INV-20241101-0004', 'P-2024-00005', 'APT-20241101-0014', 5500.00, 0.00,    'unpaid',  '2025-07-15'),
('INV-20241101-0005', 'P-2024-00008', NULL,                 1200.00, 1200.00, 'paid',    '2025-05-10'),
-- Active/upcoming invoices
('INV-20241101-0006', 'P-2024-00001', 'APT-20241101-0001', 1500.00, 0.00,    'unpaid',  '2025-07-20'),
('INV-20241101-0007', 'P-2024-00005', 'APT-20241101-0005', 2500.00, 0.00,    'unpaid',  '2025-07-25');

-- ─────────────────────────────────────────
-- 10. INVOICE ITEMS
-- ─────────────────────────────────────────
INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total_price) VALUES
('INV-20241101-0001', 'Consultation Fee — Dr. Arif Hossain',   1, 1500.00, 1500.00),
('INV-20241101-0001', 'Lipid Profile Test',                     1,  800.00,  800.00),
('INV-20241101-0001', 'Fasting Blood Glucose Test',             1,  300.00,  300.00),
('INV-20241101-0001', 'ECG',                                    1,  600.00,  600.00),

('INV-20241101-0002', 'Consultation Fee — Dr. Nasrin Sultana',  1, 1400.00, 1400.00),
('INV-20241101-0002', 'MRI Brain (with contrast)',              1, 1200.00, 1200.00),

('INV-20241101-0003', 'Consultation Fee — Dr. Kamal Uddin',     1, 1600.00, 1600.00),

('INV-20241101-0004', 'Consultation Fee — Dr. Rahim Chowdhury', 1, 2000.00, 2000.00),
('INV-20241101-0004', 'CEA Tumor Marker Test',                  1, 1500.00, 1500.00),
('INV-20241101-0004', 'Complete Blood Count (CBC)',             1,  500.00,  500.00),
('INV-20241101-0004', 'Oncology Nursing Care',                  1, 1500.00, 1500.00),

('INV-20241101-0005', 'Consultation Fee — Dr. Arif Hossain',   1, 1200.00, 1200.00),

('INV-20241101-0006', 'Consultation Fee — Dr. Arif Hossain',   1, 1500.00, 1500.00),
('INV-20241101-0007', 'Consultation Fee — Dr. Rahim Chowdhury',1, 2000.00, 2000.00),
('INV-20241101-0007', 'FOLFOX Chemotherapy Administration',     1,  500.00,  500.00);

-- ─────────────────────────────────────────
-- 11. MEDICATIONS (reference data)
-- ─────────────────────────────────────────
INSERT INTO medications (generic_name, brand_names, drug_class, common_uses, side_effects, contraindications, general_dosage, requires_prescription) VALUES
('Amlodipine',       'Norvasc, Amodip',          'Calcium Channel Blocker',  'Hypertension, angina',                             'Ankle swelling, flushing, headache, palpitations',    'Severe aortic stenosis, cardiogenic shock',                   'Adults: 5–10mg once daily',                 TRUE),
('Atorvastatin',     'Lipitor, Storvas',          'Statin',                   'High cholesterol, cardiovascular prevention',       'Muscle pain, liver enzyme elevation, headache',       'Active liver disease, pregnancy',                             'Adults: 10–80mg once daily at night',       TRUE),
('Metformin',        'Glucophage, Obimet',        'Biguanide',                'Type 2 diabetes mellitus',                         'Nausea, diarrhea, stomach upset (usually transient)', 'Renal impairment (eGFR<30), liver disease',                   'Adults: 500mg–2000mg/day in divided doses', TRUE),
('Sumatriptan',      'Imitrex, Suminat',          'Triptan (5-HT1 agonist)', 'Acute migraine, cluster headache',                 'Tingling, flushing, dizziness, chest tightness',     'Ischemic heart disease, uncontrolled hypertension, stroke',   '50–100mg oral at migraine onset',           TRUE),
('Propranolol',      'Inderal, Ciplar',           'Beta Blocker',             'Hypertension, migraine prophylaxis, tremor, angina','Bradycardia, fatigue, cold extremities, depression',  'Asthma, COPD, heart block',                                   'Adults: 40–160mg/day in divided doses',     TRUE),
('Amoxicillin',      'Moxil, Cipmox',             'Penicillin Antibiotic',    'Bacterial infections (respiratory, urinary, skin)', 'Nausea, diarrhea, rash, allergic reaction',           'Penicillin allergy',                                          'Adults: 250–500mg every 8 hours',           TRUE),
('Paracetamol',      'Napa, Ace, Tylenol',        'Analgesic/Antipyretic',    'Fever, mild to moderate pain',                     'Rare at normal doses; overdose causes liver damage',  'Severe liver disease',                                        'Adults: 500mg–1g every 4–6 hours (max 4g/day)', FALSE),
('Omeprazole',       'Losec, Omidon',             'Proton Pump Inhibitor',    'Acid reflux, GERD, peptic ulcer, H. pylori',        'Headache, nausea, diarrhea, hypomagnesemia (long-term)','Severe liver disease',                                        'Adults: 20–40mg once daily before meals',   TRUE),
('Losartan',         'Cozaar, Cosart',            'ARB (Angiotensin Blocker)','Hypertension, diabetic nephropathy, heart failure',  'Dizziness, hyperkalemia, renal impairment',           'Pregnancy, bilateral renal artery stenosis, hyperkalemia',    'Adults: 50–100mg once daily',               TRUE),
('Ondansetron',      'Zofran, Emeset',            'Serotonin Antagonist',     'Nausea and vomiting (chemo, post-op, pregnancy)',   'Headache, constipation, QT prolongation',             'Congenital QT prolongation',                                  'Adults: 8mg every 8 hours',                 TRUE),
('Ferrous Sulfate',  'Fefol, Fertab',             'Iron Supplement',          'Iron deficiency anemia',                           'Constipation, dark stools, nausea, stomach cramps',   'Hemochromatosis, hemosiderosis',                              'Adults: 200mg once or twice daily with food', FALSE),
('Cetirizine',       'Zyrtec, Alatrol',           'Antihistamine (H1)',        'Allergic rhinitis, urticaria, hay fever',           'Drowsiness, dry mouth, dizziness',                    'End-stage renal disease',                                     'Adults: 10mg once daily',                   FALSE);

-- ─────────────────────────────────────────
-- 12. DRUG INTERACTIONS (reference data)
-- ─────────────────────────────────────────
INSERT INTO drug_interactions (drug_a, drug_b, severity, description) VALUES
('Amlodipine',   'Simvastatin',     'moderate',        'Amlodipine increases simvastatin plasma levels, raising risk of myopathy. Limit simvastatin to 20mg/day.'),
('Propranolol',  'Amlodipine',      'moderate',        'Combination may cause excessive bradycardia and hypotension. Monitor heart rate and BP closely.'),
('Metformin',    'Alcohol',         'moderate',        'Increases risk of lactic acidosis. Advise patients to avoid alcohol during metformin therapy.'),
('Sumatriptan',  'MAO Inhibitors',  'contraindicated', 'Concurrent use causes severe serotonin syndrome. Absolute contraindication.'),
('Losartan',     'Potassium Supplements', 'moderate',  'Both raise serum potassium. Risk of dangerous hyperkalemia. Monitor potassium levels regularly.'),
('Warfarin',     'Amoxicillin',     'moderate',        'Antibiotics may alter gut flora, increasing warfarin effect and bleeding risk. Monitor INR.'),
('Ondansetron',  'Tramadol',        'severe',          'Additive QT prolongation risk. May also reduce tramadol efficacy via serotonin pathway competition.'),
('Atorvastatin', 'Clarithromycin',  'severe',          'CYP3A4 inhibition by clarithromycin dramatically raises atorvastatin levels, increasing myopathy risk.'),
('Propranolol',  'Insulin',         'moderate',        'Beta blockers mask hypoglycemia symptoms (tachycardia). Careful glucose monitoring required.'),
('Omeprazole',   'Clopidogrel',     'moderate',        'Omeprazole reduces clopidogrel activation via CYP2C19 inhibition, reducing antiplatelet efficacy.');

-- ─────────────────────────────────────────
-- 13. HOSPITAL INFO (static content)
-- ─────────────────────────────────────────
INSERT INTO hospital_info (category, topic, content) VALUES
('hours',    'General OPD Hours',           'Outpatient Department (OPD) is open Saturday to Thursday, 8:00 AM to 8:00 PM. Closed on Fridays.'),
('hours',    'Emergency Department Hours',  'The Emergency Department operates 24 hours a day, 7 days a week, including all public holidays.'),
('hours',    'Lab & Radiology Hours',       'Pathology Lab and Radiology are open Saturday to Thursday, 7:00 AM to 10:00 PM. Emergency labs available 24/7.'),
('hours',    'Visiting Hours',              'General ward visiting hours: 11:00 AM – 1:00 PM and 4:00 PM – 7:00 PM. ICU visiting: 12:00 PM – 1:00 PM only, one visitor at a time.'),
('location', 'Hospital Address',            'City General Hospital, Plot 15, Road 27, Dhanmondi, Dhaka-1209, Bangladesh.'),
('location', 'Emergency Entrance',          'The emergency entrance is located on the ground floor, Wing A, facing Road 27. Open 24/7.'),
('location', 'Parking',                     'Parking is available in the basement (B1) and at the rear of the building. First 2 hours free with patient slip.'),
('location', 'Public Transport',            'Nearest bus stops: Dhanmondi 27 (50m) and Dhanmondi 15 (200m). CNG and Uber pickup/drop-off allowed at main gate.'),
('service',  'Available Services',          'Cardiology, Neurology, Orthopedics, Pediatrics, Oncology, Gastroenterology, Dermatology, Emergency Medicine, Radiology, Pathology, ICU, Dialysis, Physiotherapy, Pharmacy.'),
('service',  'ICU Beds',                    'The hospital has 20 ICU beds. Current ICU occupancy can be checked at the nursing station (Ext: 200).'),
('service',  'Ambulance Service',           'Ambulance is available 24/7. Call 01711-AMBUL (01711-262851) for emergency transport. AC and non-AC ambulances available.'),
('service',  'Pharmacy',                    'In-house pharmacy located at Ground Floor, near the main exit. Open Saturday to Thursday 8:00 AM – 10:00 PM, Friday 10:00 AM – 8:00 PM.'),
('policy',   'Appointment Cancellation',    'Appointments can be cancelled up to 2 hours before the scheduled time via the AI agent, website or by calling reception. Late cancellations may incur a 10% cancellation fee.'),
('policy',   'Insurance Accepted',          'We accept Green Life Insurance, Delta Life Insurance, MetLife Bangladesh, National Life Insurance, Pragati Life Insurance, Sunlife Insurance, Popular Life Insurance, and most government employee insurance schemes.'),
('policy',   'Patient Rights',              'All patients have the right to respectful care, confidentiality, access to their own medical records, informed consent before any procedure, and the right to refuse treatment.'),
('policy',   'Medical Records Access',      'Patients can request their medical records by submitting a written request at the Medical Records Office (Floor 1, Room 105) with valid photo ID. Records ready within 3 working days.'),
('policy',   'Payment Methods',             'Accepted payment methods: Cash, bKash, Nagad, Rocket, Visa/Mastercard, and direct insurance billing. Installment facility available for bills above 20,000 BDT.'),
('contact',  'Main Reception',              'Dial 02-9876543 or 01700-HOSPITAL (01700-4677825) for general inquiries and appointment booking.'),
('contact',  'Emergency Hotline',           'For medical emergencies, call 01711-EMER (01711-3637) or come directly to Emergency, Ground Floor, Wing A.'),
('contact',  'Feedback & Complaints',       'Submit feedback online via the hospital portal, speak to the Patient Relations Officer (Floor 1, Room 108, Mon–Thu 9AM–5PM), or use our AI chat agent.');

-- ─────────────────────────────────────────
-- 14. FEEDBACK
-- ─────────────────────────────────────────
INSERT INTO feedback (patient_id, category, message, rating) VALUES
('P-2024-00001', 'doctor',      'Dr. Arif Hossain was extremely thorough and explained everything clearly. Very happy with the consultation.',                   5),
('P-2024-00002', 'ai_agent',    'The AI booking system was very easy to use. Got my appointment confirmed within minutes. Great experience!',                     5),
('P-2024-00003', 'facilities',  'Waiting area chairs are quite uncomfortable. The hospital is clean overall but seating needs improvement.',                     3),
('P-2024-00004', 'staff',       'The nurses at pediatrics ward were very gentle and patient with my child. Made a stressful visit much easier.',                 5),
('P-2024-00006', 'billing',     'The billing process took longer than expected. Staff were helpful once we got to them but the queue was very long.',            3),
('P-2024-00007', 'general',     'Overall a good hospital. Would appreciate if there was a dedicated children''s play area in the waiting room.',                 4),
(NULL,           'ai_agent',    'The chatbot gave me wrong information about visiting hours. It said 10 AM but the actual time was different at the front desk.', 2),
('P-2024-00009', 'doctor',      'Dr. Jahangir Alam was very professional and took time to explain my heart condition in simple terms. Highly recommend.',         5),
('P-2024-00008', 'facilities',  'Wheelchair access from the parking area to the elevator could be improved. Had difficulty navigating with my elderly mother.',   2),
('P-2024-00005', 'doctor',      'Dr. Rahim Chowdhury has been very compassionate throughout my treatment journey. I feel well cared for.',                       5);

-- ─────────────────────────────────────────
-- 15. COMPLAINT TICKETS
-- ─────────────────────────────────────────
INSERT INTO complaint_tickets (ticket_id, patient_id, department, description, status, priority, assigned_to, resolution_note) VALUES
('TKT-20241101-0001', 'P-2024-00006', 'Billing',     'Was charged for a test that was not performed. Invoice INV-20241101-0003 shows an extra pathology charge.',         'in_review',  'high',   'Mr. Jabbar (Billing Manager)', NULL),
('TKT-20241101-0002', 'P-2024-00008', 'Facilities',  'Wheelchair ramp from parking B1 to elevator is too steep and unsafe for elderly patients.',                          'open',       'medium', NULL,                          NULL),
('TKT-20241101-0003', NULL,           'AI Agent',     'AI agent provided incorrect OPD hours (stated 10 AM but OPD opens at 8 AM). Needs correction in the knowledge base.', 'resolved',   'high',   'IT Support Team',             'Hospital info table updated. AI agent re-tested and verified correct hours. Resolved 2025-06-02.'),
('TKT-20241101-0004', 'P-2024-00003', 'Orthopedics',  'Long waiting time despite having a confirmed appointment. Waited 90 minutes past scheduled time.',                   'in_review',  'medium', 'Dr. Kamal Uddin',             NULL);

UPDATE complaint_tickets SET resolved_at = '2025-06-02 14:00:00' WHERE ticket_id = 'TKT-20241101-0003';

-- ─────────────────────────────────────────
-- 16. AUDIT LOG
-- ─────────────────────────────────────────
INSERT INTO audit_log (session_id, patient_id, agent_name, action, resource_type, resource_id, payload_summary, ip_address) VALUES
('sess-abc-001', 'P-2024-00001', 'booking_agent',    'create_appointment',  'appointment', 'APT-20241101-0001', 'Booked cardiology appointment for patient P-2024-00001 with Dr. Arif on 2025-07-06',           '192.168.1.10'),
('sess-abc-002', 'P-2024-00002', 'booking_agent',    'create_appointment',  'appointment', 'APT-20241101-0002', 'Booked neurology appointment for patient P-2024-00002 with Dr. Nasrin on 2025-07-07',          '192.168.1.11'),
('sess-abc-003', 'P-2024-00001', 'records_agent',    'read_records',        'lab_result',  'result_id:1',      'Patient P-2024-00001 accessed lipid profile result',                                            '192.168.1.10'),
('sess-abc-004', 'P-2024-00006', 'cancel_agent',     'cancel_appointment',  'appointment', 'APT-20241101-0015', 'Patient P-2024-00006 cancelled gastro appointment APT-20241101-0015',                          '192.168.1.14'),
('sess-abc-005', 'P-2024-00005', 'records_agent',    'read_records',        'prescription','prescription:5',   'Patient P-2024-00005 accessed active prescription list',                                         '192.168.1.13'),
('sess-emg-001', 'P-2024-00009', 'emergency_agent',  'emergency_triggered', 'session',     'sess-emg-001',     'Emergency keywords detected: chest pain, shortness of breath. Emergency contacts surfaced.',    '192.168.1.17'),
('sess-abc-006', 'P-2024-00008', 'booking_agent',    'create_appointment',  'appointment', 'APT-20241101-0008', 'Walk-in appointment created for patient P-2024-00008 with Dr. Arif Hossain',                   '192.168.1.16'),
('sess-abc-007', 'P-2024-00003', 'billing_agent',    'read_records',        'invoice',     'INV-20241101-0003', 'Patient P-2024-00003 queried outstanding invoice details',                                      '192.168.1.12');

-- ─────────────────────────────────────────
-- 17. CONVERSATION SESSIONS
-- ─────────────────────────────────────────
INSERT INTO conversation_sessions (session_id, patient_id, started_at, last_active_at, channel, is_active, metadata) VALUES
('sess-abc-001', 'P-2024-00001', '2025-06-20 10:00:00', '2025-06-20 10:15:00', 'web',       FALSE, '{"device": "desktop", "browser": "Chrome", "language": "en"}'),
('sess-abc-002', 'P-2024-00002', '2025-06-21 14:30:00', '2025-06-21 14:45:00', 'web',       FALSE, '{"device": "mobile", "browser": "Safari", "language": "en"}'),
('sess-abc-003', 'P-2024-00001', '2025-06-25 09:00:00', '2025-06-25 09:20:00', 'web',       FALSE, '{"device": "desktop", "browser": "Firefox", "language": "en"}'),
('sess-abc-004', 'P-2024-00006', '2025-06-11 08:55:00', '2025-06-11 09:05:00', 'whatsapp',  FALSE, '{"platform": "whatsapp", "language": "bn"}'),
('sess-abc-005', 'P-2024-00005', '2025-06-28 16:00:00', '2025-06-28 16:25:00', 'web',       FALSE, '{"device": "tablet", "browser": "Chrome", "language": "en"}'),
('sess-emg-001', 'P-2024-00009', '2025-06-29 22:10:00', '2025-06-29 22:15:00', 'web',       FALSE, '{"device": "mobile", "browser": "Chrome", "language": "en", "emergency": true}'),
('sess-abc-006', 'P-2024-00008', '2025-06-30 10:00:00', '2025-06-30 10:18:00', 'kiosk',     FALSE, '{"terminal_id": "KIOSK-03", "language": "bn"}'),
('sess-abc-007', 'P-2024-00003', '2025-07-01 11:00:00', '2025-07-01 11:12:00', 'web',       FALSE, '{"device": "desktop", "browser": "Edge", "language": "en"}');

-- ─────────────────────────────────────────
-- 18. CONVERSATION MEMORY
-- ─────────────────────────────────────────
INSERT INTO conversation_memory (session_id, patient_id, role, content, agent_name) VALUES
('sess-abc-001', 'P-2024-00001', 'human',  'Hello, I need to book an appointment with a cardiologist.',                                                          'supervisor'),
('sess-abc-001', 'P-2024-00001', 'ai',     'Of course! We have two cardiologists available: Dr. Arif Hossain and Dr. Jahangir Alam. Who would you prefer?',      'booking_agent'),
('sess-abc-001', 'P-2024-00001', 'human',  'I would like to see Dr. Arif Hossain please.',                                                                       'booking_agent'),
('sess-abc-001', 'P-2024-00001', 'ai',     'Dr. Arif is available on Sunday (July 6) and Tuesday (July 8). What date works for you?',                           'booking_agent'),
('sess-abc-001', 'P-2024-00001', 'human',  'Sunday, July 6th.',                                                                                                  'booking_agent'),
('sess-abc-001', 'P-2024-00001', 'ai',     'Perfect. First available slot on July 6 is 9:00 AM. Shall I confirm this booking?',                                  'booking_agent'),
('sess-abc-001', 'P-2024-00001', 'human',  'Yes, please confirm.',                                                                                               'booking_agent'),
('sess-abc-001', 'P-2024-00001', 'ai',     'Your appointment has been confirmed! ID: APT-20241101-0001. Dr. Arif Hossain, July 6 at 9:00 AM, Cardiology Dept, Floor 3 Wing A.', 'booking_agent'),
-- Emergency session
('sess-emg-001', 'P-2024-00009', 'human',  'I have chest pain and my left arm is numb. What should I do?',                                                       'supervisor'),
('sess-emg-001', 'P-2024-00009', 'ai',     'URGENT: Please call our Emergency immediately at 01711-3637 or go directly to Emergency, Ground Floor Wing A. These symptoms require IMMEDIATE medical attention. Do not wait.', 'emergency_agent');

-- ─────────────────────────────────────────
-- 19. PATIENT LONG-TERM CONTEXT
-- ─────────────────────────────────────────
INSERT INTO patient_long_term_context (patient_id, preferred_doctor, preferred_time_slot, language_preference, communication_opt_in, last_concern) VALUES
('P-2024-00001', 1,  'morning',   'en', TRUE,  'Blood pressure management and cholesterol follow-up'),
('P-2024-00002', 2,  'afternoon', 'en', TRUE,  'Migraine frequency reduction'),
('P-2024-00003', 3,  'afternoon', 'en', TRUE,  'Post-ACL surgery recovery progress'),
('P-2024-00005', 5,  'morning',   'en', TRUE,  'Chemotherapy schedule and side effect management'),
('P-2024-00006', 6,  'afternoon', 'bn', TRUE,  'Digestive issues and pending billing dispute'),
('P-2024-00008', 1,  'morning',   'bn', FALSE, 'Hypertension monitoring'),
('P-2024-00009', 9,  'evening',   'en', TRUE,  'Cardiac palpitation follow-up');

-- ============================================================
-- Seed data insertion complete.
-- ============================================================

-- Quick verification queries (optional — run to confirm)
-- SELECT 'departments' as tbl, COUNT(*) as rows FROM departments
-- UNION ALL SELECT 'doctors',                   COUNT(*) FROM doctors
-- UNION ALL SELECT 'doctor_schedules',           COUNT(*) FROM doctor_schedules
-- UNION ALL SELECT 'patients',                   COUNT(*) FROM patients
-- UNION ALL SELECT 'appointments',               COUNT(*) FROM appointments
-- UNION ALL SELECT 'medical_records',            COUNT(*) FROM medical_records
-- UNION ALL SELECT 'lab_results',                COUNT(*) FROM lab_results
-- UNION ALL SELECT 'prescriptions',              COUNT(*) FROM prescriptions
-- UNION ALL SELECT 'billing_invoices',           COUNT(*) FROM billing_invoices
-- UNION ALL SELECT 'invoice_items',              COUNT(*) FROM invoice_items
-- UNION ALL SELECT 'medications',                COUNT(*) FROM medications
-- UNION ALL SELECT 'drug_interactions',          COUNT(*) FROM drug_interactions
-- UNION ALL SELECT 'hospital_info',              COUNT(*) FROM hospital_info
-- UNION ALL SELECT 'feedback',                   COUNT(*) FROM feedback
-- UNION ALL SELECT 'complaint_tickets',          COUNT(*) FROM complaint_tickets
-- UNION ALL SELECT 'audit_log',                  COUNT(*) FROM audit_log
-- UNION ALL SELECT 'conversation_sessions',      COUNT(*) FROM conversation_sessions
-- UNION ALL SELECT 'conversation_memory',        COUNT(*) FROM conversation_memory
-- UNION ALL SELECT 'patient_long_term_context',  COUNT(*) FROM patient_long_term_context;
