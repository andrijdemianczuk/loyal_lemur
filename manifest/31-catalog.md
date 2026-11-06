# 31 — Presentation catalog

Data, not prose: copy every row exactly. Generated from the reference build
(2026-11-06). Ranges are inclusive and drawn uniformly. Weights are relative
within a CTAS level. `risk/h` is the deterioration hazard per hour while
waiting. `subtle` marks dangerous presentations that look benign at the
front desk; they are where decision support earns its keep.

## Presentations

| code | complaint | CTAS | weight | age | sex | amb. prob | risk/h | subtle | treatment min | admit prob | vitals (overrides of normal) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `L1_MAJOR_TRAUMA` | Major trauma - MVC | 1 | 3 | 18–70 | any | 1 | 1.5 |  | 180–360 | 0.95 | HR 125–150, SBP 72–88, DBP 40–55, RR 26–34, SpO2 86–92, pain 8–10, GCS 10–13 |
| `L1_RESP_FAILURE` | Severe respiratory distress | 1 | 3 | 55–90 | any | 0.9 | 1.5 |  | 180–360 | 0.9 | HR 118–140, RR 32–40, SpO2 78–86, SBP 150–185, GCS 13–14 |
| `L1_ANAPHYLAXIS` | Allergic reaction - anaphylaxis | 1 | 2 | 8–60 | any | 0.7 | 2 |  | 240–360 | 0.5 | HR 125–145, SBP 70–85, DBP 35–50, RR 26–32, SpO2 88–93 |
| `L1_STATUS_SEIZURE` | Seizure - ongoing | 1 | 1 | 5–75 | any | 1 | 2 |  | 180–300 | 0.8 | HR 120–140, SpO2 85–91, GCS 3–7, T 37.5–38.4 |
| `L2_CHEST_PAIN_CARDIAC` | Chest pain - cardiac features | 2 | 6 | 45–85 | any | 0.55 | 0.5 |  | 180–300 | 0.7 | HR 95–115, SBP 150–175, pain 7–9 |
| `L2_STROKE` | Stroke symptoms - within window | 2 | 3 | 55–90 | any | 0.8 | 0.8 |  | 180–300 | 0.85 | SBP 170–200, DBP 90–110, GCS 13–14 |
| `L2_SEPSIS` | Fever - suspected sepsis | 2 | 4 | 60–92 | any | 0.6 | 0.6 |  | 240–360 | 0.85 | HR 110–128, SBP 88–100, RR 22–28, SpO2 91–94, T 38.6–39.8, GCS 13–14 |
| `L2_OVERDOSE` | Overdose - ingestion | 2 | 3 | 16–55 | any | 0.7 | 0.5 |  | 240–480 | 0.6 | HR 98–115, RR 10–13, GCS 12–14 |
| `L2_ASTHMA` | Shortness of breath - asthma | 2 | 3 | 12–45 | any | 0.3 | 0.5 |  | 120–240 | 0.3 | HR 112–128, RR 26–32, SpO2 89–92 |
| `L2_SUICIDAL` | Suicidal ideation with plan | 2 | 2 | 16–60 | any | 0.2 | 0.15 |  | 180–360 | 0.5 | HR 80–100 |
| `L2_ATYPICAL_ACS` | Epigastric pain | 2 | 3 | 62–85 | F | 0.1 | 0.45 | yes | 180–300 | 0.7 | HR 92–104, SBP 138–152, pain 3–5 |
| `L2_SAH_HEADACHE` | Headache | 2 | 2 | 30–60 | any | 0.05 | 0.4 | yes | 180–300 | 0.6 | SBP 145–165, pain 5–7 |
| `L2_ECTOPIC` | Abdominal pain - lower | 2 | 2 | 19–38 | F | 0.05 | 0.5 | yes | 120–240 | 0.6 | HR 98–110, SBP 102–112, pain 4–6 |
| `L3_ABDO_PAIN` | Abdominal pain | 3 | 8 | 18–75 | any | 0.1 | 0.06 |  | 120–300 | 0.3 | HR 90–105, T 37.4–38.3, pain 5–7 |
| `L3_RENAL_COLIC` | Flank pain | 3 | 5 | 25–60 | any | 0.1 | 0.03 |  | 90–180 | 0.1 | HR 92–110, SBP 140–160, pain 8–10 |
| `L3_SOB_MILD` | Shortness of breath | 3 | 6 | 40–85 | any | 0.25 | 0.08 |  | 150–300 | 0.45 | HR 92–106, RR 20–24, SpO2 92–95 |
| `L3_SYNCOPE` | Syncope | 3 | 4 | 20–85 | any | 0.4 | 0.05 |  | 120–240 | 0.25 | HR 55–90 |
| `L3_FEVER_ADULT` | Fever | 3 | 5 | 18–65 | any | 0.05 | 0.04 |  | 90–180 | 0.1 | HR 95–108, T 38.3–39.2, pain 2–4 |
| `L3_VOMITING` | Vomiting and dehydration | 3 | 5 | 18–80 | any | 0.1 | 0.04 |  | 120–240 | 0.15 | HR 98–112, SBP 100–115, pain 3–5 |
| `L3_FRACTURE_HIP` | Hip injury - fall | 3 | 3 | 70–95 | any | 0.85 | 0.05 |  | 180–360 | 0.9 | HR 88–102, pain 6–8 |
| `L3_HEAD_INJURY_ANTICOAG` | Head injury - minor | 3 | 3 | 68–92 | any | 0.3 | 0.35 | yes | 150–300 | 0.4 | pain 2–4 |
| `L4_ANKLE` | Ankle injury | 4 | 8 | 12–60 | any | 0 | 0.003 |  | 45–90 | 0 | pain 4–6 |
| `L4_LACERATION` | Laceration | 4 | 7 | 5–75 | any | 0 | 0.003 |  | 40–80 | 0 | pain 3–5 |
| `L4_UTI` | Urinary symptoms | 4 | 5 | 18–70 | any | 0 | 0.008 |  | 40–90 | 0.02 | pain 2–4 |
| `L4_BACK_PAIN` | Back pain | 4 | 6 | 25–65 | any | 0.05 | 0.003 |  | 45–90 | 0.01 | pain 5–7 |
| `L4_EAR_PAIN` | Earache | 4 | 4 | 2–40 | any | 0 | 0.002 |  | 30–60 | 0 | T 37.4–38.2, pain 3–5 |
| `L5_SORE_THROAT` | Sore throat | 5 | 5 | 8–50 | any | 0 | 0.001 |  | 20–45 | 0 | pain 2–4 |
| `L5_URTI` | Cold and flu symptoms | 5 | 5 | 18–60 | any | 0 | 0.001 |  | 15–40 | 0 | normal |
| `L5_MED_REFILL` | Medication request | 5 | 3 | 30–80 | any | 0 | 0.001 |  | 15–30 | 0 | normal |
| `L5_RASH` | Rash | 5 | 3 | 5–60 | any | 0 | 0.001 |  | 15–40 | 0 | normal |

