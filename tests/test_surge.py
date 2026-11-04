from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from er_triage.db import ping, session_scope
from er_triage.events import EventBus
from er_triage.models import Arm, Encounter, Patient, SimRun
from er_triage.sim.catalog import CATALOG
from er_triage.sim.feed import FeedEngine
from er_triage.sim.generator import PatientGenerator
from er_triage.sim.surge import BY_CODE, PRESETS, SurgeSchedule

OPENS = datetime(2026, 11, 6, 14, 0, tzinfo=UTC)


def test_preset_codes_exist():
    for p in PRESETS.values():
        assert set(p.manifest) <= set(BY_CODE)
        assert {code for code, _ in p.mix} <= set(BY_CODE)
        assert set(p.notes) <= set(p.manifest)


def test_surge_counts_are_fixed_and_inside_the_window():
    for seed in (1, 5, 8):
        for key, preset in PRESETS.items():
            sched = SurgeSchedule(preset, OPENS, seed, PatientGenerator(seed))
            expected = {"evening-rush": 12, "mvc": 8, "flu-wave": 12}[key]
            assert sched.planned == expected, (key, seed)
            start, end = sched.window
            patients = sched.arrivals(start, end + timedelta(hours=1))
            assert len(patients) == expected
            assert all(start <= p.arrived_at < end for p in patients)
            assert all(p.mrn.startswith("S") for p in patients)


def test_window_is_clipped_to_opening():
    late = OPENS.replace(hour=19)
    sched = SurgeSchedule(PRESETS["evening-rush"], late, 3, PatientGenerator(3))
    assert sched.window[0] == late
    assert 0 < sched.planned < 12
    after = OPENS.replace(hour=22)
    assert SurgeSchedule(PRESETS["evening-rush"], after, 3, PatientGenerator(3)).planned == 0


def test_collision_manifest_is_coherent():
    sched = SurgeSchedule(PRESETS["mvc"], OPENS, 8, PatientGenerator(8))
    patients = sched.arrivals(OPENS, OPENS + timedelta(hours=12))
    assert sorted(p.presentation.code for p in patients) == sorted(PRESETS["mvc"].manifest)
    assert all(p.arrival_mode == "ambulance" for p in patients)
    for p in patients:
        if p.presentation.code != "L1_MAJOR_TRAUMA":
            assert "collision" in p.triage_note


def test_respiratory_wave_uses_its_mix():
    sched = SurgeSchedule(PRESETS["flu-wave"], OPENS, 2, PatientGenerator(2))
    codes = {p.presentation.code for p in sched.arrivals(OPENS, OPENS + timedelta(hours=12))}
    assert codes <= {code for code, _ in PRESETS["flu-wave"].mix}


def test_overrides_off_reproduce_a_normal_patient():
    a, b = PatientGenerator(4), PatientGenerator(4)
    t = OPENS
    for _ in range(20):
        pa, pb = a.new_patient(t), b.new_patient(t, presentation=None, ambulance=None, notes=None)
        assert (pa.mrn, pa.presentation.code, pa.triage_note, pa.arrival_mode, pa.vitals_seed) == (
            pb.mrn, pb.presentation.code, pb.triage_note, pb.arrival_mode, pb.vitals_seed)
    assert CATALOG  # catalog loaded


@pytest.fixture
def db():
    try:
        ping()
    except Exception:
        pytest.skip("postgres not available")


def _patients(engine: FeedEngine) -> list[tuple]:
    with session_scope() as s:
        rows = s.execute(
            select(Patient.mrn, Patient.first_name, Encounter.arrived_at)
            .join(Encounter, Encounter.patient_id == Patient.id)
            .where(Encounter.run_id == engine.run_id, Encounter.arm == Arm.BASELINE)
            .order_by(Encounter.arrived_at, Patient.mrn)
        ).all()
    return [tuple(r) for r in rows]


def test_surge_adds_patients_without_changing_the_normal_day(db):
    engines = []
    try:
        for preset in (None, PRESETS["evening-rush"]):
            e = FeedEngine(EventBus([]), sim_start=OPENS - timedelta(hours=6), seed=7,
                           surge=preset, opens_at=OPENS)
            engines.append(e)
            e.warm_up(6)
            e.step(OPENS + timedelta(hours=10))
        normal, surged = (_patients(e) for e in engines)
        assert [p for p in surged if p[0].startswith("M")] == normal
        assert sum(p[0].startswith("S") for p in surged) == 12
    finally:
        with session_scope() as s:
            for e in engines:
                s.delete(s.get(SimRun, e.run_id))
