"""Synthetic patient and vital-sign generation."""

import math
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from faker import Faker

from er_triage.models import ArrivalMode
from er_triage.sim.catalog import (
    BY_CTAS,
    CTAS_MIX,
    HOURLY_ARRIVAL_FACTOR,
    Presentation,
)


@dataclass
class Vitals:
    heart_rate: int
    systolic_bp: int
    diastolic_bp: int
    resp_rate: int
    spo2: int
    temp_c: float
    pain_score: int
    gcs: int

    def as_dict(self) -> dict[str, float]:
        return dict(self.__dict__)


@dataclass
class NewPatient:
    """Everything known about an arrival at the moment they walk in."""

    presentation: Presentation
    mrn: str
    health_card_no: str
    first_name: str
    last_name: str
    date_of_birth: date
    age: int
    sex: str
    postal_code: str
    arrival_mode: ArrivalMode
    arrived_at: datetime
    history: str
    triage_note: str
    fragility: float  # latent threshold for deterioration; lower = more fragile
    vitals: Vitals


def poisson(rng: random.Random, lam: float) -> int:
    """Knuth's algorithm; fine for the small rates used per tick."""
    if lam <= 0:
        return 0
    threshold, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= threshold:
            return k
        k += 1


class PatientGenerator:
    def __init__(self, seed: int | None = None, daily_volume: float = 150.0) -> None:
        # Separate streams: arrivals must be identical for a given seed no
        # matter how many vitals rechecks each ED arm performs.
        self.rng = random.Random(seed)
        self.vitals_rng = random.Random(None if seed is None else seed + 1)
        self.faker = Faker("en_CA")
        self.faker.seed_instance(seed)
        self.daily_volume = daily_volume
        self._mrn_seq = 0

    def arrivals_per_minute(self, at: datetime, multiplier: float = 1.0) -> float:
        return self.daily_volume / 1440 * HOURLY_ARRIVAL_FACTOR[at.hour] * multiplier

    def sample_arrival_times(
        self, start: datetime, end: datetime, multiplier: float = 1.0
    ) -> list[datetime]:
        """Arrival times in [start, end) from a time-of-day-varying Poisson process."""
        minutes = (end - start).total_seconds() / 60
        if minutes <= 0:
            return []
        lam = self.arrivals_per_minute(start, multiplier) * minutes
        offsets = sorted(self.rng.uniform(0, minutes) for _ in range(poisson(self.rng, lam)))
        return [start + timedelta(minutes=m) for m in offsets]

    def _pick_presentation(self) -> Presentation:
        level = self.rng.choices(list(CTAS_MIX), weights=list(CTAS_MIX.values()))[0]
        options = BY_CTAS[level]
        return self.rng.choices(options, weights=[p.weight for p in options])[0]

    def _uniform(self, r: tuple[float, float]) -> float:
        return self.rng.uniform(*r)

    def initial_vitals(self, p: Presentation) -> Vitals:
        u = lambda name: self._uniform(p.vital_range(name))  # noqa: E731
        sbp = round(u("systolic_bp"))
        return Vitals(
            heart_rate=round(u("heart_rate")),
            systolic_bp=sbp,
            diastolic_bp=min(round(u("diastolic_bp")), sbp - 20),
            resp_rate=round(u("resp_rate")),
            spo2=min(100, round(u("spo2"))),
            temp_c=round(u("temp_c"), 1),
            pain_score=round(u("pain_score")),
            gcs=round(u("gcs")),
        )

    def recheck_vitals(self, p: Presentation, last: Vitals, deteriorated: bool) -> Vitals:
        """Small random drift around the presentation profile; a deteriorated
        patient trends toward shock/respiratory compromise."""
        rng = self.vitals_rng

        def drift(value: float, name: str, jitter: float) -> float:
            lo, hi = p.vital_range(name)
            target = (lo + hi) / 2
            return value + (target - value) * 0.2 + rng.gauss(0, jitter)

        v = Vitals(
            heart_rate=round(drift(last.heart_rate, "heart_rate", 3)),
            systolic_bp=round(drift(last.systolic_bp, "systolic_bp", 4)),
            diastolic_bp=round(drift(last.diastolic_bp, "diastolic_bp", 3)),
            resp_rate=round(drift(last.resp_rate, "resp_rate", 1)),
            spo2=round(drift(last.spo2, "spo2", 0.7)),
            temp_c=round(drift(last.temp_c, "temp_c", 0.1), 1),
            pain_score=round(drift(last.pain_score, "pain_score", 0.5)),
            gcs=last.gcs,
        )
        if deteriorated:
            # Gentle continued decline; the step change happened at deterioration.
            v.heart_rate += rng.randint(0, 3)
            v.systolic_bp -= rng.randint(0, 3)
            v.resp_rate += rng.randint(0, 1)
            if rng.random() < 0.1:
                v.gcs -= 1
        return _clamp(v)

    def deteriorate(self, v: Vitals) -> Vitals:
        """Step change at the moment of deterioration."""
        rng = self.vitals_rng
        return _clamp(Vitals(
            heart_rate=v.heart_rate + rng.randint(15, 28),
            systolic_bp=v.systolic_bp - rng.randint(15, 30),
            diastolic_bp=v.diastolic_bp - rng.randint(8, 15),
            resp_rate=v.resp_rate + rng.randint(4, 8),
            spo2=v.spo2 - rng.randint(3, 7),
            temp_c=v.temp_c,
            pain_score=v.pain_score + rng.randint(1, 3),
            gcs=v.gcs - rng.randint(0, 2),
        ))

    def new_patient(self, arrived_at: datetime) -> NewPatient:
        p = self._pick_presentation()
        rng, fk = self.rng, self.faker

        sex = p.sex or rng.choice("MF")
        age = rng.randint(int(p.age[0]), int(p.age[1]))
        dob = arrived_at.date() - timedelta(days=age * 365 + rng.randint(0, 364))
        first = fk.first_name_female() if sex == "F" else fk.first_name_male()
        self._mrn_seq += 1

        pmh, meds = rng.choice(p.history)
        history = f"PMHx: {pmh}. Meds: {meds}."
        note = rng.choice(p.notes).format(age=age, sex=sex)
        ambulance = rng.random() < p.ambulance_prob

        return NewPatient(
            presentation=p,
            mrn=f"M{self._mrn_seq:07d}",
            health_card_no=f"{rng.randint(10000, 99999)}-{rng.randint(1000, 9999)}",
            first_name=first,
            last_name=fk.last_name(),
            date_of_birth=dob,
            age=age,
            sex=sex,
            postal_code=fk.postcode(),
            arrival_mode=ArrivalMode.AMBULANCE if ambulance else ArrivalMode.WALK_IN,
            arrived_at=arrived_at,
            history=history,
            triage_note=note,
            fragility=rng.expovariate(1.0),
            vitals=self.initial_vitals(p),
        )


def _clamp(v: Vitals) -> Vitals:
    v.heart_rate = max(30, min(200, v.heart_rate))
    v.systolic_bp = max(50, min(240, v.systolic_bp))
    v.diastolic_bp = max(25, min(v.systolic_bp - 15, v.diastolic_bp))
    v.resp_rate = max(6, min(50, v.resp_rate))
    v.spo2 = max(60, min(100, v.spo2))
    v.pain_score = max(0, min(10, v.pain_score))
    v.gcs = max(3, min(15, v.gcs))
    return v

