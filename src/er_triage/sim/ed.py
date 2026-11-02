"""One emergency department "arm": triage, queueing, physicians, beds.

Both arms get identical resources (main physicians and beds, a fast track
with its own physician and chairs, triage nurses). They differ only in their
``Triager`` and ``QueuePolicy``:

- baseline: nurse triage, strict CTAS then first-come-first-served,
  fast track takes assigned CTAS 4-5.
- AI: decision-support triage, SLO-aware ordering (CTAS 1-2 strictly first,
  then whoever is closest to breaching their CTAS target, with a guard for
  walk-ins approaching the 4h SLO), and smarter fast-track streaming.

Performance is always judged against the patient's *true* acuity (including
deterioration), never the level the arm assigned.
"""

import random
import statistics
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlalchemy.orm import Session

from er_triage.events import EventType
from er_triage.models import (
    Arm,
    ArrivalMode,
    Encounter,
    EncounterStatus,
    Lane,
    MetricSnapshot,
    TriageAssessment,
)
from er_triage.sim.catalog import (
    CTAS_REASSESS_MIN,
    WALK_IN_SLO_MIN,
    Presentation,
    effective_target_min,
)
from er_triage.sim.generator import NewPatient, Vitals
from er_triage.sim.triage import TriageDecision, Triager

WAITING = {EncounterStatus.WAITING_TRIAGE, EncounterStatus.WAITING_PHYSICIAN}
DONE = {EncounterStatus.DISCHARGED, EncounterStatus.ADMITTED, EncounterStatus.LWBS}

Emit = Callable[..., None]


@dataclass
class EDConfig:
    main_physicians: int = 5
    main_beds: int = 20
    # Over-capacity protocol: hallway stretchers for assigned CTAS 1-2 only.
    hallway_spaces: int = 4
    fast_track_physicians: int = 1
    fast_track_chairs: int = 4
    fast_track_hours: tuple[int, int] = (9, 23)  # open [start, end) local hour
    triage_nurses: int = 2
    triage_min: tuple[float, float] = (3, 8)
    # Fast-track patients needing longer workup move to an internal results
    # area rather than holding a chair.
    fast_track_chair_max_min: float = 60
    # Rapid assessment zone: idle main physicians assess stable walk-ins in
    # intake chairs. "scheduled" opens it during fixed hours (typical static
    # policy); "dynamic" opens it whenever there are idle physicians and
    # waiting walk-ins (decision-support recommendation); "off" disables it.
    intake_chairs: int = 2
    intake_mode: str = "scheduled"
    intake_hours: tuple[int, int] = (11, 21)
    # Internal results-waiting area shared by fast track and intake patients
    # whose workup outlasts their chair time. When full, those lanes stall.
    results_area_capacity: int = 8
    deteriorated_treatment_factor: float = 1.5
    slo_guard_min: float = 180  # AI policy: escalate walk-ins waiting this long


@dataclass
class ActiveEncounter:
    """Working state for one patient in one arm."""

    encounter_id: uuid.UUID
    patient_id: uuid.UUID
    arm: Arm
    patient: NewPatient
    current_ctas: int  # true acuity, including deterioration
    vitals: Vitals
    next_vitals_at: datetime
    status: EncounterStatus = EncounterStatus.WAITING_TRIAGE
    assigned_ctas: int | None = None
    initial_assigned_ctas: int | None = None
    priority_score: float | None = None
    lane: Lane | None = None
    fast_track_hint: bool | None = None
    triage_done_at: datetime | None = None
    seen_at: datetime | None = None
    resource_free_at: datetime | None = None  # bed/chair released
    depart_at: datetime | None = None
    admitted: bool = False
    hazard: float = 0.0
    deteriorated: bool = False
    slo_breached: bool = False
    rng: random.Random = field(init=False)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.patient.vitals_seed)

    @property
    def presentation(self) -> Presentation:
        return self.patient.presentation

    @property
    def arrived_at(self) -> datetime:
        return self.patient.arrived_at

    @property
    def walk_in(self) -> bool:
        return self.patient.arrival_mode == ArrivalMode.WALK_IN

    def wait_minutes(self, now: datetime) -> float:
        end = self.seen_at or now
        return (end - self.arrived_at).total_seconds() / 60


