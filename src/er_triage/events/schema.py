"""Event envelope emitted by the simulator and triage engine.

Events are the integration surface for downstream platforms (Cribl, a
warehouse, a SIEM...). The envelope is stable; ``data`` varies by type.
Patient-level events intentionally carry synthetic PHI so pipelines can
demonstrate masking/redaction.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"
SOURCE = "er-triage-sim"


class EventType(StrEnum):
    RUN_STARTED = "run.started"
    RUN_STOPPED = "run.stopped"
    PATIENT_ARRIVED = "patient.arrived"
    VITALS_RECORDED = "vitals.recorded"
    TRIAGE_ASSESSED = "triage.assessed"
    PATIENT_DETERIORATED = "patient.deteriorated"
    PHYSICIAN_ASSIGNED = "physician.assigned"
    PATIENT_DEPARTED = "patient.departed"
    QUEUE_REPRIORITIZED = "queue.reprioritized"
    METRICS_SNAPSHOT = "metrics.snapshot"
    SLO_BREACH = "slo.breach"
    LLM_CALL = "llm.call"


class Event(BaseModel):
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: EventType
    emitted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sim_time: datetime | None = None
    run_id: uuid.UUID | None = None
    arm: str | None = None
    source: str = SOURCE
    schema_version: str = SCHEMA_VERSION
    data: dict[str, Any] = Field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
