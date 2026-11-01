"""Synthetic EHR feed: the heartbeat of the simulation.

Each tick advances the simulated clock, admits new arrivals into both ED arms,
re-checks vitals for waiting patients on CTAS reassessment intervals, and
applies deterioration to patients who wait too long. Everything is persisted
to Postgres and published on the event bus.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from er_triage.db import session_scope
from er_triage.events import EventBus, EventType
from er_triage.models import (
    Arm,
    Encounter,
    EncounterStatus,
    Patient,
    SimRun,
    VitalSigns,
)
from er_triage.sim.catalog import CTAS_REASSESS_MIN, CTAS_TARGET_MIN, Presentation
from er_triage.sim.clock import SimClock
from er_triage.sim.generator import NewPatient, PatientGenerator, Vitals

log = logging.getLogger(__name__)

WAITING = {EncounterStatus.WAITING_TRIAGE, EncounterStatus.WAITING_PHYSICIAN}


@dataclass
class ActiveEncounter:
    """In-memory working state for one patient in one arm."""

    encounter_id: uuid.UUID
    patient_id: uuid.UUID
    arm: Arm
    presentation: Presentation
    fragility: float
    arrived_at: datetime
    arrival_mode: str
    current_ctas: int
    vitals: Vitals
    next_vitals_at: datetime
    status: EncounterStatus = EncounterStatus.WAITING_TRIAGE
    assigned_ctas: int | None = None
    hazard: float = 0.0
    deteriorated: bool = False

    def wait_minutes(self, now: datetime) -> float:
        return (now - self.arrived_at).total_seconds() / 60


class FeedEngine:
    def __init__(
        self,
        bus: EventBus,
        *,
        sim_start: datetime,
        speed: float = 1.0,
        seed: int | None = None,
        scenario: str = "baseline_day",
        daily_volume: float = 150.0,
        arrival_multiplier: float = 1.0,
        tick_seconds: float = 1.0,
    ) -> None:
        self.bus = bus
        self.clock = SimClock(sim_start, speed)
        self.generator = PatientGenerator(seed, daily_volume)
        self.seed = seed
        self.scenario = scenario
        self.arrival_multiplier = arrival_multiplier
        self.tick_seconds = tick_seconds
        self.run_id: uuid.UUID | None = None
        self.active: dict[uuid.UUID, ActiveEncounter] = {}
        self._last_tick = sim_start
        self._task: asyncio.Task[None] | None = None

    # -- lifecycle -------------------------------------------------------------

    def create_run(self) -> uuid.UUID:
        config = {
            "daily_volume": self.generator.daily_volume,
            "arrival_multiplier": self.arrival_multiplier,
            "tick_seconds": self.tick_seconds,
        }
        with session_scope() as s:
            run = SimRun(
                scenario=self.scenario, seed=self.seed, sim_start_at=self.clock.start,
                speed=self.clock.speed, config=config,
            )
            s.add(run)
            s.flush()
            self.run_id = run.id
        self._emit(EventType.RUN_STARTED, self.clock.start, {
            "scenario": self.scenario, "seed": self.seed, "speed": self.clock.speed, **config,
        })
        return self.run_id

    def start(self) -> None:
        if self.run_id is None:
            self.create_run()
        self._task = asyncio.create_task(self._loop(), name="feed-engine")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self.run_id is not None:
            with session_scope() as s:
                s.get(SimRun, self.run_id).status = "stopped"
            self._emit(EventType.RUN_STOPPED, self.clock.now(), {})

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.step, self.clock.now())
            except Exception:
                log.exception("feed tick failed")
            await asyncio.sleep(self.tick_seconds)

    # -- simulation ------------------------------------------------------------

    def step(self, now: datetime) -> None:
        """Advance the simulation to ``now`` (simulated time)."""
        if now <= self._last_tick:
            return
        start, self._last_tick = self._last_tick, now
        with session_scope() as s:
            for arrived_at in self.generator.sample_arrival_times(
                start, now, self.arrival_multiplier
            ):
                self._admit(s, self.generator.new_patient(arrived_at))
            dt_hours = (now - start).total_seconds() / 3600
            for enc in list(self.active.values()):
                if enc.status in WAITING:
                    self._accumulate_risk(s, enc, now, dt_hours)
                if now >= enc.next_vitals_at:
                    self._recheck_vitals(s, enc, now)

    def _admit(self, s: Session, np: NewPatient) -> None:
        p = np.presentation
        patient = Patient(
            run_id=self.run_id, mrn=np.mrn, health_card_no=np.health_card_no,
            first_name=np.first_name, last_name=np.last_name, date_of_birth=np.date_of_birth,
            sex=np.sex, postal_code=np.postal_code, arrival_mode=np.arrival_mode,
            arrived_at=np.arrived_at, chief_complaint=p.complaint, triage_note=np.triage_note,
            history=np.history, presentation_code=p.code, true_ctas=p.ctas,
            fragility=np.fragility,
        )
        s.add(patient)
        s.flush()

        states = []
        for arm in Arm:
            enc = Encounter(
                run_id=self.run_id, patient_id=patient.id, arm=arm,
                arrived_at=np.arrived_at, current_ctas=p.ctas,
            )
            s.add(enc)
            s.flush()
            states.append(ActiveEncounter(
                encounter_id=enc.id, patient_id=patient.id, arm=arm, presentation=p,
                fragility=np.fragility, arrived_at=np.arrived_at,
                arrival_mode=np.arrival_mode, current_ctas=p.ctas,
                vitals=Vitals(**np.vitals.as_dict()),
                next_vitals_at=np.arrived_at + timedelta(minutes=CTAS_REASSESS_MIN[p.ctas]),
            ))

        # Arrival is shared by both arms and is emitted before any per-arm
        # events. Synthetic PHI is included on purpose so downstream pipelines
        # can demonstrate masking.
        self._emit(EventType.PATIENT_ARRIVED, np.arrived_at, {
            "patient_id": str(patient.id),
            "encounter_ids": {st.arm.value: str(st.encounter_id) for st in states},
            "mrn": np.mrn,
            "health_card_no": np.health_card_no,
            "first_name": np.first_name,
            "last_name": np.last_name,
            "date_of_birth": np.date_of_birth.isoformat(),
            "age": np.age,
            "sex": np.sex,
            "postal_code": np.postal_code,
            "arrival_mode": np.arrival_mode,
            "chief_complaint": p.complaint,
            "triage_note": np.triage_note,
            "history": np.history,
            "vitals": np.vitals.as_dict(),
        })
        for state in states:
            self.active[state.encounter_id] = state
            self._record_vitals(s, state, np.arrived_at)

    def _accumulate_risk(
        self, s: Session, enc: ActiveEncounter, now: datetime, dt_hours: float
    ) -> None:
        if enc.deteriorated:
            return
        # Risk escalates once a patient has waited past their CTAS target.
        target = max(CTAS_TARGET_MIN[enc.presentation.ctas], 5)
        overdue = max(0.0, enc.wait_minutes(now) / target - 1)
        enc.hazard += enc.presentation.risk_per_hour * dt_hours * (1 + 0.5 * overdue)
        if enc.hazard >= enc.fragility:
            self._deteriorate(s, enc, now)

    def _deteriorate(self, s: Session, enc: ActiveEncounter, now: datetime) -> None:
        previous = enc.current_ctas
        enc.deteriorated = True
        enc.current_ctas = max(1, previous - 1)
        enc.vitals = self.generator.deteriorate(enc.vitals)
        row = s.get(Encounter, enc.encounter_id)
        row.current_ctas = enc.current_ctas
        row.deteriorated_at = now
        self._record_vitals(s, enc, now)
        enc.next_vitals_at = now + timedelta(minutes=CTAS_REASSESS_MIN[enc.current_ctas])
        self._emit(EventType.PATIENT_DETERIORATED, now, {
            "encounter_id": str(enc.encounter_id),
            "patient_id": str(enc.patient_id),
            "previous_ctas": previous,
            "current_ctas": enc.current_ctas,
            "assigned_ctas": enc.assigned_ctas,
            "wait_min": round(enc.wait_minutes(now), 1),
            "vitals": enc.vitals.as_dict(),
        }, arm=enc.arm)

    def _recheck_vitals(self, s: Session, enc: ActiveEncounter, now: datetime) -> None:
        enc.vitals = self.generator.recheck_vitals(enc.presentation, enc.vitals, enc.deteriorated)
        self._record_vitals(s, enc, now)
        # Reassessment cadence follows the acuity the ED believes the patient has.
        level = enc.assigned_ctas or enc.current_ctas
        enc.next_vitals_at = now + timedelta(minutes=CTAS_REASSESS_MIN[level])

    def _record_vitals(self, s: Session, enc: ActiveEncounter, at: datetime) -> None:
        s.add(VitalSigns(encounter_id=enc.encounter_id, recorded_at=at, **enc.vitals.as_dict()))
        self._emit(EventType.VITALS_RECORDED, at, {
            "encounter_id": str(enc.encounter_id),
            "patient_id": str(enc.patient_id),
            **enc.vitals.as_dict(),
        }, arm=enc.arm)

    def _emit(self, event_type: EventType, sim_time: datetime, data: dict,
              arm: Arm | None = None) -> None:
        self.bus.emit(event_type, data, sim_time=sim_time, run_id=self.run_id,
                      arm=arm.value if arm else None)
