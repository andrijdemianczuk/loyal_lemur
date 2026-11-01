"""Clinical presentation catalog for synthetic ED arrivals.

Each presentation is a chief complaint (CEDIS-style wording) with a true CTAS
level, a vital-sign profile, demographics, and the narrative a triage nurse
would record. Overall CTAS mix approximates Canadian ED data: roughly
1% / 12% / 40% / 33% / 14% for levels 1-5.

``subtle`` presentations are the clinically dangerous ones that look benign
at the front desk (atypical ACS, SAH with normal vitals, anticoagulated head
injury...). Their initial vitals and wording invite under-triage; their risk
of deterioration while waiting is high. They are where decision support earns
its keep.

All of this is synthetic and simplified for demonstration; it is not
clinical guidance.
"""

from dataclasses import dataclass, field

# Time-to-physician targets per CTAS level, in minutes (CTAS guidelines).
CTAS_TARGET_MIN = {1: 0, 2: 15, 3: 30, 4: 60, 5: 120}



def effective_target_min(level: int) -> int:
    """CTAS target with a small floor so "immediate" is measurable."""
    return max(CTAS_TARGET_MIN[level], 5)


# Physician time for the initial assessment, by acuity, in minutes.
ASSESS_MIN = {1: (45, 75), 2: (30, 50), 3: (20, 40), 4: (10, 25), 5: (8, 15)}

# Walk-in SLO: arrival to physician within 4 hours.
WALK_IN_SLO_MIN = 240

# Waiting-room reassessment intervals per CTAS level, in minutes.
CTAS_REASSESS_MIN = {1: 5, 2: 15, 3: 30, 4: 60, 5: 120}

CTAS_LABEL = {
    1: "Resuscitation",
    2: "Emergent",
    3: "Urgent",
    4: "Less urgent",
    5: "Non-urgent",
}

# Share of all arrivals per true CTAS level.
CTAS_MIX = {1: 0.01, 2: 0.12, 3: 0.40, 4: 0.33, 5: 0.14}

Range = tuple[float, float]

NORMAL_VITALS: dict[str, Range] = {
    "heart_rate": (62, 95),
    "systolic_bp": (110, 138),
    "diastolic_bp": (65, 88),
    "resp_rate": (12, 18),
    "spo2": (96, 100),
    "temp_c": (36.3, 37.4),
    "pain_score": (0, 2),
    "gcs": (15, 15),
}


@dataclass(frozen=True)
class Presentation:
    code: str
    complaint: str
    ctas: int
    weight: float  # relative frequency within its CTAS level
    age: Range
    notes: tuple[str, ...]  # triage narrative; {age} and {sex} are filled in
    # (past medical history, medications) pairs, kept together for consistency.
    history: tuple[tuple[str, str], ...] = (("nil significant", "none"),)
    vitals: dict[str, Range] = field(default_factory=dict)
    sex: str | None = None  # restrict to "F" or "M"
    ambulance_prob: float = 0.1
    risk_per_hour: float = 0.01  # deterioration hazard while waiting
    subtle: bool = False
    treatment_min: Range = (60, 180)  # time in treatment once seen
    admit_prob: float = 0.1

    def vital_range(self, name: str) -> Range:
        return self.vitals.get(name, NORMAL_VITALS[name])


