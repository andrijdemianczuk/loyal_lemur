import random
import time
from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from er_triage.db import ping, session_scope
from er_triage.events import EventBus
from er_triage.models import Encounter, Patient, SimRun, VitalSigns
from er_triage.sim.catalog import CATALOG, CTAS_MIX, NORMAL_VITALS
from er_triage.sim.clock import SimClock
from er_triage.sim.feed import FeedEngine
from er_triage.sim.generator import PatientGenerator

START = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)


def test_catalog_integrity():
    codes = [p.code for p in CATALOG]
    assert len(codes) == len(set(codes))
    for p in CATALOG:
        assert 1 <= p.ctas <= 5 and p.weight > 0 and p.history and p.notes
        assert set(p.vitals) <= set(NORMAL_VITALS), p.code
        for lo, hi in p.vitals.values():
            assert lo <= hi, p.code
    assert {p.ctas for p in CATALOG} == {1, 2, 3, 4, 5}


def test_daily_volume_and_ctas_mix():
    gen = PatientGenerator(seed=7, daily_volume=150)
    days = 20
    # Sample hour by hour, like the engine's ticks, so the time-of-day curve applies.
    times = [
        t for h in range(days * 24)
        for t in gen.sample_arrival_times(START + timedelta(hours=h),
                                          START + timedelta(hours=h + 1))
    ]
    assert 140 * days < len(times) < 160 * days

    mix = Counter(gen.new_patient(START).presentation.ctas for _ in range(5000))
    for level, share in CTAS_MIX.items():
        assert abs(mix[level] / 5000 - share) < 0.02, level


def test_night_is_quieter_than_day():
    gen = PatientGenerator(seed=1)
    night = gen.arrivals_per_minute(START.replace(hour=4))
    day = gen.arrivals_per_minute(START.replace(hour=11))
    assert day > 3 * night


def test_same_seed_same_arrivals():
    def arrivals(rechecks: int):
        gen = PatientGenerator(seed=99)
        out = []
        for h in range(12):
            for t in gen.sample_arrival_times(START + timedelta(hours=h),
                                              START + timedelta(hours=h + 1)):
                p = gen.new_patient(t)
                for _ in range(rechecks):
                    gen.recheck_vitals(p.presentation, p.vitals, False, random.Random(p.vitals_seed))
                out.append((t, p.mrn, p.presentation.code, p.last_name))
        return out

    assert arrivals(0) == arrivals(5)


def test_clock_speed_pause_resume():
    clock = SimClock(START, speed=600)  # 0.05 s real -> ~30 sim minutes
    time.sleep(0.05)
    assert timedelta(minutes=20) < clock.now() - START < timedelta(minutes=60)
    clock.pause()
    frozen = clock.now()
    time.sleep(0.02)
    assert clock.now() == frozen
    clock.resume()
    clock.set_speed(1)
    assert clock.now() - frozen < timedelta(seconds=5)


@pytest.fixture
def db():
    try:
        ping()
    except Exception:
        pytest.skip("postgres not available")


def test_feed_engine_populates_both_arms(db):
    engine = FeedEngine(EventBus([]), sim_start=START.replace(hour=8), seed=3)
    run_id = engine.create_run()
    try:
        for minutes in range(10, 6 * 60 + 1, 10):
            engine.step(engine.clock.start + timedelta(minutes=minutes))

        with session_scope() as s:
            n_patients = s.scalar(select(func.count()).where(Patient.run_id == run_id))
            per_arm = dict(s.execute(
                select(Encounter.arm, func.count()).where(Encounter.run_id == run_id)
                .group_by(Encounter.arm)
            ).all())
            n_vitals = s.scalar(
                select(func.count()).select_from(VitalSigns).join(Encounter)
                .where(Encounter.run_id == run_id)
            )
        assert n_patients > 15
        assert per_arm == {"ai": n_patients, "baseline": n_patients}
        assert n_vitals > 2 * n_patients  # initial + reassessments
        assert engine.bus.stats.emitted > n_patients
    finally:
        with session_scope() as s:
            s.delete(s.get(SimRun, run_id))


def test_clock_pause_at_exact_time():
    clock = SimClock(START, speed=60)
    target = START + timedelta(hours=3)
    clock.pause_at(target)
    assert clock.paused and clock.now() == target
    clock.set_speed(2)
    assert clock.now() == target
