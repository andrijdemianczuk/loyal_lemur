"""Relational schema for the ED simulation.

One simulated arrival stream feeds two parallel EDs ("arms"): a manual-triage
baseline and an AI-assisted ED. A patient therefore has one row in
``patients`` and one ``encounters`` row per arm, so outcomes can be compared
patient-for-patient.

All ``*_at`` columns on clinical tables are *simulated* clock times.
"""

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}


class Arm(StrEnum):
    BASELINE = "baseline"  # manual nurse triage, FIFO within CTAS level
    AI = "ai"  # Claude-assisted triage and queue ordering


class ArrivalMode(StrEnum):
    WALK_IN = "walk_in"
    AMBULANCE = "ambulance"


class EncounterStatus(StrEnum):
    WAITING_TRIAGE = "waiting_triage"
    WAITING_PHYSICIAN = "waiting_physician"
    IN_TREATMENT = "in_treatment"
    DISCHARGED = "discharged"
    ADMITTED = "admitted"
    LWBS = "lwbs"  # left without being seen


class AssessmentSource(StrEnum):
    NURSE = "nurse"
    RULES = "rules"  # deterministic CTAS calculator (AI arm fallback)
    AI = "ai"


class Lane(StrEnum):
    MAIN = "main"
    FAST_TRACK = "fast"
    INTAKE = "intake"  # rapid assessment zone staffed by idle main physicians


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _ctas(nullable: bool = False) -> Mapped[Any]:
    return mapped_column(SmallInteger, nullable=nullable)


class SimRun(Base):
    __tablename__ = "sim_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    scenario: Mapped[str] = mapped_column(String(64), default="baseline_day")
    seed: Mapped[int | None]
    sim_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    speed: Mapped[float] = mapped_column(Float, default=1.0)
    status: Mapped[str] = mapped_column(String(16), default="running")
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Patient(Base):
    """Synthetic demographics. Fields marked PHI are deliberately realistic so
    downstream pipelines (e.g. Cribl) can demonstrate masking."""

    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sim_runs.id", ondelete="CASCADE"))
    mrn: Mapped[str] = mapped_column(String(16))  # PHI
    health_card_no: Mapped[str] = mapped_column(String(24))  # PHI
    first_name: Mapped[str] = mapped_column(String(64))  # PHI
    last_name: Mapped[str] = mapped_column(String(64))  # PHI
    date_of_birth: Mapped[date] = mapped_column(Date)  # PHI
    sex: Mapped[str] = mapped_column(String(1))
    postal_code: Mapped[str] = mapped_column(String(8))  # PHI

    # Clinical presentation shared by both arms.
    arrival_mode: Mapped[ArrivalMode] = mapped_column(String(16))
    arrived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    chief_complaint: Mapped[str] = mapped_column(String(128))
    triage_note: Mapped[str] = mapped_column(Text, default="")
    history: Mapped[str] = mapped_column(Text, default="")

    # Simulator ground truth, used for scoring and never shown to either
    # triage arm.
    presentation_code: Mapped[str] = mapped_column(String(32))
    true_ctas: Mapped[int] = _ctas()
    fragility: Mapped[float]  # latent deterioration threshold

    encounters: Mapped[list["Encounter"]] = relationship(back_populates="patient")

    __table_args__ = (
        UniqueConstraint("run_id", "mrn"),
        CheckConstraint("true_ctas BETWEEN 1 AND 5", name="ck_patient_true_ctas"),
        Index("ix_patients_run_arrived", "run_id", "arrived_at"),
    )


class Encounter(Base):
    """A patient's journey through one arm of the ED."""

    __tablename__ = "encounters"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sim_runs.id", ondelete="CASCADE"))
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE")
    )
    arm: Mapped[Arm] = mapped_column(String(16))
    status: Mapped[EncounterStatus] = mapped_column(
        String(24), default=EncounterStatus.WAITING_TRIAGE
    )

    assigned_ctas: Mapped[int | None] = _ctas(nullable=True)
    priority_score: Mapped[float | None]  # higher = see sooner

    arrived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    triaged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    physician_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    departed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lane: Mapped[Lane | None] = mapped_column(String(8))

    # Deterioration while waiting can raise effective acuity above true_ctas.
    current_ctas: Mapped[int | None] = _ctas(nullable=True)
    deteriorated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    patient: Mapped[Patient] = relationship(back_populates="encounters")
    vitals: Mapped[list["VitalSigns"]] = relationship(back_populates="encounter")
    assessments: Mapped[list["TriageAssessment"]] = relationship(back_populates="encounter")

    __table_args__ = (
        UniqueConstraint("patient_id", "arm"),
        CheckConstraint("assigned_ctas BETWEEN 1 AND 5", name="ck_enc_assigned_ctas"),
        CheckConstraint("current_ctas BETWEEN 1 AND 5", name="ck_enc_current_ctas"),
        Index("ix_encounters_run_arm_status", "run_id", "arm", "status"),
    )