Normal vitals: HR 62–95, SBP 110–138, DBP 65–88, RR 12–18, SpO2 96–100, T 36.3–37.4, pain 0–2, GCS 15–15

Hourly arrival weights (00–23, normalise to mean 1.0): 0.55, 0.45, 0.38, 0.33, 0.3, 0.32, 0.42, 0.62, 0.9, 1.15, 1.32, 1.38, 1.35, 1.33, 1.3, 1.28, 1.27, 1.27, 1.28, 1.25, 1.15, 1, 0.85, 0.7

CTAS mix of arrivals: 1: 0.01, 2: 0.12, 3: 0.40, 4: 0.33, 5: 0.14.

## Complaint base levels (rules triager)

What a complaint lookup would suggest before vital-sign modifiers.
Deliberately not the ground truth.

| Complaint | Base CTAS |
|---|---|
| Major trauma - MVC | 2 |
| Severe respiratory distress | 2 |
| Allergic reaction - anaphylaxis | 2 |
| Seizure - ongoing | 1 |
| Chest pain - cardiac features | 2 |
| Stroke symptoms - within window | 2 |
| Fever - suspected sepsis | 3 |
| Overdose - ingestion | 2 |
| Shortness of breath - asthma | 3 |
| Suicidal ideation with plan | 2 |
| Epigastric pain | 4 |
| Headache | 4 |
| Abdominal pain - lower | 4 |
| Abdominal pain | 4 |
| Flank pain | 4 |
| Shortness of breath | 3 |
| Syncope | 3 |
| Fever | 4 |
| Vomiting and dehydration | 4 |
| Hip injury - fall | 3 |
| Head injury - minor | 4 |
| Ankle injury | 4 |
| Laceration | 4 |
| Urinary symptoms | 4 |
| Back pain | 4 |
| Earache | 4 |
| Sore throat | 5 |
| Cold and flu symptoms | 5 |
| Medication request | 5 |
| Rash | 5 |