class QueuePolicy(Protocol):
    name: str

    def key(self, enc: ActiveEncounter, now: datetime) -> tuple[float, ...]: ...

    def lane(self, enc: ActiveEncounter) -> Lane: ...


class CtasFifoPolicy:
    """Standard practice: assigned CTAS, then arrival order."""

    name = "ctas-fifo"

    def key(self, enc, now):
        return (enc.assigned_ctas, enc.arrived_at.timestamp())

    def lane(self, enc):
        return Lane.FAST_TRACK if enc.assigned_ctas >= 4 else Lane.MAIN


class SloAwarePolicy:
    """CTAS 1-2 strictly first; then walk-ins nearing the 4h SLO; then
    everyone else by fraction of their CTAS target already elapsed."""

    name = "slo-aware"

    def __init__(self, slo_guard_min: float) -> None:
        self.slo_guard_min = slo_guard_min

    def key(self, enc, now):
        level = enc.assigned_ctas
        if level <= 2:
            return (0.0, float(level), enc.arrived_at.timestamp())
        wait = enc.wait_minutes(now)
        if enc.walk_in and wait >= self.slo_guard_min:
            return (1.0, -wait, 0.0)
        return (2.0, -wait / effective_target_min(level), 0.0)

    def lane(self, enc):
        if enc.fast_track_hint is not None:
            return Lane.FAST_TRACK if enc.fast_track_hint else Lane.MAIN
        # Stream stable, ambulatory CTAS 3 walk-ins under 65 to fast track too.
        if enc.assigned_ctas >= 4:
            return Lane.FAST_TRACK
        if (enc.assigned_ctas == 3 and enc.walk_in and enc.patient.age < 65
                and not enc.deteriorated):
            return Lane.FAST_TRACK
        return Lane.MAIN


@dataclass
class WaitRecord:
    """A completed wait: seen by a physician, or left without being seen.
    Walk-outs are kept so an ED can't look faster by losing patients."""

    at: datetime
    wait_min: float
    arrival_ctas: int  # true acuity on arrival
    current_ctas: int  # true acuity at the end of the wait
    walk_in: bool
    left: bool = False


@dataclass
class ArmCounters:
    seen: int = 0
    slo_breaches: int = 0
    target_misses: int = 0
    under_triaged: int = 0
    deteriorations: int = 0
    lwbs: int = 0
    ai_late_applied: int = 0
    ai_late_dropped: int = 0  # arrived after the patient was already seen or gone
    waits: list[WaitRecord] = field(default_factory=list)


