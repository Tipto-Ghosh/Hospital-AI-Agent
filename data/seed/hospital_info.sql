USE hospital_ai;

SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE TABLE hospital_info;
SET FOREIGN_KEY_CHECKS = 1;

INSERT INTO hospital_info (category, topic, content)
VALUES

-- HOURS
('hours', 'General OPD Hours',
 'Outpatient Department (OPD) is open Saturday to Thursday, 8:00 AM to 8:00 PM. '
 'Friday OPD operates 10:00 AM to 2:00 PM. Emergency services are available 24 hours a day, 7 days a week.'),

('hours', 'Emergency Department Hours',
 'The Emergency Department operates 24 hours a day, 365 days a year, including all public holidays. '
 'For life-threatening emergencies, call 109 or proceed directly to the Emergency entrance at Ground Floor, Block A.'),

('hours', 'ICU Visiting Hours',
 'ICU visiting hours are 8:00 AM – 10:00 AM and 4:00 PM – 6:00 PM daily. '
 'Maximum 2 visitors per patient at a time. Children under 12 are not permitted in the ICU. '
 'All visitors must obtain a visitor pass from the ICU reception desk.'),

('hours', 'General Ward Visiting Hours',
 'General ward visiting hours: 8:00 AM – 12:00 PM and 4:00 PM – 8:00 PM. '
 'Private room patients may receive visitors at any time during the day (8 AM – 9 PM). '
 'No visiting is allowed between 9:00 PM and 8:00 AM to ensure patient rest.'),

('hours', 'Laboratory Hours',
 'Clinical laboratory services are available Monday–Friday: 7:00 AM – 9:00 PM. '
 'Saturday and Sunday: 8:00 AM – 4:00 PM. '
 'Urgent lab tests are processed round-the-clock through the Emergency lab (Ground Floor).'),

('hours', 'Pharmacy Hours',
 'Hospital pharmacy is open daily 7:00 AM – 10:00 PM. '
 'An emergency pharmacy window operates 24/7 for critical medications. '
 'Located at Ground Floor, Block A, near the main entrance.'),

('hours', 'Radiology Hours',
 'Radiology (X-ray, CT, MRI, Ultrasound) is open Monday–Friday: 8:00 AM – 8:00 PM, '
 'Saturday: 8:00 AM – 4:00 PM. MRI is available by appointment only. '
 'Emergency imaging is available 24/7 through the Emergency Department.'),

('hours', 'Holiday Schedule',
 'City General Hospital maintains reduced OPD services on national public holidays. '
 'Emergency, ICU, Pharmacy, and Laboratory services remain fully operational on all holidays. '
 'Please call reception at 16700 to confirm OPD availability on specific public holidays.'),

-- LOCATION
('location', 'Hospital Address',
 'City General Hospital, Plot 12, Road 5, Mirpur-10, Dhaka-1216, Bangladesh. '
 'GPS coordinates: 23.8103° N, 90.3667° E. '
 'Nearest landmark: Mirpur-10 Metro Station (5-minute walk).'),

('location', 'Emergency Entrance',
 'The Emergency entrance is at Ground Floor, Block A, on the north side of the main building. '
 'Ambulances and emergency vehicles use the dedicated gate on Road 5 (Gate 2). '
 'A green "EMERGENCY" sign with 24-hour lighting marks the entrance.'),

('location', 'Main Entrance & Reception',
 'Main entrance and reception are at Ground Floor, Block A, facing Road 5 (Gate 1). '
 'Reception is open 8:00 AM – 10:00 PM. After hours, please use the Emergency entrance.'),

('location', 'Department Floor Map',
 'Ground Floor (Block A): Emergency, Pharmacy, Reception, Billing. '
 '1st Floor (Block A): General Medicine, Pathology/Sample Collection. '
 '1st Floor (Block D): Pediatrics. '
 '2nd Floor (Block A): Radiology (X-ray, CT, MRI, Ultrasound). '
 '2nd Floor (Block C): Orthopedics. '
 '2nd Floor (Block D): Dermatology. '
 '3rd Floor (Block B): Cardiology, Cardiac ICU. '
 '3rd Floor (Block D): Gynecology, Labour Ward. '
 '4th Floor (Block B): Neurology. '
 '5th Floor (Block B): Oncology, Chemotherapy Suite.'),

('location', 'Parking',
 'Free parking is available for patients and visitors in the basement and Lot B (east side). '
 'Capacity: 200 vehicles. Parking is available 24/7. '
 'Disabled parking bays are located on Level B1, near the lift. '
 'For extended stays (inpatients), a monthly parking permit can be obtained from Security (Ground Floor).'),

