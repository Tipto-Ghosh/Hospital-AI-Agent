USE hospital_ai;

SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE TABLE drug_interactions;
TRUNCATE TABLE medications;
SET FOREIGN_KEY_CHECKS = 1;

INSERT INTO medications (
    generic_name,
    brand_names,
    drug_class,
    common_uses,
    side_effects,
    contraindications,
    general_dosage,
    requires_prescription
)
VALUES

-- Cardiovascular
('metformin',
 'Glucophage, Fortamet, Glumetza',
 'Biguanide antidiabetic',
 'Type 2 diabetes management; reduces blood glucose by decreasing hepatic glucose production.',
 'Nausea, diarrhoea, abdominal discomfort, metallic taste. Rarely: lactic acidosis.',
 'Renal impairment (eGFR < 30 mL/min), hepatic failure, contrast dye procedures.',
 '500–2000 mg/day in 2–3 divided doses with meals.',
 1),

('atorvastatin',
 'Lipitor',
 'HMG-CoA reductase inhibitor (statin)',
 'High cholesterol and triglycerides; prevention of cardiovascular events.',
 'Muscle pain (myalgia), elevated liver enzymes, headache. Rare: rhabdomyolysis.',
 'Active liver disease, pregnancy, breastfeeding.',
 '10–80 mg once daily, usually at bedtime.',
 1),

('amlodipine',
 'Norvasc, Amvaz',
 'Calcium channel blocker (dihydropyridine)',
 'Hypertension, stable angina, Prinzmetal angina.',
 'Ankle oedema, flushing, palpitations, headache, fatigue.',
 'Cardiogenic shock, severe aortic stenosis.',
 '5–10 mg once daily.',
 1),

('lisinopril',
 'Zestril, Prinivil',
 'ACE inhibitor',
 'Hypertension, heart failure, diabetic nephropathy, post-MI cardioprotection.',
 'Dry cough (very common), hypotension, hyperkalaemia, angioedema (rare but serious).',
 'History of angioedema with ACE inhibitors, bilateral renal artery stenosis, pregnancy.',
 '5–40 mg once daily.',
 1),

('losartan',
 'Cozaar',
 'Angiotensin II receptor blocker (ARB)',
 'Hypertension, diabetic nephropathy, heart failure (ACE-inhibitor intolerant patients).',
 'Dizziness, hyperkalaemia, renal impairment. Rarely: angioedema.',
 'Pregnancy, bilateral renal artery stenosis.',
 '25–100 mg once or twice daily.',
 1),

-- Remaining medication rows follow the same formatting pattern...

-- DRUG INTERACTIONS
-- Columns:
-- drug_a, drug_b, severity, description

INSERT INTO drug_interactions (
    drug_a,
    drug_b,
    severity,
    description
)
VALUES

-- Contraindicated
('warfarin', 'aspirin',
 'contraindicated',
 'Concurrent use significantly increases bleeding risk. Aspirin inhibits platelet aggregation and displaces warfarin from plasma proteins, elevating INR unpredictably. Avoid combination unless under strict haematology supervision with daily INR monitoring.'),

('sertraline', 'tramadol',
 'contraindicated',
 'High risk of serotonin syndrome: symptoms include agitation, confusion, rapid heart rate, high blood pressure, dilated pupils, muscle twitching, and hyperthermia. This can be life-threatening. Do not co-administer.'),

-- Severe
('ciprofloxacin', 'warfarin',
 'severe',
 'Ciprofloxacin inhibits CYP1A2, significantly increasing warfarin plasma levels and INR. Risk of major bleeding. If combination is unavoidable, monitor INR daily and reduce warfarin dose.'),

('diazepam', 'morphine',
 'severe',
 'Combined CNS and respiratory depression. The combination can cause life-threatening respiratory failure, especially in opioid-naive patients or those with respiratory disease. Avoid concurrent use; if essential, monitor respiratory rate closely.'),

-- Moderate
('omeprazole', 'clopidogrel',
 'moderate',
 'Omeprazole inhibits CYP2C19, reducing conversion of clopidogrel to its active metabolite, potentially diminishing antiplatelet effect. Clinical significance is debated; pantoprazole is a preferred PPI alternative in patients on clopidogrel.'),

-- Mild
('paracetamol', 'warfarin',
 'mild',
 'Regular use of paracetamol (>2 g/day for >4 days) can moderately increase INR in patients on warfarin, possibly by inhibiting vitamin K-dependent clotting factor synthesis. Occasional therapeutic doses are generally safe. Monitor INR if patient uses paracetamol regularly.');