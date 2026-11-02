import dataclasses
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from er_triage.db import ping, session_scope
from er_triage.events import EventBus
from er_triage.models import Arm, Encounter, EncounterStatus, Lane, SimRun
from er_triage.sim.ed import EDConfig
from er_triage.sim.feed import FeedEngine
from er_triage.sim.triage import RulesTriager, vitals_level
from er_triage.sim.generator import Vitals

START = datetime(2026, 11, 6, 8, 0, tzinfo=UTC)


def _vitals(**kw) -> Vitals:
    base = dict(heart_rate=80, systolic_bp=125, diastolic_bp=80, resp_rate=16, spo2=98,
                temp_c=37.0, pain_score=1, gcs=15)
    return Vitals(**{**base, **kw})


def test_vitals_modifiers():
    assert vitals_level(_vitals())[0] == 5
    assert vitals_level(_vitals(pain_score=5))[0] == 4
    assert vitals_level(_vitals(heart_rate=105))[0] == 3
    assert vitals_level(_vitals(spo2=90))[0] == 2
    level, reasons = vitals_level(_vitals(systolic_bp=75))
    assert level == 1 and reasons == ["SBP 75"]


@pytest.fixture
def db():
    try:
        ping()
    except Exception:
        pytest.skip("postgres not available")


def _run(hours: int, seed: int, ai_config: EDConfig | None = None) -> FeedEngine:
    engine = FeedEngine(EventBus([]), sim_start=START, seed=seed)
    if ai_config is not None:
        arm = engine.arms[Arm.AI]
        arm.config = ai_config
        arm.capacity[Lane.INTAKE] = ai_config.intake_chairs
    engine.create_run()
    t = START
    while t < START + timedelta(hours=hours):
        t += timedelta(minutes=10)
        engine.step(t)
    return engine


def _cleanup(*engines: FeedEngine) -> None:
    with session_scope() as s:
        for e in engines:
            s.delete(s.get(SimRun, e.run_id))


def test_arms_are_independent(db):
    """Changing only the AI arm must not change a single baseline outcome."""
    a = _run(12, seed=11)
    b = _run(12, seed=11, ai_config=dataclasses.replace(EDConfig(), intake_mode="off"))
    try:
        def baseline(e):
            with session_scope() as s:
                rows = s.execute(
                    select(Encounter.arrived_at, Encounter.assigned_ctas,
                           Encounter.physician_seen_at, Encounter.status)
                    .where(Encounter.run_id == e.run_id, Encounter.arm == Arm.BASELINE)
                    .order_by(Encounter.arrived_at)
                ).all()
            return [tuple(r) for r in rows]

        assert baseline(a) == baseline(b)
        assert a.arms[Arm.BASELINE].counters.seen == b.arms[Arm.BASELINE].counters.seen
    finally:
        _cleanup(a, b)


def test_flow_invariants(db):
    engine = _run(18, seed=5)
    try:
        cfg = engine.ed_config
        with session_scope() as s:
            rows = s.scalars(select(Encounter).where(Encounter.run_id == engine.run_id)).all()
            for enc in rows:
                if enc.triaged_at:
                    assert enc.triaged_at >= enc.arrived_at
                if enc.physician_seen_at:
                    assert enc.triaged_at is not None
                    assert enc.physician_seen_at >= enc.triaged_at
                    assert enc.lane is not None
                if enc.departed_at and enc.status != EncounterStatus.LWBS:
                    assert enc.physician_seen_at <= enc.departed_at
                if enc.status == EncounterStatus.LWBS:
                    assert enc.physician_seen_at is None
        for arm in engine.arms.values():
            # Recognized resuscitation cases are seen almost immediately.
            for rec in arm.counters.waits:
                if rec.arrival_ctas == 1:
                    assert rec.wait_min < 10
            limit = cfg.main_beds + cfg.hallway_spaces + 2  # + resus overflow
            assert arm.occupied(Lane.MAIN, engine._last_tick) <= limit
            assert arm.occupied(Lane.FAST_TRACK, engine._last_tick) <= cfg.fast_track_chairs
    finally:
        _cleanup(engine)


