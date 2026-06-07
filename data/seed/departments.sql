USE hospital_ai;

SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE TABLE departments;
SET FOREIGN_KEY_CHECKS = 1;

INSERT INTO departments (
    department_id,
    name,
    floor_location,
    phone_extension,
    head_doctor_id,
    description,
    is_active
)
VALUES
(1, 'Emergency', 'Ground Floor, Block A', '100', NULL,
 'Round-the-clock emergency care for acute injuries and life-threatening conditions.', 1),

(2, 'Cardiology', '3rd Floor, Block B', '301', NULL,
 'Diagnosis and treatment of heart and vascular diseases. Houses cardiac ICU and cath lab.', 1),

(3, 'Neurology', '4th Floor, Block B', '401', NULL,
 'Specialises in disorders of the brain, spinal cord, and nervous system.', 1),

(4, 'Orthopedics', '2nd Floor, Block C', '201', NULL,
 'Bone, joint, muscle, and ligament conditions including surgery and rehabilitation.', 1),

(5, 'Pediatrics', '1st Floor, Block D', '110', NULL,
 'Comprehensive healthcare for infants, children, and adolescents up to 18 years.', 1),

(6, 'General Medicine', '1st Floor, Block A', '105', NULL,
 'Primary care and internal medicine for adult patients with non-surgical conditions.', 1),

(7, 'Radiology', '2nd Floor, Block A', '210', NULL,
 'Diagnostic imaging: X-ray, CT scan, MRI, ultrasound, and interventional radiology.', 1),

(8, 'Oncology', '5th Floor, Block B', '501', NULL,
 'Cancer diagnosis, chemotherapy, radiation therapy, and palliative care.', 1),

(9, 'Gynecology', '3rd Floor, Block D', '310', NULL,
 'Women''s reproductive health, obstetrics, prenatal care, and labour ward.', 1),

(10, 'Dermatology', '2nd Floor, Block D', '220', NULL,
 'Skin, hair, and nail conditions including dermatological surgery.', 1);