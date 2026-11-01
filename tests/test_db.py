from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from er_triage.db import ping, session_scope
from er_triage.models import Arm, ArrivalMode, Encounter, Patient, SimRun


@pytest.fixture
def run():
    try:
        ping()
    except Exception:
        pytest.skip("postgres not available")
    with session_scope() as s:
        sim_run = SimRun(sim_start_at=datetime(2026, 11, 6, 8, tzinfo=UTC), scenario="test")
        s.add(sim_run)
    yield sim_run
    with session_scope() as s:
        s.delete(s.get(SimRun, sim_run.id))


def test_patient_has_encounter_per_arm(run):
    arrived = datetime(2026, 11, 6, 8, 5, tzinfo=UTC)
    with session_scope() as s:
        p = Patient(
            run_id=run.id, mrn="M0001", health_card_no="1234-567-890", first_name="Test",
            last_name="Patient", date_of_birth=date(1970, 1, 1), sex="F", postal_code="T2P 1J9",
            arrival_mode=ArrivalMode.WALK_IN, arrived_at=arrived, chief_complaint="chest pain",
            true_ctas=2,
        )
        p.encounters = [Encounter(run_id=run.id, arm=arm, arrived_at=arrived) for arm in Arm]
        s.add(p)

    with session_scope() as s:
        arms = s.scalars(select(Encounter.arm).where(Encounter.run_id == run.id)).all()
    assert sorted(arms) == ["ai", "baseline"]
