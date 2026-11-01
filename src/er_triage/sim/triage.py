"""Triage decision makers for the two ED arms.

- ``NurseTriager`` (baseline): a busy human triage nurse. Usually right, but
  with realistic error rates: under-triage is more common than over-triage,
  subtle presentations are frequently under-scored, errors rise with
  waiting-room load, and deterioration is noticed only some of the time.
- ``RulesTriager`` (AI arm fallback): a deterministic CTAS calculator using
  the chief complaint's base level and first-order vital-sign modifiers. It
  never makes random errors and re-scores at every reassessment, but it only
  sees what the numbers show, so it misses subtle presentations with normal
  vitals. Phase 4 puts Claude in front of it.

Neither triager sees simulator ground truth except the nurse error model,
which perturbs the true level to emulate human performance.
"""

import random
from dataclasses import dataclass, field
from typing import Protocol

from er_triage.models import AssessmentSource
from er_triage.sim.generator import NewPatient, Vitals

# Base CTAS level a complaint-lookup (CEDIS-style) would suggest before
# modifiers. Deliberately not the ground truth: benign-sounding complaints
# for dangerous conditions start low, as they do in real lookups.
COMPLAINT_BASE = {
    "Major trauma - MVC": 2,
    "Severe respiratory distress": 2,
    "Allergic reaction - anaphylaxis": 2,
    "Seizure - ongoing": 1,
    "Chest pain - cardiac features": 2,
    "Stroke symptoms - within window": 2,
    "Fever - suspected sepsis": 3,
    "Overdose - ingestion": 2,
    "Shortness of breath - asthma": 3,
    "Suicidal ideation with plan": 2,
    "Epigastric pain": 4,
    "Headache": 4,
    "Abdominal pain - lower": 4,
    "Abdominal pain": 4,
    "Flank pain": 4,
    "Shortness of breath": 3,
    "Syncope": 3,
    "Fever": 4,
    "Vomiting and dehydration": 4,
    "Hip injury - fall": 3,
    "Head injury - minor": 4,
    "Ankle injury": 4,
    "Laceration": 4,
    "Urinary symptoms": 4,
    "Back pain": 4,
    "Earache": 4,
    "Sore throat": 5,
    "Cold and flu symptoms": 5,
    "Medication request": 5,
    "Rash": 5,
}


@dataclass
class TriageDecision:
    ctas: int
    source: AssessmentSource
    rationale: str = ""
    red_flags: list[str] = field(default_factory=list)
    priority_score: float | None = None
    fast_track: bool | None = None  # None = let the queue policy decide
    model: str | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class Triager(Protocol):
    def assess(self, patient: NewPatient, vitals: Vitals, true_ctas: int,
               waiting_load: int) -> TriageDecision: ...

    def reassess(self, patient: NewPatient, vitals: Vitals, assigned: int,
                 true_ctas: int) -> TriageDecision | None: ...


def vitals_level(v: Vitals) -> tuple[int, list[str]]:
    """First-order CTAS modifiers from vital signs. Returns (level, reasons)."""
    checks = [
        (1, v.gcs <= 9, f"GCS {v.gcs}"),
        (1, v.spo2 < 86, f"SpO2 {v.spo2}%"),
        (1, v.systolic_bp < 80, f"SBP {v.systolic_bp}"),
        (1, v.heart_rate >= 140, f"HR {v.heart_rate}"),
        (1, v.resp_rate >= 36, f"RR {v.resp_rate}"),
        (2, v.gcs <= 13, f"GCS {v.gcs}"),
        (2, v.spo2 < 92, f"SpO2 {v.spo2}%"),
        (2, v.systolic_bp < 90, f"SBP {v.systolic_bp}"),
        (2, v.heart_rate >= 120, f"HR {v.heart_rate}"),
        (2, v.resp_rate >= 28, f"RR {v.resp_rate}"),
        (2, v.temp_c >= 38.5 and (v.heart_rate > 110 or v.systolic_bp < 100),
         f"T {v.temp_c} with hemodynamic change"),
        (3, v.gcs == 14, f"GCS {v.gcs}"),
        (3, v.spo2 < 95, f"SpO2 {v.spo2}%"),
        (3, v.heart_rate > 100, f"HR {v.heart_rate}"),
        (3, v.resp_rate > 24, f"RR {v.resp_rate}"),
        (3, v.systolic_bp >= 200, f"SBP {v.systolic_bp}"),
        (3, v.temp_c >= 38.0 and v.heart_rate > 100, f"T {v.temp_c}, HR {v.heart_rate}"),
        (3, v.pain_score >= 8, f"pain {v.pain_score}/10"),
        (4, v.pain_score >= 4, f"pain {v.pain_score}/10"),
    ]
    hits = [(lvl, why) for lvl, hit, why in checks if hit]
    if not hits:
        return 5, []
    level = min(lvl for lvl, _ in hits)
    return level, [why for lvl, why in hits if lvl == level]