## Triage notes and history

`{age}{sex}` is filled in, e.g. `76F`. One note and one history pair are
chosen per patient.


**`L1_MAJOR_TRAUMA`**
- note: "{age}{sex} driver, high-speed MVC with rollover, prolonged extrication. Combative, pale, diaphoretic."
- history (PMHx → meds): nil significant → none

**`L1_RESP_FAILURE`**
- note: "{age}{sex} acute on chronic SOB, tripoding, speaking single words. Accessory muscle use."
- history (PMHx → meds): COPD on home O2 → tiotropium, salbutamol; CHF, EF 25% → furosemide, bisoprolol

**`L1_ANAPHYLAXIS`**
- note: "{age}{sex} ate at restaurant, lip and tongue swelling, stridor, diffuse hives. EpiPen given by spouse x1."
- history (PMHx → meds): peanut allergy → none

**`L1_STATUS_SEIZURE`**
- note: "{age}{sex} continuous generalized seizure activity >10 min per EMS. Midazolam x1 given en route."
- history (PMHx → meds): epilepsy → levetiracetam; nil significant → none

**`L2_CHEST_PAIN_CARDIAC`**
- note: "{age}{sex} crushing retrosternal chest pain radiating to L arm x40 min, diaphoretic, nauseated."
- history (PMHx → meds): HTN, dyslipidemia → ramipril, atorvastatin; prior MI with stent 2019 → ASA, clopidogrel, metoprolol; smoker 40 pack-years → none

**`L2_STROKE`**
- note: "{age}{sex} sudden R-sided weakness and slurred speech, last seen well 50 min ago. Facial droop noted."
- history (PMHx → meds): atrial fibrillation → apixaban; HTN, T2DM → metformin, amlodipine

**`L2_SEPSIS`**
- note: "{age}{sex} from care home, confused since this AM, fever, foul-smelling urine."
- note: "{age}{sex} productive cough x3 days, rigors, now drowsy."
- history (PMHx → meds): dementia, recurrent UTI → donepezil; COPD → tiotropium; T2DM → metformin

**`L2_OVERDOSE`**
- note: "{age}{sex} found by roommate with empty pill bottles, unknown quantity acetaminophen and alcohol. Drowsy but rousable."
- history (PMHx → meds): depression → sertraline

**`L2_ASTHMA`**
- note: "{age}{sex} wheezy, unable to finish sentences, salbutamol x6 puffs at home with no relief."
- history (PMHx → meds): asthma, prior ICU admission → fluticasone/salmeterol, salbutamol

**`L2_SUICIDAL`**
- note: "{age}{sex} brought by family, states plan to overdose tonight, has access to medications."
- history (PMHx → meds): major depressive disorder → escitalopram

**`L2_ATYPICAL_ACS`**
- note: "{age}{sex} 'indigestion' since this morning, some nausea and fatigue. Thinks it was something she ate."
- note: "{age}{sex} upper abdominal discomfort x3h, feels 'off', mild SOB on exertion."
- history (PMHx → meds): T2DM x15 years, HTN → metformin, gliclazide, ramipril; T2DM, CKD stage 3 → insulin glargine, losartan

**`L2_SAH_HEADACHE`**
- note: "{age}{sex} sudden severe headache while lifting weights, 'worst of my life', onset over seconds. Now 6/10 after ibuprofen."
- history (PMHx → meds): nil significant → none; HTN, smoker → amlodipine

**`L2_ECTOPIC`**
- note: "{age}{sex} R lower abdominal cramping x6h, some spotting. LMP ~7 weeks ago. Felt lightheaded in the waiting room bathroom."
- history (PMHx → meds): nil significant → none; nil significant → prenatal vitamins

**`L3_ABDO_PAIN`**
- note: "{age}{sex} RLQ pain x18h, anorexic, vomited twice."
- note: "{age}{sex} RUQ pain after fatty meal, radiates to back, vomiting."
- history (PMHx → meds): nil significant → none; cholelithiasis → none