def test_rules_triager_flags_abnormal_vitals():
    from er_triage.sim.generator import PatientGenerator

    gen = PatientGenerator(seed=1)
    patient = gen.new_patient(START)
    decision = RulesTriager().assess(patient, _vitals(spo2=84), patient.presentation.ctas, 0)
    assert decision.ctas == 1 and "SpO2 84%" in decision.red_flags


def test_stream_independent_of_step_timing(db):
    """Irregular wall-clock ticks must yield exactly the same simulation."""
    import random as _random

    def run(step_sizes):
        engine = FeedEngine(EventBus([]), sim_start=START, seed=21)
        engine.create_run()
        t = START
        while t < START + timedelta(hours=6):
            t += timedelta(seconds=next(step_sizes))
            engine.step(t)
        engine.step(START + timedelta(hours=6))
        with session_scope() as s:
            rows = s.execute(
                select(Encounter.arm, Encounter.arrived_at, Encounter.physician_seen_at)
                .where(Encounter.run_id == engine.run_id)
                .order_by(Encounter.arm, Encounter.arrived_at)
            ).all()
        return engine, [tuple(r) for r in rows]

    rng = _random.Random(0)
    a, rows_a = run(iter(lambda: 600, None))
    b, rows_b = run(iter(lambda: rng.uniform(5, 400), None))
    try:
        assert rows_a and rows_a == rows_b
    finally:
        _cleanup(a, b)


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, datetime]] = []

    def emit(self, event_type, data, *, sim_time, run_id, arm) -> None:
        self.events.append((str(event_type), sim_time))


def test_warm_up_opens_loaded_and_counts_from_opening(db):
    """Warm-up carries patients over but not KPIs, publishes nothing, and
    leaves the ED in exactly the state a plain run reaches."""
    bus = _Recorder()
    warm = FeedEngine(bus, sim_start=START, seed=5, arrival_multiplier=1.5)
    summary = warm.warm_up(30)
    plain = FeedEngine(EventBus([]), sim_start=START, seed=5)  # warm-up ignores surge
    plain.create_run()
    plain.step(START + timedelta(hours=30))
    try:
        opens = START + timedelta(hours=30)
        assert warm.clock.start == opens and warm.processed_until == opens
        assert warm.arrival_multiplier == 1.5
        assert bus.events == [("run.started", opens)]
        for arm in Arm:
            ed = warm.arms[arm]
            assert ed.encounters and summary["in_ed"][arm.value] == len(ed.encounters)
            assert ed.counters.seen == 0 and not ed.counters.waits
            assert plain.arms[arm].counters.seen > 0
            assert ({e.patient.mrn: e.status for e in ed.encounters.values()}
                    == {e.patient.mrn: e.status for e in plain.arms[arm].encounters.values()})
        with session_scope() as s:
            assert s.get(SimRun, warm.run_id).config["warmup"]["hours"] == 30
    finally:
        _cleanup(warm, plain)


class _AlwaysAdmit(RulesTriager):
    def assess(self, patient, vitals, true_ctas, waiting_load):
        d = super().assess(patient, vitals, true_ctas, waiting_load)
        d.admit_predicted = True
        return d


def test_early_bed_request_shortens_boarding_for_true_admissions(db):
    engine = FeedEngine(EventBus([]), sim_start=START, seed=8, ai_triager=_AlwaysAdmit())
    engine.create_run()
    engine.step(START + timedelta(hours=24))
    try:
        ai, base = engine.arms[Arm.AI].counters, engine.arms[Arm.BASELINE].counters
        assert ai.admit_true_pos > 0 and ai.admit_false_pos > 0 and ai.admit_false_neg == 0
        # Only correctly predicted admissions save time, at most 60 min each.
        assert 0 < ai.boarding_saved_min <= 60 * ai.admit_true_pos
        assert base.boarding_saved_min == 0 and base.admit_true_pos == 0  # nurse: no prediction
    finally:
        _cleanup(engine)