class EDArm:
    def __init__(
        self,
        arm: Arm,
        triager: Triager,
        policy: QueuePolicy,
        config: EDConfig,
        emit: Emit,
    ) -> None:
        self.arm = arm
        self.triager = triager
        self.policy = policy
        self.config = config
        self._emit = emit
        self.encounters: dict[uuid.UUID, ActiveEncounter] = {}
        self.physician_free_at: dict[Lane, list[datetime | None]] = {
            Lane.MAIN: [None] * config.main_physicians,
            Lane.FAST_TRACK: [None] * config.fast_track_physicians,
        }
        self.capacity = {
            Lane.MAIN: config.main_beds,
            Lane.FAST_TRACK: config.fast_track_chairs,
            Lane.INTAKE: config.intake_chairs,
        }
        self.counters = ArmCounters()

    def reset_counters(self) -> None:
        """Start KPI counting afresh (after a warm-up); patients stay put."""
        self.counters = ArmCounters()

    # -- views -------------------------------------------------------------

    def by_status(self, *statuses: EncounterStatus) -> list[ActiveEncounter]:
        return [e for e in self.encounters.values() if e.status in statuses]

    def occupied(self, lane: Lane, t: datetime) -> int:
        return sum(1 for e in self.encounters.values()
                   if e.status == EncounterStatus.IN_TREATMENT and e.lane == lane
                   and e.resource_free_at > t)

    def fast_track_open(self, t: datetime) -> bool:
        start, end = self.config.fast_track_hours
        return start <= t.hour < end

    def intake_open(self, t: datetime) -> bool:
        match self.config.intake_mode:
            case "dynamic":
                return self.config.intake_chairs > 0
            case "scheduled":
                start, end = self.config.intake_hours
                return self.config.intake_chairs > 0 and start <= t.hour < end
            case _:
                return False

    def results_area_occupied(self, t: datetime) -> int:
        return sum(1 for e in self.encounters.values()
                   if e.status == EncounterStatus.IN_TREATMENT
                   and e.lane in (Lane.FAST_TRACK, Lane.INTAKE)
                   and e.resource_free_at <= t < e.depart_at)

    # -- lifecycle hooks called by the feed engine -------------------------

    def admit(self, enc: ActiveEncounter) -> None:
        self.encounters[enc.encounter_id] = enc

    def on_deteriorated(self, enc: ActiveEncounter) -> None:
        self.counters.deteriorations += 1

    def on_reassessment(self, s: Session, enc: ActiveEncounter, t: datetime) -> None:
        if enc.status != EncounterStatus.WAITING_PHYSICIAN:
            return
        decision = self.triager.reassess(enc.patient, enc.vitals, enc.assigned_ctas,
                                         enc.current_ctas)
        if decision is not None:
            self.apply_assessment(s, enc, decision, t)

    def apply_assessment(self, s: Session, enc: ActiveEncounter, decision: TriageDecision,
                         t: datetime) -> None:
        """Record a triage decision and (re)place the patient in a lane."""
        first = enc.assigned_ctas is None
        previous = enc.assigned_ctas
        enc.assigned_ctas = decision.ctas
        enc.priority_score = decision.priority_score
        if decision.fast_track is not None:
            enc.fast_track_hint = decision.fast_track
        if first:
            enc.initial_assigned_ctas = decision.ctas
            if decision.ctas > enc.current_ctas:
                self.counters.under_triaged += 1
        if enc.status == EncounterStatus.WAITING_TRIAGE:
            enc.status = EncounterStatus.WAITING_PHYSICIAN
        enc.lane = self.policy.lane(enc)
        enc.next_vitals_at = min(enc.next_vitals_at,
                                 t + timedelta(minutes=CTAS_REASSESS_MIN[decision.ctas]))

        row = s.get(Encounter, enc.encounter_id)
        row.assigned_ctas = decision.ctas
        row.priority_score = decision.priority_score
        row.status = enc.status
        row.lane = enc.lane
        if first:
            row.triaged_at = t
        self._record_assessment(s, enc, decision, t, applied=True, previous=previous,
                                first=first)

    def _record_assessment(self, s: Session, enc: ActiveEncounter, decision: TriageDecision,
                           t: datetime, *, applied: bool, previous: int | None = None,
                           first: bool = False) -> None:
        s.add(TriageAssessment(
            encounter_id=enc.encounter_id, source=decision.source, assessed_at=t,
            ctas_level=decision.ctas, priority_score=decision.priority_score,
            rationale=decision.rationale, red_flags=decision.red_flags, model=decision.model,
            latency_ms=decision.latency_ms, input_tokens=decision.input_tokens,
            output_tokens=decision.output_tokens, applied=applied,
        ))
        self._emit(EventType.TRIAGE_ASSESSED, t, {
            "encounter_id": str(enc.encounter_id),
            "patient_id": str(enc.patient_id),
            "source": decision.source,
            "ctas": decision.ctas,
            "previous_ctas": previous if applied else enc.assigned_ctas,
            "reassessment": not first,
            "applied": applied,
            "lane": enc.lane,
            "rationale": decision.rationale,
            "red_flags": decision.red_flags,
            "model": decision.model,
        }, arm=self.arm)

    # -- simulation step ----------------------------------------------------

    def step(self, s: Session, t: datetime) -> None:
        self._apply_late_decisions(s, t)
        self._finish_triage(s, t)
        self._start_triage(t)
        self._discharge(s, t)
        self._walkouts(s, t)
        self._assign_physicians(s, t)
        self._check_slo(t)

    def _finish_triage(self, s: Session, t: datetime) -> None:
        for enc in self.by_status(EncounterStatus.WAITING_TRIAGE):
            if enc.triage_done_at is not None and enc.triage_done_at <= t:
                waiting = len(self.by_status(*WAITING))
                decision = self.triager.assess(enc.patient, enc.vitals, enc.current_ctas,
                                               waiting)
                self.apply_assessment(s, enc, decision, enc.triage_done_at)

    def _start_triage(self, t: datetime) -> None:
        queue = [e for e in self.by_status(EncounterStatus.WAITING_TRIAGE)
                 if e.triage_done_at is None]
        # Resuscitation cases bypass the triage desk.
        for enc in queue:
            if enc.current_ctas == 1:
                enc.triage_done_at = enc.arrived_at
        busy = sum(1 for e in self.by_status(EncounterStatus.WAITING_TRIAGE)
                   if e.triage_done_at is not None and e.triage_done_at > t)
        queue = sorted((e for e in queue if e.triage_done_at is None),
                       key=lambda e: (e.walk_in, e.arrived_at))  # ambulance first
        for enc in queue[: max(0, self.config.triage_nurses - busy)]:
            start = max(t, enc.arrived_at)
            enc.triage_done_at = start + timedelta(
                minutes=_draw(enc, "triage", *self.config.triage_min))
            # Decision support starts working as the patient reaches the desk.
            if prefetch := getattr(self.triager, "prefetch", None):
                prefetch(enc.patient, enc.vitals)

    def _apply_late_decisions(self, s: Session, t: datetime) -> None:
        """Apply AI decisions that arrived after a provisional triage."""
        completed = getattr(self.triager, "completed", None)
        if completed is None:
            return
        by_mrn = {e.patient.mrn: e for e in self.encounters.values()}
        for mrn, decision in completed():
            enc = by_mrn.get(mrn)
            if enc is not None and enc.status == EncounterStatus.WAITING_PHYSICIAN:
                self.counters.ai_late_applied += 1
                self.apply_assessment(s, enc, decision, t)
            else:
                # Too late to change care, but keep it for audit and review.
                self.counters.ai_late_dropped += 1
                if enc is not None:
                    self._record_assessment(s, enc, decision, t, applied=False)

    def _discharge(self, s: Session, t: datetime) -> None:
        for enc in self.by_status(EncounterStatus.IN_TREATMENT):
            if enc.depart_at <= t:
                status = EncounterStatus.ADMITTED if enc.admitted else EncounterStatus.DISCHARGED
                self._depart(s, enc, status, enc.depart_at)

    def _walkouts(self, s: Session, t: datetime) -> None:
        for enc in self.by_status(*WAITING):
            if enc.walk_in and enc.wait_minutes(t) > enc.patient.patience_min:
                self.counters.lwbs += 1
                self.counters.target_misses += (
                    enc.wait_minutes(t) > effective_target_min(enc.current_ctas))
                self.counters.waits.append(WaitRecord(
                    t, enc.wait_minutes(t), enc.presentation.ctas, enc.current_ctas,
                    enc.walk_in, left=True))
                self._depart(s, enc, EncounterStatus.LWBS, t)

    def _depart(self, s: Session, enc: ActiveEncounter, status: EncounterStatus,
                t: datetime) -> None:
        enc.status = status
        row = s.get(Encounter, enc.encounter_id)
        row.status = status
        row.departed_at = t
        del self.encounters[enc.encounter_id]
        self._emit(EventType.PATIENT_DEPARTED, t, {
            "encounter_id": str(enc.encounter_id),
            "patient_id": str(enc.patient_id),
            "disposition": status,
            "length_of_stay_min": round((t - enc.arrived_at).total_seconds() / 60, 1),
            "true_ctas": enc.current_ctas,
            "assigned_ctas": enc.assigned_ctas,
        }, arm=self.arm)

    def _assign_physicians(self, s: Session, t: datetime) -> None:
        waiting = self.by_status(EncounterStatus.WAITING_PHYSICIAN)
        # Recognized resuscitation cases go straight to resus with the team,
        # regardless of bed or physician availability.
        for enc in [e for e in waiting if e.assigned_ctas == 1]:
            self._see(s, enc, Lane.MAIN, t)
            doctors = self.physician_free_at[Lane.MAIN]
            doc = min(range(len(doctors)), key=lambda i: doctors[i] or t)
            doctors[doc] = max(doctors[doc] or t, t) + timedelta(minutes=enc.patient.assess_min)
        waiting = [e for e in waiting if e.status == EncounterStatus.WAITING_PHYSICIAN]
        ft_open = self.fast_track_open(t)
        main_q = [e for e in waiting if e.lane == Lane.MAIN or not ft_open]
        fast_q = [e for e in waiting if e.lane == Lane.FAST_TRACK and ft_open]
        if ft_open:
            self._fill(s, t, Lane.FAST_TRACK, fast_q)
        # Main takes overflow from fast track only when its own queue is empty.
        if not main_q:
            main_q = [e for e in fast_q if e.status == EncounterStatus.WAITING_PHYSICIAN]
        self._fill(s, t, Lane.MAIN, main_q)
        if self.intake_open(t):
            intake_q = [e for e in waiting
                        if e.status == EncounterStatus.WAITING_PHYSICIAN and e.walk_in
                        and e.assigned_ctas >= 3 and not e.deteriorated]
            self._fill(s, t, Lane.INTAKE, intake_q, doctors=self.physician_free_at[Lane.MAIN])

    def _fill(self, s: Session, t: datetime, lane: Lane, queue: list[ActiveEncounter],
              doctors: list[datetime | None] | None = None) -> None:
        queue = sorted(queue, key=lambda e: self.policy.key(e, t))
        doctors = doctors if doctors is not None else self.physician_free_at[lane]
        for enc in queue:
            doc = next((i for i, f in enumerate(doctors) if f is None or f <= t), None)
            if doc is None:
                return
            emergent = lane == Lane.MAIN and enc.assigned_ctas <= 2
            capacity = self.capacity[lane] + (self.config.hallway_spaces if emergent else 0)
            if self.occupied(lane, t) >= capacity:
                if emergent:
                    continue
                return
            if (lane != Lane.MAIN
                    and self.results_area_occupied(t) >= self.config.results_area_capacity):
                return
            self._see(s, enc, lane, t)
            doctors[doc] = t + timedelta(minutes=enc.patient.assess_min)

    def _see(self, s: Session, enc: ActiveEncounter, lane: Lane, t: datetime) -> None:
        p = enc.patient
        enc.status = EncounterStatus.IN_TREATMENT
        enc.lane = lane
        enc.seen_at = t
        enc.admitted = p.admitted or enc.deteriorated
        treatment = max(p.treatment_min, p.assess_min)
        if enc.deteriorated:
            treatment *= self.config.deteriorated_treatment_factor
        boarding = p.boarding_min if p.admitted else (90.0 if enc.admitted else 0.0)
        enc.depart_at = t + timedelta(minutes=treatment + boarding)
        if lane in (Lane.FAST_TRACK, Lane.INTAKE):
            chair = min(treatment, self.config.fast_track_chair_max_min)
            enc.resource_free_at = t + timedelta(minutes=chair)
        else:
            enc.resource_free_at = enc.depart_at

        wait = enc.wait_minutes(t)
        target = effective_target_min(enc.current_ctas)
        c = self.counters
        c.seen += 1
        c.target_misses += wait > target
        c.waits.append(WaitRecord(t, wait, enc.presentation.ctas, enc.current_ctas,
                                  enc.walk_in))

        row = s.get(Encounter, enc.encounter_id)
        row.status = enc.status
        row.lane = lane
        row.physician_seen_at = t
        self._emit(EventType.PHYSICIAN_ASSIGNED, t, {
            "encounter_id": str(enc.encounter_id),
            "patient_id": str(enc.patient_id),
            "lane": lane,
            "wait_min": round(wait, 1),
            "assigned_ctas": enc.assigned_ctas,
            "true_ctas": enc.current_ctas,
            "target_min": target,
            "target_met": wait <= target,
            "arrival_mode": p.arrival_mode,
        }, arm=self.arm)

    def _check_slo(self, t: datetime) -> None:
        for enc in self.by_status(*WAITING):
            if enc.walk_in and not enc.slo_breached and enc.wait_minutes(t) >= WALK_IN_SLO_MIN:
                enc.slo_breached = True
                self.counters.slo_breaches += 1
                self._emit(EventType.SLO_BREACH, t, {
                    "encounter_id": str(enc.encounter_id),
                    "patient_id": str(enc.patient_id),
                    "slo_min": WALK_IN_SLO_MIN,
                    "assigned_ctas": enc.assigned_ctas,
                    "true_ctas": enc.current_ctas,
                }, arm=self.arm)

    # -- metrics ----------------------------------------------------------

    def snapshot(self, s: Session, run_id: uuid.UUID, t: datetime,
                 window_min: float = 60) -> dict[str, Any]:
        """Persist and publish a metrics snapshot."""
        metrics = self.metrics(t, window_min)
        s.add(MetricSnapshot(run_id=run_id, arm=self.arm, sim_time=t, **metrics))
        self._emit(EventType.METRICS_SNAPSHOT, t, metrics, arm=self.arm)
        return metrics

    def metrics(self, t: datetime, window_min: float = 60) -> dict[str, Any]:
        c = self.counters
        recent = [r.wait_min for r in c.waits
                  if (t - r.at).total_seconds() / 60 <= window_min]
        waiting = self.by_status(*WAITING)
        walk_in_waits = [e.wait_minutes(t) for e in waiting if e.walk_in]
        by_ctas: dict[str, dict[str, float]] = {}
        # Grouped by true acuity on arrival; misses are judged against the
        # acuity at the end of the wait, so deteriorating counts as a miss.
        for level in range(1, 6):
            done = [r for r in c.waits if r.arrival_ctas == level]
            waits = [r.wait_min for r in done]
            by_ctas[str(level)] = {
                "waiting": sum(1 for e in waiting if e.presentation.ctas == level),
                "seen": sum(1 for r in done if not r.left),
                "avg_wait_min": round(statistics.fmean(waits), 1) if waits else 0.0,
                "p90_wait_min": round(percentile(waits, 90), 1),
                "target_misses": sum(
                    1 for r in done if r.wait_min > effective_target_min(r.current_ctas)),
            }
        metrics = {
            "waiting": len(waiting),
            "in_treatment": len(self.by_status(EncounterStatus.IN_TREATMENT)),
            "avg_wait_min": round(statistics.fmean(recent), 1) if recent else 0.0,
            "p90_wait_min": round(percentile(recent, 90), 1),
            "max_walk_in_wait_min": round(max(walk_in_waits, default=0.0), 1),
            "slo_breaches": c.slo_breaches,
            "ctas_target_misses": c.target_misses,
            "under_triaged": c.under_triaged,
            "deteriorations": c.deteriorations,
            "lwbs": c.lwbs,
            "seen": c.seen,
            "by_ctas": by_ctas,
        }
        return metrics


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(pct / 100 * len(ordered)) - 1))
    return ordered[idx]


def _draw(enc: ActiveEncounter, salt: str, lo: float, hi: float) -> float:
    """Per-patient draw that is identical in both arms."""
    return random.Random(f"{enc.patient.vitals_seed}:{salt}").uniform(lo, hi)