('location', 'Public Transport',
 'Metro: Mirpur-10 Metro Station (Green Line) – 5-minute walk from the hospital main gate. '
 'Bus: Routes 5, 12, 27, and 34 stop at "City General Hospital" bus stand on Road 5. '
 'CNG/Rickshaw: Available at the main gate 24/7. '
 'Ambulance transfer from other facilities: call 01711-AMBU (01711-2628).'),

-- POLICY
('policy', 'Appointment Cancellation Policy',
 'Appointments must be cancelled at least 24 hours in advance to avoid a cancellation fee. '
 'Same-day cancellations may incur a fee of 200 BDT. '
 'No-show appointments (missed without notice) are recorded and may affect future booking priority. '
 'To cancel, contact reception at 16700 or use the hospital AI assistant.'),

('policy', 'Patient Identification Policy',
 'Patients must present a valid National ID Card (NID) or Birth Certificate at registration. '
 'Foreign nationals must present a valid passport. '
 'Patient wristbands are issued at admission and must be worn throughout the stay. '
 'Accessing another patient''s records without consent is strictly prohibited.'),

('policy', 'Visitor Policy',
 'Maximum 2 visitors per patient at any time. '
 'Children under 10 are not permitted in ICU, HDU, or isolation wards. '
 'Visitors must check in at the reception desk and collect a visitor pass. '
 'Smoking and alcohol are strictly prohibited on hospital premises. '
 'Mobile phones must be on silent mode in clinical areas.'),

('policy', 'Consent & Privacy Policy',
 'All medical procedures require written informed consent from the patient or legal guardian. '
 'Patient information is strictly confidential and governed by the Patient Privacy Act. '
 'Medical records are released only to the patient, legal guardian, or authorised representative. '
 'For medical record requests, contact the Medical Records Department (1st Floor, Block A).'),

('policy', 'Refund Policy',
 'Consultation fees are non-refundable once the appointment has commenced. '
 'Lab and diagnostic fees are refundable if tests are cancelled more than 2 hours before the scheduled time. '
 'Inpatient deposit refunds are processed within 5 working days of discharge. '
 'Billing disputes must be raised within 30 days of invoice issuance.'),

-- SERVICE
('service', 'Available Medical Services',
 'City General Hospital provides: Emergency Medicine, Cardiology (including cath lab and cardiac ICU), '
 'Neurology, Orthopedics (joint replacement), Pediatrics, General Medicine, '
 'Radiology (X-ray, CT, MRI, PET-CT, Ultrasound), Oncology (chemo and radiation therapy), '
 'Gynecology and Obstetrics, Dermatology, Clinical Laboratory, Blood Bank, '
 'Physiotherapy and Rehabilitation, Dietary and Nutrition Counselling.'),

('service', 'Diagnostic Imaging Services',
 'Available imaging modalities: Digital X-ray (no appointment needed), '
 'CT Scan (appointment required, results in 2–4 hours), '
 'MRI (appointment required, results in 24 hours), '
 'Ultrasound (walk-in or appointment, results same day), '
 'Echocardiogram (via Cardiology referral). '
 'All imaging is located on the 2nd Floor, Block A.'),

('service', 'Blood Bank Services',
 'Hospital blood bank is open 24/7 and stocks all major blood groups (A, B, AB, O — positive and negative). '
 'Platelet and FFP are available with 4-hour notice. '
 'Blood donation camp is held every first Saturday of the month, 9 AM – 1 PM, Ground Floor lobby.'),

('service', 'Physiotherapy & Rehabilitation',
 'Physiotherapy is available by referral from any department. '
 'Services include post-surgical rehabilitation, stroke recovery, orthopaedic physiotherapy, '
 'and paediatric developmental therapy. '
 'Located at Ground Floor, Block C. Hours: 8 AM – 6 PM, Monday–Saturday.'),

('service', 'Telemedicine / Online Consultation',
 'Online video consultations are available for General Medicine, Dermatology, and follow-up appointments. '
 'Book via the hospital website or AI assistant. Minimum notice required: 2 hours. '
 'Telemedicine fee: 300–500 BDT depending on specialisation. '
 'Prescriptions issued via telemedicine are valid and can be filled at the hospital pharmacy.'),

-- CONTACT
('contact', 'Main Reception',
 'Main reception number: 16700 (toll-free within Bangladesh). '
 'International: +88 02-9xxxxxxx. '
 'Email: reception@cityhospital.com. '
 'Open: 8:00 AM – 10:00 PM, Saturday to Thursday. '
 'For after-hours non-emergency queries, call 01700-HOSP (01700-4677).'),

