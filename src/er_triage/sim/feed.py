"""Synthetic EHR feed: the heartbeat of the simulation.

Each tick advances the simulated clock in small sub-steps. A sub-step admits
new arrivals into both ED arms, advances each arm's flow (triage, physician
assignment, departures), re-checks vitals for waiting patients on CTAS
reassessment intervals, and applies deterioration to patients who wait too
long. Everything is persisted to Postgres and published on the event bus.
"""

import asyncio
import dataclasses
import logging
import random
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from er_triage.db import session_scope
from er_triage.events import EventBus, EventType
from er_triage.models import Arm, Encounter, Patient, SimRun, VitalSigns
from er_triage.sim.catalog import CTAS_REASSESS_MIN, effective_target_min
from er_triage.sim.clock import SimClock
from er_triage.sim.ed import (
    WAITING,
    ActiveEncounter,
    CtasFifoPolicy,
    EDArm,
    EDConfig,
    SloAwarePolicy,
)
from er_triage.sim.generator import NewPatient, PatientGenerator, Vitals
from er_triage.sim.triage import NurseTriager, RulesTriager, Triager

log = logging.getLogger(__name__)

# Fixed simulated-time grid. Steps always process whole grid intervals, so
# the patient stream depends only on the seed, never on wall-clock timing.
SUBSTEP = timedelta(minutes=1)
SNAPSHOT_EVERY = timedelta(minutes=15)


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
        boarding_min: tuple[float, float] = (480, 1080),
        arrival_multiplier: float = 1.0,
        tick_seconds: float = 1.0,
        ed_config: EDConfig | None = None,
        ai_ed_config: EDConfig | None = None,
        ai_triager: Triager | None = None,
    ) -> None:
        self.bus = bus
        self.clock = SimClock(sim_start, speed)
        self.generator = PatientGenerator(seed, daily_volume, boarding_min)
        self.seed = seed
        self.scenario = scenario
        self.arrival_multiplier = arrival_multiplier
        self.tick_seconds = tick_seconds
        self.ed_config = ed_config or EDConfig()
        # Same resources; the AI arm only changes how the intake zone is used.
        self.ai_ed_config = ai_ed_config or dataclasses.replace(
            self.ed_config, intake_mode="dynamic")
        self.run_id: uuid.UUID | None = None
        nurse_rng = random.Random(None if seed is None else seed + 2)
        self.arms = {
            Arm.BASELINE: EDArm(Arm.BASELINE, NurseTriager(nurse_rng), CtasFifoPolicy(),
                                self.ed_config, self._emit),
            Arm.AI: EDArm(Arm.AI, ai_triager or RulesTriager(),
                          SloAwarePolicy(self.ai_ed_config.slo_guard_min),
                          self.ai_ed_config, self._emit),
        }
        if attach := getattr(self.arms[Arm.AI].triager, "attach_emitter", None):
            attach(lambda event_type, data: self._emit(
                event_type, self.clock.now(), data, Arm.AI))
        self._last_tick = sim_start
        self._next_snapshot = sim_start + SNAPSHOT_EVERY
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self.stop_at: datetime | None = None  # optional end of simulated time

    # -- lifecycle -------------------------------------------------------------

    def create_run(self) -> uuid.UUID:
        config = {
            "daily_volume": self.generator.daily_volume,
            "arrival_multiplier": self.arrival_multiplier,
            "tick_seconds": self.tick_seconds,
            "ed": {arm.value: a.config.__dict__ for arm, a in self.arms.items()},
            "policies": {arm.value: a.policy.name for arm, a in self.arms.items()},
            "triagers": {arm.value: type(a.triager).__name__ for arm, a in self.arms.items()},
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

    @property
    def processed_until(self) -> datetime:
        """Simulated time the engine has fully processed (lags the clock while
        waiting on slow work such as blocking AI calls)."""
        return self._last_tick

    async def stop(self) -> None:
        if self._task is not None:
            # Let the in-flight step finish so no writes land after the run ends.
            self._stopping = True
            await self._task
            self._task = None
        if close := getattr(self.arms[Arm.AI].triager, "close", None):
            close()
        if self.run_id is not None:
            with session_scope() as s:
                s.get(SimRun, self.run_id).status = "stopped"
            self._emit(EventType.RUN_STOPPED, self.clock.now(), {})

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                now = self.clock.now()
                if self.stop_at is not None:
                    now = min(now, self.stop_at)
                await asyncio.to_thread(self.step, now)
            except Exception:
                log.exception("feed tick failed")
            await asyncio.sleep(self.tick_seconds)

    # -- simulation ------------------------------------------------------------

    def step(self, now: datetime) -> None:
        """Advance the simulation through every whole grid interval up to
        ``now`` (simulated time)."""
        if now < self._last_tick + SUBSTEP:
            return
        with session_scope() as s:
            while self._last_tick + SUBSTEP <= now:
                t = self._last_tick + SUBSTEP
                self._substep(s, self._last_tick, t)
                self._last_tick = t

    def _substep(self, s: Session, start: datetime, t: datetime) -> None:
        for arrived_at in self.generator.sample_arrival_times(start, t, self.arrival_multiplier):
            self._admit(s, self.generator.new_patient(arrived_at))
        for arm in self.arms.values():
            arm.step(s, t)
        dt_hours = (t - start).total_seconds() / 3600
        for arm in self.arms.values():
            for enc in list(arm.by_status(*WAITING)):
                self._accumulate_risk(s, arm, enc, t, dt_hours)
                if t >= enc.next_vitals_at:
                    self._recheck_vitals(s, arm, enc, t)
        if t >= self._next_snapshot:
            for arm in self.arms.values():
                arm.snapshot(s, self.run_id, t)
            self._next_snapshot += SNAPSHOT_EVERY

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
                encounter_id=enc.id, patient_id=patient.id, arm=arm, patient=np,
                current_ctas=p.ctas, vitals=Vitals(**np.vitals.as_dict()),
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
            self.arms[state.arm].admit(state)
            self._record_vitals(s, state, np.arrived_at)

    def _accumulate_risk(self, s: Session, arm: EDArm, enc: ActiveEncounter, t: datetime,
                         dt_hours: float) -> None:
        if enc.deteriorated:
            return
        # Risk escalates once a patient has waited past their CTAS target.
        overdue = max(0.0, enc.wait_minutes(t) / effective_target_min(enc.presentation.ctas) - 1)
        enc.hazard += enc.presentation.risk_per_hour * dt_hours * (1 + 0.5 * overdue)
        if enc.hazard >= enc.patient.fragility:
            self._deteriorate(s, arm, enc, t)

    def _deteriorate(self, s: Session, arm: EDArm, enc: ActiveEncounter, t: datetime) -> None:
        previous = enc.current_ctas
        enc.deteriorated = True
        enc.current_ctas = max(1, previous - 1)
        enc.vitals = self.generator.deteriorate(enc.vitals, enc.rng)
        row = s.get(Encounter, enc.encounter_id)
        row.current_ctas = enc.current_ctas
        row.deteriorated_at = t
        self._record_vitals(s, enc, t)
        enc.next_vitals_at = t + timedelta(minutes=CTAS_REASSESS_MIN[enc.current_ctas])
        arm.on_deteriorated(enc)
        self._emit(EventType.PATIENT_DETERIORATED, t, {
            "encounter_id": str(enc.encounter_id),
            "patient_id": str(enc.patient_id),
            "previous_ctas": previous,
            "current_ctas": enc.current_ctas,
            "assigned_ctas": enc.assigned_ctas,
            "wait_min": round(enc.wait_minutes(t), 1),
            "vitals": enc.vitals.as_dict(),
        }, arm=enc.arm)

    def _recheck_vitals(self, s: Session, arm: EDArm, enc: ActiveEncounter,
                        t: datetime) -> None:
        enc.vitals = self.generator.recheck_vitals(enc.presentation, enc.vitals, enc.deteriorated,
                                                   enc.rng)
        self._record_vitals(s, enc, t)
        # Reassessment cadence follows the acuity the ED believes the patient has.
        level = enc.assigned_ctas or enc.current_ctas
        enc.next_vitals_at = t + timedelta(minutes=CTAS_REASSESS_MIN[level])
        arm.on_reassessment(s, enc, t)

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