class RulesTriager:
    source = AssessmentSource.RULES
    model = "ctas-rules-v1"

    def score(self, patient: NewPatient, vitals: Vitals) -> TriageDecision:
        base = COMPLAINT_BASE.get(patient.presentation.complaint, 3)
        v_level, reasons = vitals_level(vitals)
        level = min(base, v_level)
        why = f"Complaint '{patient.presentation.complaint}' base CTAS {base}"
        if v_level < base:
            why += f"; vitals modifier to CTAS {v_level} ({', '.join(reasons)})"
        return TriageDecision(level, self.source, why, reasons if v_level < base else [],
                              model=self.model)

    def assess(self, patient, vitals, true_ctas, waiting_load):
        return self.score(patient, vitals)

    def reassess(self, patient, vitals, assigned, true_ctas):
        decision = self.score(patient, vitals)
        if decision.ctas < assigned:
            decision.rationale = "Reassessment: " + decision.rationale
            return decision
        return None


class NurseTriager:
    source = AssessmentSource.NURSE

    def __init__(
        self,
        rng: random.Random,
        under_rate: float = 0.12,
        over_rate: float = 0.08,
        subtle_miss_rate: float = 0.6,
        load_penalty: float = 0.004,  # extra under-triage per waiting patient
        notice_rate: float = 0.5,  # chance a reassessment acts on abnormal vitals
        gestalt_rate: float = 0.1,  # chance of catching under-triage without them
    ) -> None:
        self.gestalt_rate = gestalt_rate
        self.rng = rng
        self.under_rate = under_rate
        self.over_rate = over_rate
        self.subtle_miss_rate = subtle_miss_rate
        self.load_penalty = load_penalty
        self.notice_rate = notice_rate

    def assess(self, patient, vitals, true_ctas, waiting_load):
        rng = self.rng
        if true_ctas == 1:
            return TriageDecision(1, self.source, "Obvious resuscitation case")
        under = self.under_rate + self.load_penalty * waiting_load
        if patient.presentation.subtle and rng.random() < self.subtle_miss_rate:
            level = true_ctas + rng.choice((1, 2))
        elif (r := rng.random()) < under:
            level = true_ctas + 1
        elif r < under + self.over_rate:
            level = true_ctas - 1
        else:
            level = true_ctas
        return TriageDecision(max(1, min(5, level)), self.source, "Nurse triage")

    def reassess(self, patient, vitals, assigned, true_ctas):
        v_level, reasons = vitals_level(vitals)
        if v_level < assigned and self.rng.random() < self.notice_rate:
            return TriageDecision(v_level, self.source,
                                  f"Nurse reassessment: {', '.join(reasons)}", reasons)
        # Occasionally clinical gestalt catches an under-triage without
        # abnormal numbers.
        if true_ctas < assigned and self.rng.random() < self.gestalt_rate:
            return TriageDecision(true_ctas, self.source, "Nurse reassessment: clinical concern")
        return None
