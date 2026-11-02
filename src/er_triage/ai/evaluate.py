"""Offline triage accuracy evaluation against simulator ground truth.

Builds a stratified set of synthetic patients (N per presentation) and scores
each triager on exact agreement, under-/over-triage, and subtle-case catch
rate. Claude responses are cached, so re-runs are free.
"""

import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from er_triage.ai.claude_triage import ClaudeTriager
from er_triage.sim.catalog import CATALOG
from er_triage.sim.generator import NewPatient, PatientGenerator
from er_triage.sim.triage import NurseTriager, RulesTriager

# USD per million tokens (input, output).
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00)}


@dataclass
class Score:
    n: int = 0
    exact: int = 0
    under: int = 0
    over: int = 0
    emergent_under: int = 0  # true CTAS 1-2 assigned 3+
    subtle_n: int = 0
    subtle_caught: int = 0
    abs_err: int = 0

    def add(self, true: int, assigned: int, subtle: bool) -> None:
        self.n += 1
        self.exact += assigned == true
        self.under += assigned > true
        self.over += assigned < true
        self.emergent_under += true <= 2 and assigned >= 3
        self.abs_err += abs(assigned - true)
        if subtle:
            self.subtle_n += 1
            self.subtle_caught += assigned <= true

    def row(self) -> dict[str, str]:
        pct = lambda x: f"{100 * x / self.n:.0f}%" if self.n else "-"  # noqa: E731
        return {
            "exact": pct(self.exact),
            "under": pct(self.under),
            "over": pct(self.over),
            "emergent missed": f"{self.emergent_under}",
            "subtle caught": f"{self.subtle_caught}/{self.subtle_n}",
            "mean |err|": f"{self.abs_err / self.n:.2f}" if self.n else "-",
        }


def stratified_patients(per_code: int, seed: int = 2026) -> list[NewPatient]:
    gen = PatientGenerator(seed=seed)
    when = datetime(2026, 11, 6, 12, tzinfo=UTC)
    buckets: dict[str, list[NewPatient]] = defaultdict(list)
    while any(len(buckets[p.code]) < per_code for p in CATALOG):
        patient = gen.new_patient(when)
        if len(buckets[patient.presentation.code]) < per_code:
            buckets[patient.presentation.code].append(patient)
    return [p for presentation in CATALOG for p in buckets[presentation.code]]


def evaluate(api_key: str | None, per_code: int = 4, offline: bool = False) -> None:
    patients = stratified_patients(per_code)
    triagers = {
        "Nurse (baseline)": NurseTriager(random.Random(7)),
        "Rules": RulesTriager(),
        "Haiku only": ClaudeTriager(api_key, escalation_model=None, blocking=True,
                                    offline=offline),
        "Haiku + Sonnet": ClaudeTriager(api_key, blocking=True, offline=offline),
    }
    # Warm Claude concurrently; assess() then collects the finished futures.
    for t in triagers.values():
        if isinstance(t, ClaudeTriager):
            for p in patients:
                t.prefetch(p, p.vitals)

    scores = {name: Score() for name in triagers}
    # Admission prediction (Claude only): name -> [tp, fp, fn, tn]
    admit: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    misses: dict[str, list[str]] = defaultdict(list)
    for p in patients:
        true = p.presentation.ctas
        for name, t in triagers.items():
            d = t.assess(p, p.vitals, true, 10)
            scores[name].add(true, d.ctas, p.presentation.subtle)
            cell = {(True, True): 0, (True, False): 1, (False, True): 2, (False, False): 3}
            if d.admit_predicted is not None:
                admit[name][cell[(d.admit_predicted, p.admitted)]] += 1
            if true <= 2 and d.ctas >= 3 and isinstance(t, ClaudeTriager):
                misses[name].append(f"{p.presentation.code} -> CTAS {d.ctas}")
        # Ceiling: knows each presentation's true admission rate (no model can
        # do better, because the simulated disposition is random given it).
        best = p.presentation.admit_prob >= 0.5
        admit["Best possible"][cell[(best, p.admitted)]] += 1

    print(f"\n{len(patients)} patients ({per_code} per presentation, "
          f"{sum(p.presentation.subtle for p in patients)} subtle)\n")
    cols = list(next(iter(scores.values())).row())
    print(f"  {'':18}" + "".join(f"{c:>16}" for c in cols))
    for name, sc in scores.items():
        print(f"  {name:18}" + "".join(f"{v:>16}" for v in sc.row().values()))

    if admit:
        print("\n  Admission prediction (vs simulated disposition):")
        admit["Best possible"] = admit.pop("Best possible")  # print last
        for name, (tp, fp, fn, tn) in admit.items():
            n = tp + fp + fn + tn
            print(f"  {name:18} accuracy {100 * (tp + tn) / n:.0f}%  "
                  f"precision {100 * tp / max(1, tp + fp):.0f}%  "
                  f"recall {100 * tp / max(1, tp + fn):.0f}%  "
                  f"(admitted {tp + fn}/{n}, predicted {tp + fp})")

    print()
    for name, t in triagers.items():
        if not isinstance(t, ClaudeTriager):
            continue
        st = t.stats
        # Estimated live cost (replayed calls are free but priced as if live).
        cost = sum(PRICES[m][0] * i / 1e6 + PRICES[m][1] * o / 1e6
                   for m, (i, o) in t.tokens_by_model.items())
        print(f"  {name}: {st['calls']} calls ({st['cache_hits']} replayed), "
              f"{st['escalations']} escalated, {st['fallbacks']} fallbacks, "
              f"est. ${cost:.3f} live (~${cost / len(patients) * 150:.2f}/day at 150 patients)")
        for m in misses[name]:
            print(f"      emergent missed: {m}")
        t.close()