('contact', 'Emergency Contacts',
 'Hospital Emergency (24/7): 109 (direct hotline). '
 'Ambulance dispatch: 01711-AMBU (01711-2628). '
 'Police: 999. '
 'Fire Service: 199. '
 'National Emergency: 999. '
 'For cardiac arrest or stroke, call 109 immediately — do not wait for the AI assistant.'),

('contact', 'Department Phone Extensions',
 'Emergency: Ext. 100 | Cardiology: Ext. 301 | Neurology: Ext. 401 | '
 'Orthopedics: Ext. 201 | Pediatrics: Ext. 110 | General Medicine: Ext. 105 | '
 'Radiology: Ext. 210 | Oncology: Ext. 501 | Gynecology: Ext. 310 | '
 'Dermatology: Ext. 220 | Pharmacy: Ext. 102 | Laboratory: Ext. 103 | '
 'Billing: Ext. 104 | Medical Records: Ext. 106.'),

('contact', 'Billing Department',
 'Billing inquiries: Ext. 104 or billing@cityhospital.com. '
 'Billing desk hours: 8:00 AM – 6:00 PM, Saturday to Thursday. '
 'For insurance claims, contact the Insurance Desk at billing@cityhospital.com or Ext. 104. '
 'Online payment portal: pay.cityhospital.com.'),

-- INSURANCE & PAYMENT
('service', 'Accepted Insurance Plans',
 'City General Hospital accepts the following insurance providers: '
 'Green Delta Insurance, Delta Life Insurance, Pragati Life Insurance, National Life Insurance, '
 'MetLife Bangladesh, Guardian Life Insurance, Popular Life Insurance, '
 'Meghna Life Insurance, SunLife Insurance, Prime Islami Life. '
 'For corporate health schemes: contact billing@cityhospital.com with your company name and policy number. '
 'Government employee health benefits (under DGHS) are also accepted.'),

('service', 'Payment Methods',
 'City General Hospital accepts the following payment methods: '
 'Cash (BDT only) at the billing counter, '
 'Debit/Credit Card (Visa, Mastercard, American Express) at all billing points, '
 'Mobile banking: bKash, Nagad, Rocket (scan QR at billing counter), '
 'Online bank transfer to: City General Hospital, A/C 12345678901, Sonali Bank, Mirpur-10 Branch, '
 'Insurance direct billing (for enrolled plans — pre-authorisation required). '
 'Instalment plans are available for bills above 50,000 BDT — apply at the billing desk.'),

-- FAQ
('faq', 'How do I book an appointment?',
 'You can book an appointment through: '
 '1. This AI assistant (available 24/7 — just say "book an appointment"). '
 '2. Calling reception at 16700 (8 AM – 10 PM). '
 '3. The hospital website: www.cityhospital.com/appointments. '
 'Walk-in appointments are also accepted subject to doctor availability.'),

('faq', 'Can I get my test results online?',
 'Lab results are available online via the patient portal at portal.cityhospital.com '
 'within 2–24 hours of sample collection, depending on the test. '
 'For imaging results (CT, MRI), a radiologist report is added within 24 hours. '
 'You can also ask the AI assistant to check if your results are ready after authenticating your identity.'),

('faq', 'What should I bring for my first visit?',
 'For your first visit please bring: '
 'Valid National ID Card or Passport, '
 'Insurance card and policy number (if applicable), '
 'Referral letter (if referred by another doctor), '
 'Any previous medical records, test results, or imaging CDs relevant to your condition, '
 'List of current medications.'),

('faq', 'Is there a patient helpdesk?',
 'Yes. The Patient Relations Helpdesk is located at Ground Floor, Block A (near the main entrance). '
 'Hours: 8:00 AM – 8:00 PM, Saturday to Thursday. '
 'The helpdesk handles: complaint escalation, appointment issues, feedback, '
 'medical record requests, and insurance queries. '
 'You can also lodge a complaint through this AI assistant.'),

('faq', 'Does the hospital have a canteen or cafeteria?',
 'Yes. The hospital cafeteria is located at Ground Floor, Block B. '
 'Hours: 7:00 AM – 10:00 PM daily. It serves halal meals, snacks, and beverages. '
 'A coffee kiosk is also available at the Ground Floor lobby (7 AM – 9 PM). '
 'Outside food may be brought for inpatients unless dietary restrictions apply.');