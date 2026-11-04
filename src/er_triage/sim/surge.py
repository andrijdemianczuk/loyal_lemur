"""Time-limited surge presets.

A surge adds patients on top of the normal day; it never changes it. Surge
patients come from their own random stream (MRNs prefixed ``S``), so the
normal day's patients are identical with and without a surge, and the demo
can say "the same Friday, plus an evening rush".

Windows are clock times on the opening day, clipped to the opening time;
they never overlap the warm-up.
"""

import random
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from er_triage.sim.catalog import CATALOG, Presentation
from er_triage.sim.generator import NewPatient, PatientGenerator

BY_CODE = {p.code: p for p in CATALOG}


@dataclass(frozen=True)
class SurgePreset:
    key: str
    label: str
    start_hour: float  # clock time on the opening day
    hours: float
    # Poisson surge: extra arrivals as a fraction of the normal rate.
    extra: float = 0.0
    # Presentation mix for extra arrivals as (code, weight); empty = normal mix.
    mix: tuple[tuple[str, float], ...] = ()
    # Fixed casualty list instead of a rate: one patient per code.
    manifest: tuple[str, ...] = ()
    ambulance: bool | None = None  # force the arrival mode; None = per presentation
    notes: dict[str, tuple[str, ...]] = field(default_factory=dict)  # per-code narratives


_MVC = "multi-vehicle collision on the highway"

PRESETS: dict[str, SurgePreset] = {p.key: p for p in (
    SurgePreset(
        "evening-rush", "Evening rush (+35%, 17:00–21:00)",
        start_hour=17, hours=4, extra=0.35,
    ),
    SurgePreset(
        "mvc", "Multi-vehicle collision (8 patients, 18:30)",
        start_hour=18.5, hours=0.5, ambulance=True,
        manifest=("L1_MAJOR_TRAUMA", "L4_BACK_PAIN", "L4_LACERATION", "L1_MAJOR_TRAUMA",
                  "L3_HEAD_INJURY_ANTICOAG", "L4_ANKLE", "L4_BACK_PAIN", "L4_LACERATION"),
        notes={
            "L3_HEAD_INJURY_ANTICOAG": (
                f"{{age}}{{sex}} rear-seat passenger in a {_MVC}, struck head on the side "
                "window. Small scalp laceration. Denies LOC. Says they feel 'a bit foggy'.",),
            "L4_BACK_PAIN": (
                f"{{age}}{{sex}} restrained occupant in a {_MVC}, rear-ended at low speed. "
                "Neck and lower back pain, ambulatory at scene, no numbness or weakness.",),
            "L4_LACERATION": (
                f"{{age}}{{sex}} occupant in a {_MVC}, 4 cm forearm laceration from broken "
                "glass, bleeding controlled with pressure dressing.",),
            "L4_ANKLE": (
                f"{{age}}{{sex}} occupant in a {_MVC}, ankle pain and swelling after foot "
                "was jammed under the pedals. Weight bearing with pain.",),
        },
    ),
    SurgePreset(
        "flu-wave", "Respiratory wave (+15%, 12:00–24:00)",
        start_hour=12, hours=12, extra=0.15,
        mix=(("L5_URTI", 30), ("L3_FEVER_ADULT", 20), ("L5_SORE_THROAT", 15),
             ("L3_SOB_MILD", 12), ("L3_VOMITING", 10), ("L2_ASTHMA", 6),
             ("L2_SEPSIS", 5), ("L1_RESP_FAILURE", 2)),
    ),
)}


class SurgeSchedule:
    """Pre-drawn surge arrival times plus a dedicated patient generator."""

    def __init__(self, preset: SurgePreset, opens_at: datetime, seed: int | None,
                 base: PatientGenerator) -> None:
        self.preset = preset
        order = list(PRESETS).index(preset.key) + 1 if preset.key in PRESETS else 99
        derived = None if seed is None else seed * 1000 + order
        self.gen = PatientGenerator(derived, base.daily_volume, base.boarding_min,
                                    mrn_prefix="S")
        rng = random.Random(f"surge-times:{seed}:{preset.key}")
        day = opens_at.replace(hour=0, minute=0, second=0, microsecond=0)
        start = max(opens_at, day + timedelta(hours=preset.start_hour))
        end = day + timedelta(hours=preset.start_hour + preset.hours)
        self.window = (start, end)
        times: list[datetime] = []
        span = (end - start).total_seconds() / 60
        if span > 0 and preset.manifest:
            times = sorted(start + timedelta(minutes=rng.uniform(0, span))
                           for _ in preset.manifest)
        elif span > 0 and preset.extra:
            # A fixed count (the expected number) so a preset means the same
            # load on every seed; only the times are random, following the
            # time-of-day arrival curve.
            minutes = [start + timedelta(minutes=m) for m in range(int(span))]
            rates = [base.arrivals_per_minute(m) * preset.extra for m in minutes]
            count = round(sum(rates))
            times = sorted(m + timedelta(minutes=rng.random())
                           for m in rng.choices(minutes, weights=rates, k=count))
        self.planned = len(times)
        self._pending = deque(times)
        self._manifest = deque(preset.manifest)

    def arrivals(self, start: datetime, end: datetime) -> list[NewPatient]:
        """Surge patients arriving in [start, end)."""
        out = []
        while self._pending and self._pending[0] < end:
            at = self._pending.popleft()
            out.append(self._patient(max(at, start)))
        return out

    def _patient(self, at: datetime) -> NewPatient:
        p = self.preset
        presentation: Presentation | None = None
        if self._manifest:
            presentation = BY_CODE[self._manifest.popleft()]
        elif p.mix:
            codes, weights = zip(*p.mix, strict=True)
            presentation = BY_CODE[self.gen.rng.choices(codes, weights=weights)[0]]
        notes = p.notes.get(presentation.code) if presentation else None
        return self.gen.new_patient(at, presentation=presentation, ambulance=p.ambulance,
                                    notes=notes)