CATALOG: tuple[Presentation, ...] = (
    # ---- CTAS 1: Resuscitation -------------------------------------------------
    Presentation(
        "L1_MAJOR_TRAUMA", "Major trauma - MVC", 1, 3, (18, 70),
        ("{age}{sex} driver, high-speed MVC with rollover, prolonged extrication. "
         "Combative, pale, diaphoretic.",),
        vitals={"heart_rate": (125, 150), "systolic_bp": (72, 88), "diastolic_bp": (40, 55),
                "resp_rate": (26, 34), "spo2": (86, 92), "pain_score": (8, 10), "gcs": (10, 13)},
        ambulance_prob=1.0, risk_per_hour=1.5, treatment_min=(180, 360), admit_prob=0.95,
    ),
    Presentation(
        "L1_RESP_FAILURE", "Severe respiratory distress", 1, 3, (55, 90),
        ("{age}{sex} acute on chronic SOB, tripoding, speaking single words. "
         "Accessory muscle use.",),
        history=(("COPD on home O2", "tiotropium, salbutamol"),
                 ("CHF, EF 25%", "furosemide, bisoprolol")),
        vitals={"heart_rate": (118, 140), "resp_rate": (32, 40), "spo2": (78, 86),
                "systolic_bp": (150, 185), "gcs": (13, 14)},
        ambulance_prob=0.9, risk_per_hour=1.5, treatment_min=(180, 360), admit_prob=0.9,
    ),
    Presentation(
        "L1_ANAPHYLAXIS", "Allergic reaction - anaphylaxis", 1, 2, (8, 60),
        ("{age}{sex} ate at restaurant, lip and tongue swelling, stridor, "
         "diffuse hives. EpiPen given by spouse x1.",),
        history=(("peanut allergy", "none"),),
        vitals={"heart_rate": (125, 145), "systolic_bp": (70, 85), "diastolic_bp": (35, 50),
                "resp_rate": (26, 32), "spo2": (88, 93)},
        ambulance_prob=0.7, risk_per_hour=2.0, treatment_min=(240, 360), admit_prob=0.5,
    ),
    Presentation(
        "L1_STATUS_SEIZURE", "Seizure - ongoing", 1, 1, (5, 75),
        ("{age}{sex} continuous generalized seizure activity >10 min per EMS. "
         "Midazolam x1 given en route.",),
        history=(("epilepsy", "levetiracetam"), ("nil significant", "none")),
        vitals={"heart_rate": (120, 140), "spo2": (85, 91), "gcs": (3, 7), "temp_c": (37.5, 38.4)},
        ambulance_prob=1.0, risk_per_hour=2.0, treatment_min=(180, 300), admit_prob=0.8,
    ),

    # ---- CTAS 2: Emergent ------------------------------------------------------
    Presentation(
        "L2_CHEST_PAIN_CARDIAC", "Chest pain - cardiac features", 2, 6, (45, 85),
        ("{age}{sex} crushing retrosternal chest pain radiating to L arm x40 min, "
         "diaphoretic, nauseated.",),
        history=(("HTN, dyslipidemia", "ramipril, atorvastatin"),
                 ("prior MI with stent 2019", "ASA, clopidogrel, metoprolol"),
                 ("smoker 40 pack-years", "none")),
        vitals={"heart_rate": (95, 115), "systolic_bp": (150, 175), "pain_score": (7, 9)},
        ambulance_prob=0.55, risk_per_hour=0.5, treatment_min=(180, 300), admit_prob=0.7,
    ),
    Presentation(
        "L2_STROKE", "Stroke symptoms - within window", 2, 3, (55, 90),
        ("{age}{sex} sudden R-sided weakness and slurred speech, last seen well "
         "50 min ago. Facial droop noted.",),
        history=(("atrial fibrillation", "apixaban"), ("HTN, T2DM", "metformin, amlodipine")),
        vitals={"systolic_bp": (170, 200), "diastolic_bp": (90, 110), "gcs": (13, 14)},
        ambulance_prob=0.8, risk_per_hour=0.8, treatment_min=(180, 300), admit_prob=0.85,
    ),
    Presentation(
        "L2_SEPSIS", "Fever - suspected sepsis", 2, 4, (60, 92),
        ("{age}{sex} from care home, confused since this AM, fever, foul-smelling urine.",
         "{age}{sex} productive cough x3 days, rigors, now drowsy."),
        history=(("dementia, recurrent UTI", "donepezil"), ("COPD", "tiotropium"),
                 ("T2DM", "metformin")),
        vitals={"heart_rate": (110, 128), "systolic_bp": (88, 100), "resp_rate": (22, 28),
                "spo2": (91, 94), "temp_c": (38.6, 39.8), "gcs": (13, 14)},
        ambulance_prob=0.6, risk_per_hour=0.6, treatment_min=(240, 360), admit_prob=0.85,
    ),
    Presentation(
        "L2_OVERDOSE", "Overdose - ingestion", 2, 3, (16, 55),
        ("{age}{sex} found by roommate with empty pill bottles, unknown quantity "
         "acetaminophen and alcohol. Drowsy but rousable.",),
        history=(("depression", "sertraline"),),
        vitals={"heart_rate": (98, 115), "resp_rate": (10, 13), "gcs": (12, 14)},
        ambulance_prob=0.7, risk_per_hour=0.5, treatment_min=(240, 480), admit_prob=0.6,
    ),
    Presentation(
        "L2_ASTHMA", "Shortness of breath - asthma", 2, 3, (12, 45),
        ("{age}{sex} wheezy, unable to finish sentences, salbutamol x6 puffs "
         "at home with no relief.",),
        history=(("asthma, prior ICU admission", "fluticasone/salmeterol, salbutamol"),),
        vitals={"heart_rate": (112, 128), "resp_rate": (26, 32), "spo2": (89, 92)},
        ambulance_prob=0.3, risk_per_hour=0.5, treatment_min=(120, 240), admit_prob=0.3,
    ),
    Presentation(
        "L2_SUICIDAL", "Suicidal ideation with plan", 2, 2, (16, 60),
        ("{age}{sex} brought by family, states plan to overdose tonight, "
         "has access to medications.",),
        history=(("major depressive disorder", "escitalopram"),),
        vitals={"heart_rate": (80, 100)},
        ambulance_prob=0.2, risk_per_hour=0.15, treatment_min=(180, 360), admit_prob=0.5,
    ),
    # Subtle level-2 presentations: look like level 3-4 at the front desk.
    Presentation(
        "L2_ATYPICAL_ACS", "Epigastric pain", 2, 3, (62, 85),
        ("{age}{sex} 'indigestion' since this morning, some nausea and fatigue. "
         "Thinks it was something she ate.",
         "{age}{sex} upper abdominal discomfort x3h, feels 'off', mild SOB on exertion."),
        sex="F",
        history=(("T2DM x15 years, HTN", "metformin, gliclazide, ramipril"),
                 ("T2DM, CKD stage 3", "insulin glargine, losartan")),
        vitals={"heart_rate": (92, 104), "systolic_bp": (138, 152), "pain_score": (3, 5)},
        ambulance_prob=0.1, risk_per_hour=0.45, subtle=True,
        treatment_min=(180, 300), admit_prob=0.7,
    ),
    Presentation(
        "L2_SAH_HEADACHE", "Headache", 2, 2, (30, 60),
        ("{age}{sex} sudden severe headache while lifting weights, 'worst of my life', "
         "onset over seconds. Now 6/10 after ibuprofen.",),
        history=(("nil significant", "none"), ("HTN, smoker", "amlodipine")),
        vitals={"systolic_bp": (145, 165), "pain_score": (5, 7)},
        ambulance_prob=0.05, risk_per_hour=0.4, subtle=True,
        treatment_min=(180, 300), admit_prob=0.6,
    ),
    Presentation(
        "L2_ECTOPIC", "Abdominal pain - lower", 2, 2, (19, 38),
        ("{age}{sex} R lower abdominal cramping x6h, some spotting. LMP ~7 weeks ago. "
         "Felt lightheaded in the waiting room bathroom.",),
        sex="F", history=(("nil significant", "none"), ("nil significant", "prenatal vitamins")),
        vitals={"heart_rate": (98, 110), "systolic_bp": (102, 112), "pain_score": (4, 6)},
        ambulance_prob=0.05, risk_per_hour=0.5, subtle=True,
        treatment_min=(120, 240), admit_prob=0.6,
    ),

    # ---- CTAS 3: Urgent --------------------------------------------------------
    Presentation(
        "L3_ABDO_PAIN", "Abdominal pain", 3, 8, (18, 75),
        ("{age}{sex} RLQ pain x18h, anorexic, vomited twice.",
         "{age}{sex} RUQ pain after fatty meal, radiates to back, vomiting."),
        history=(("nil significant", "none"), ("cholelithiasis", "none")),
        vitals={"heart_rate": (90, 105), "temp_c": (37.4, 38.3), "pain_score": (5, 7)},
        ambulance_prob=0.1, risk_per_hour=0.06, treatment_min=(120, 300), admit_prob=0.3,
    ),
    Presentation(
        "L3_RENAL_COLIC", "Flank pain", 3, 5, (25, 60),
        ("{age}{sex} sudden L flank pain radiating to groin, writhing, "
         "can't get comfortable.",),
        history=(("prior kidney stone", "none"), ("nil significant", "none")),
        vitals={"heart_rate": (92, 110), "systolic_bp": (140, 160), "pain_score": (8, 10)},
        ambulance_prob=0.1, risk_per_hour=0.03, treatment_min=(90, 180), admit_prob=0.1,
    ),
    Presentation(
        "L3_SOB_MILD", "Shortness of breath", 3, 6, (40, 85),
        ("{age}{sex} increased SOB and ankle swelling x4 days, sleeping on 3 pillows.",
         "{age}{sex} cough and SOB x5 days, green sputum."),
        history=(("CHF", "furosemide, bisoprolol"), ("COPD", "tiotropium"),
                 ("HTN", "amlodipine")),
        vitals={"heart_rate": (92, 106), "resp_rate": (20, 24), "spo2": (92, 95)},
        ambulance_prob=0.25, risk_per_hour=0.08, treatment_min=(150, 300), admit_prob=0.45,
    ),
    Presentation(
        "L3_SYNCOPE", "Syncope", 3, 4, (20, 85),
        ("{age}{sex} passed out at church while standing, brief LOC <1 min, "
         "back to baseline now.",),
        history=(("nil significant", "none"), ("HTN", "hydrochlorothiazide"),
                 ("atrial fibrillation", "apixaban, diltiazem")),
        vitals={"heart_rate": (55, 90)},
        ambulance_prob=0.4, risk_per_hour=0.05, treatment_min=(120, 240), admit_prob=0.25,
    ),
    Presentation(
        "L3_FEVER_ADULT", "Fever", 3, 5, (18, 65),
        ("{age}{sex} fever, body aches and cough x3 days, tolerating fluids.",),
        vitals={"heart_rate": (95, 108), "temp_c": (38.3, 39.2), "pain_score": (2, 4)},
        ambulance_prob=0.05, risk_per_hour=0.04, treatment_min=(90, 180), admit_prob=0.1,
    ),
    Presentation(
        "L3_VOMITING", "Vomiting and dehydration", 3, 5, (18, 80),
        ("{age}{sex} vomiting and diarrhea x2 days, unable to keep fluids down, dizzy on standing.",),
        vitals={"heart_rate": (98, 112), "systolic_bp": (100, 115), "pain_score": (3, 5)},
        ambulance_prob=0.1, risk_per_hour=0.04, treatment_min=(120, 240), admit_prob=0.15,
    ),
    Presentation(
        "L3_FRACTURE_HIP", "Hip injury - fall", 3, 3, (70, 95),
        ("{age}{sex} fall at home, unable to weight bear, L leg shortened and externally rotated.",),
        history=(("osteoporosis", "alendronate"), ("HTN", "amlodipine")),
        vitals={"heart_rate": (88, 102), "pain_score": (6, 8)},
        ambulance_prob=0.85, risk_per_hour=0.05, treatment_min=(180, 360), admit_prob=0.9,
    ),
    # Subtle: looks like a minor head bump, but anticoagulated.
    Presentation(
        "L3_HEAD_INJURY_ANTICOAG", "Head injury - minor", 3, 3, (68, 92),
        ("{age}{sex} tripped on rug, hit head on table, small scalp lac. "
         "Denies LOC. Daughter says 'a bit more forgetful today'.",),
        history=(("atrial fibrillation", "rivaroxaban"),
                 ("mechanical mitral valve", "warfarin")),
        vitals={"pain_score": (2, 4)},
        ambulance_prob=0.3, risk_per_hour=0.35, subtle=True,
        treatment_min=(150, 300), admit_prob=0.4,
    ),

    # ---- CTAS 4: Less urgent ---------------------------------------------------
    Presentation(
        "L4_ANKLE", "Ankle injury", 4, 8, (12, 60),
        ("{age}{sex} rolled ankle playing basketball, swelling lateral malleolus, "
         "limping but weight bearing.",),
        vitals={"pain_score": (4, 6)},
        ambulance_prob=0.0, risk_per_hour=0.003, treatment_min=(45, 90), admit_prob=0.0,
    ),
    Presentation(
        "L4_LACERATION", "Laceration", 4, 7, (5, 75),
        ("{age}{sex} 3 cm laceration to forearm from kitchen knife, bleeding controlled.",),
        vitals={"pain_score": (3, 5)},
        ambulance_prob=0.0, risk_per_hour=0.003, treatment_min=(40, 80), admit_prob=0.0,
    ),
    Presentation(
        "L4_UTI", "Urinary symptoms", 4, 5, (18, 70),
        ("{age}{sex} dysuria and frequency x2 days, no fever, no flank pain.",),
        vitals={"pain_score": (2, 4)},
        ambulance_prob=0.0, risk_per_hour=0.008, treatment_min=(40, 90), admit_prob=0.02,
    ),
    Presentation(
        "L4_BACK_PAIN", "Back pain", 4, 6, (25, 65),
        ("{age}{sex} lower back pain after moving furniture, no numbness or "
         "bladder/bowel changes.",),
        vitals={"pain_score": (5, 7)},
        ambulance_prob=0.05, risk_per_hour=0.003, treatment_min=(45, 90), admit_prob=0.01,
    ),
    Presentation(
        "L4_EAR_PAIN", "Earache", 4, 4, (2, 40),
        ("{age}{sex} R ear pain x2 days, mild fever at home.",),
        vitals={"temp_c": (37.4, 38.2), "pain_score": (3, 5)},
        ambulance_prob=0.0, risk_per_hour=0.002, treatment_min=(30, 60), admit_prob=0.0,
    ),

    # ---- CTAS 5: Non-urgent ----------------------------------------------------
    Presentation(
        "L5_SORE_THROAT", "Sore throat", 5, 5, (8, 50),
        ("{age}{sex} sore throat x3 days, eating and drinking okay.",),
        vitals={"pain_score": (2, 4)},
        ambulance_prob=0.0, risk_per_hour=0.001, treatment_min=(20, 45), admit_prob=0.0,
    ),
    Presentation(
        "L5_URTI", "Cold and flu symptoms", 5, 5, (18, 60),
        ("{age}{sex} runny nose, congestion and cough x4 days, wants a note for work.",),
        ambulance_prob=0.0, risk_per_hour=0.001, treatment_min=(15, 40), admit_prob=0.0,
    ),
    Presentation(
        "L5_MED_REFILL", "Medication request", 5, 3, (30, 80),
        ("{age}{sex} ran out of BP medication, family doctor away, no symptoms.",),
        history=(("HTN", "amlodipine"),),
        ambulance_prob=0.0, risk_per_hour=0.001, treatment_min=(15, 30), admit_prob=0.0,
    ),
    Presentation(
        "L5_RASH", "Rash", 5, 3, (5, 60),
        ("{age}{sex} itchy rash on forearms x1 week after gardening, no fever.",),
        ambulance_prob=0.0, risk_per_hour=0.001, treatment_min=(15, 40), admit_prob=0.0,
    ),
)

BY_CODE = {p.code: p for p in CATALOG}
BY_CTAS: dict[int, tuple[Presentation, ...]] = {
    level: tuple(p for p in CATALOG if p.ctas == level) for level in range(1, 6)
}

# Relative arrival rate by hour of day (0-23); normalized to mean 1.0.
_HOURLY = (
    0.55, 0.45, 0.38, 0.33, 0.30, 0.32, 0.42, 0.62, 0.90, 1.15, 1.32, 1.38,
    1.35, 1.33, 1.30, 1.28, 1.27, 1.27, 1.28, 1.25, 1.15, 1.00, 0.85, 0.70,
)
HOURLY_ARRIVAL_FACTOR = tuple(h * 24 / sum(_HOURLY) for h in _HOURLY)