class VitalSigns(Base):
    __tablename__ = "vital_signs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    encounter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("encounters.id", ondelete="CASCADE")
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    heart_rate: Mapped[int]
    systolic_bp: Mapped[int]
    diastolic_bp: Mapped[int]
    resp_rate: Mapped[int]
    spo2: Mapped[int]
    temp_c: Mapped[float]
    pain_score: Mapped[int] = mapped_column(SmallInteger)  # 0-10
    gcs: Mapped[int] = mapped_column(SmallInteger)  # 3-15

    encounter: Mapped[Encounter] = relationship(back_populates="vitals")

    __table_args__ = (Index("ix_vitals_encounter_time", "encounter_id", "recorded_at"),)


class TriageAssessment(Base):
    """A triage decision by a nurse (baseline) or Claude (AI arm)."""

    __tablename__ = "triage_assessments"

    id: Mapped[uuid.UUID] = _uuid_pk()
    encounter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("encounters.id", ondelete="CASCADE")
    )
    source: Mapped[AssessmentSource] = mapped_column(String(8))
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ctas_level: Mapped[int] = _ctas()
    priority_score: Mapped[float | None]
    rationale: Mapped[str] = mapped_column(Text, default="")
    red_flags: Mapped[list[Any]] = mapped_column(default=list)
    # False when a decision arrived too late to change care (kept for audit).
    applied: Mapped[bool] = mapped_column(default=True)
    # Likely to need hospital admission (AI only); drives the early bed request.
    admit_predicted: Mapped[bool | None]

    # LLM call telemetry (null for nurse assessments).
    model: Mapped[str | None] = mapped_column(String(64))
    latency_ms: Mapped[int | None]
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]

    encounter: Mapped[Encounter] = relationship(back_populates="assessments")

    __table_args__ = (
        CheckConstraint("ctas_level BETWEEN 1 AND 5", name="ck_assessment_ctas"),
        Index("ix_assessments_encounter", "encounter_id", "assessed_at"),
    )


class MetricSnapshot(Base):
    """Periodic SLI roll-up per arm, for time-series charts."""

    __tablename__ = "metric_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sim_runs.id", ondelete="CASCADE"))
    arm: Mapped[Arm] = mapped_column(String(16))
    sim_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    waiting: Mapped[int]
    in_treatment: Mapped[int]
    avg_wait_min: Mapped[float]
    p90_wait_min: Mapped[float]
    max_walk_in_wait_min: Mapped[float]
    slo_breaches: Mapped[int]  # walk-ins exceeding the 4h SLO so far
    ctas_target_misses: Mapped[int]  # time-to-physician above true CTAS target
    under_triaged: Mapped[int]  # assigned a lower acuity than true at triage
    deteriorations: Mapped[int]
    lwbs: Mapped[int]
    seen: Mapped[int]
    by_ctas: Mapped[dict[str, Any]] = mapped_column(default=dict)

    __table_args__ = (Index("ix_metrics_run_arm_time", "run_id", "arm", "sim_time"),)


class LlmResponse(Base):
    """Cache of model responses keyed by the exact request, so a rehearsed
    seed can be replayed with no API calls."""

    __tablename__ = "llm_responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cache_key: Mapped[str] = mapped_column(String(64), unique=True)
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(16))
    request: Mapped[dict[str, Any]] = mapped_column(default=dict)
    response: Mapped[dict[str, Any]] = mapped_column(default=dict)
    latency_ms: Mapped[int]
    input_tokens: Mapped[int]
    output_tokens: Mapped[int]
    cache_read_tokens: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