**`L3_RENAL_COLIC`**
- note: "{age}{sex} sudden L flank pain radiating to groin, writhing, can't get comfortable."
- history (PMHx → meds): prior kidney stone → none; nil significant → none

**`L3_SOB_MILD`**
- note: "{age}{sex} increased SOB and ankle swelling x4 days, sleeping on 3 pillows."
- note: "{age}{sex} cough and SOB x5 days, green sputum."
- history (PMHx → meds): CHF → furosemide, bisoprolol; COPD → tiotropium; HTN → amlodipine

**`L3_SYNCOPE`**
- note: "{age}{sex} passed out at church while standing, brief LOC <1 min, back to baseline now."
- history (PMHx → meds): nil significant → none; HTN → hydrochlorothiazide; atrial fibrillation → apixaban, diltiazem

**`L3_FEVER_ADULT`**
- note: "{age}{sex} fever, body aches and cough x3 days, tolerating fluids."
- history (PMHx → meds): nil significant → none

**`L3_VOMITING`**
- note: "{age}{sex} vomiting and diarrhea x2 days, unable to keep fluids down, dizzy on standing."
- history (PMHx → meds): nil significant → none

**`L3_FRACTURE_HIP`**
- note: "{age}{sex} fall at home, unable to weight bear, L leg shortened and externally rotated."
- history (PMHx → meds): osteoporosis → alendronate; HTN → amlodipine

**`L3_HEAD_INJURY_ANTICOAG`**
- note: "{age}{sex} tripped on rug, hit head on table, small scalp lac. Denies LOC. Daughter says 'a bit more forgetful today'."
- history (PMHx → meds): atrial fibrillation → rivaroxaban; mechanical mitral valve → warfarin

**`L4_ANKLE`**
- note: "{age}{sex} rolled ankle playing basketball, swelling lateral malleolus, limping but weight bearing."
- history (PMHx → meds): nil significant → none

**`L4_LACERATION`**
- note: "{age}{sex} 3 cm laceration to forearm from kitchen knife, bleeding controlled."
- history (PMHx → meds): nil significant → none

**`L4_UTI`**
- note: "{age}{sex} dysuria and frequency x2 days, no fever, no flank pain."
- history (PMHx → meds): nil significant → none

**`L4_BACK_PAIN`**
- note: "{age}{sex} lower back pain after moving furniture, no numbness or bladder/bowel changes."
- history (PMHx → meds): nil significant → none

**`L4_EAR_PAIN`**
- note: "{age}{sex} R ear pain x2 days, mild fever at home."
- history (PMHx → meds): nil significant → none

**`L5_SORE_THROAT`**
- note: "{age}{sex} sore throat x3 days, eating and drinking okay."
- history (PMHx → meds): nil significant → none

**`L5_URTI`**
- note: "{age}{sex} runny nose, congestion and cough x4 days, wants a note for work."
- history (PMHx → meds): nil significant → none

**`L5_MED_REFILL`**
- note: "{age}{sex} ran out of BP medication, family doctor away, no symptoms."
- history (PMHx → meds): HTN → amlodipine

**`L5_RASH`**
- note: "{age}{sex} itchy rash on forearms x1 week after gardening, no fever."
- history (PMHx → meds): nil significant → none

## Collision preset notes (`mvc`)

Replace the normal note for these codes during the `mvc` surge:

- `L3_HEAD_INJURY_ANTICOAG`: "{age}{sex} rear-seat passenger in a multi-vehicle collision on the highway, struck head on the side window. Small scalp laceration. Denies LOC. Says they feel 'a bit foggy'."
- `L4_BACK_PAIN`: "{age}{sex} restrained occupant in a multi-vehicle collision on the highway, rear-ended at low speed. Neck and lower back pain, ambulatory at scene, no numbness or weakness."
- `L4_LACERATION`: "{age}{sex} occupant in a multi-vehicle collision on the highway, 4 cm forearm laceration from broken glass, bleeding controlled with pressure dressing."
- `L4_ANKLE`: "{age}{sex} occupant in a multi-vehicle collision on the highway, ankle pain and swelling after foot was jammed under the pedals. Weight bearing with pain."
