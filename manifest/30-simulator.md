# 30 — Simulator: patients, the two-arm ED, the four decisions

All parameters below are exact. Synthetic and simplified; not clinical
guidance.

## Time and determinism

- Simulated time advances in a **fixed grid of 1-minute sub-steps**. A tick
  processes every whole sub-step up to "now"; the result depends only on the
  seed, never on how wall-clock ticks fall.
- A **sim clock** maps real seconds to simulated minutes (`speed`, 0–60
  sim-min per real second). It can pause, resume, change speed without
  jumps, and pause at an exact simulated time.
- **Random streams:**
  - The patient generator has one RNG (seeded by the run seed) plus a Faker
    instance (`en_CA`) seeded the same way.
  - Each patient carries a 64-bit `vitals_seed`. Each arm gives each patient
    its own RNG from it, so the arms never disturb each other.
  - Per-patient draws that must match in both arms (triage desk duration)
    use `Random(f"{vitals_seed}:{salt}")`.
  - The nurse triager has its own RNG, seeded `seed + 2`.
  - Surge patients come from a separate generator stream (MRN prefix `S`).
- **Invariant:** changing anything in the AI arm must not change a single
  baseline outcome, and the same seed reproduces the same day.

## Patient generator

- **Arrivals:** non-homogeneous Poisson. Rate per minute =
  `daily_volume / 1440 × hourly_factor[hour] × multiplier`, default volume
  150/day. Hourly factors are in `31-catalog.md`. Per sub-step, draw a
  Poisson count (Knuth's algorithm) and uniform offsets within the minute.
- **Presentation:** pick a CTAS level by the mix 1% / 12% / 40% / 33% / 14%,
  then a presentation within that level by its weight (`31-catalog.md`).
- **Per patient** (draw order matters for reproducibility only within one
  implementation): sex (presentation's restriction, else M/F), age uniform in
  the presentation range, date of birth consistent with age, Faker first name
  by sex and last name, sequential MRN `M0000001`…, health card
  `NNNNN-NNNN`, Faker postal code, one (history, medications) pair, one note
  template filled with `{age}{sex}` (e.g. `76F`), arrival mode (ambulance with
  the presentation's probability), `fragility ~ Exp(1)`, initial vitals,
  and care-path outcomes drawn once so both arms face the same patient:
  - physician assessment minutes, uniform by true CTAS: 1: 45–75, 2: 30–50,
    3: 20–40, 4: 10–25, 5: 8–15
  - treatment minutes, uniform in the presentation range
  - admitted: Bernoulli(admit_prob)
  - boarding minutes if admitted: uniform **240–600** (access block)
  - patience (walk-ins only): `120 + Exp(mean 720)` min for true CTAS 1–2,
    `120 + Exp(mean 480)` otherwise; ambulance patients never leave
- **History text:** `PMHx: {pmh}. Meds: {meds}.`
- **Initial vitals:** each uniform in the presentation's range (normal range
  if not overridden), rounded; DBP = min(drawn, SBP − 20); SpO2 ≤ 100;
  temperature to 0.1.
- **Vitals recheck:** each value moves 20% toward its range midpoint plus
  Gaussian noise (σ: HR 3, SBP 4, DBP 3, RR 1, SpO2 0.7, T 0.1, pain 0.5;
  GCS unchanged). A deteriorated patient also drifts worse each recheck: HR
  +0–3, SBP −0–3, RR +0–1, and GCS −1 with probability 0.1.
- **Deterioration step change:** HR +15–28, SBP −15–30, DBP −8–15, RR +4–8,
  SpO2 −3–7, pain +1–3, GCS −0–2.
- **Clamp** after every change: HR 30–200, SBP 50–240, DBP 25–(SBP−15),
  RR 6–50, SpO2 60–100, pain 0–10, GCS 3–15.

## Deterioration

While waiting (triage or physician), each patient accumulates hazard every
sub-step:

```
overdue = max(0, wait_min / target_min(true CTAS on arrival) − 1)
hazard += risk_per_hour × hours × (1 + 0.5 × overdue)
```

When `hazard ≥ fragility`: the patient deteriorates once. True CTAS drops by
one level (minimum 1), vitals take the step change, the next vitals check is
scheduled at the new level's interval, and `patient.deteriorated` is emitted.
`target_min(level) = max(CTAS target, 5)`.

**Vitals checks while waiting** happen at the reassessment interval of the
level the ED *believes* (assigned, else true): 1: 5, 2: 15, 3: 30, 4: 60,
5: 120 minutes. Each check records vitals and lets the arm's triager
reassess.

## ED resources (identical in both arms)

| Resource | Value |
|---|---|
| Main physicians | 5 |
| Main beds | 20, plus 4 hallway spaces usable only by assigned CTAS 1–2 |
| Fast track | 1 physician, 4 chairs, open 09:00–23:00, chair time capped at 60 min |
| Intake zone (rapid assessment) | 2 chairs, staffed by idle **main** physicians |
| Results area | 8 places, shared by fast-track and intake patients whose workup outlasts their chair; when full, those lanes stall |
| Triage nurses | 2; triage takes 3–8 min (per-patient draw, same in both arms) |
| Deteriorated treatment | ×1.5 treatment time |
| SLO guard | 180 min (AI queue policy) |

## Flow (each sub-step, per arm, in this order)

1. **Apply late AI decisions** that arrived after a provisional triage. If
   the patient is still waiting for a physician, apply it; otherwise record
   it with `applied = false`.
2. **Finish triage** for patients whose triage time is up: ask the arm's
   triager (it receives the number currently waiting, for the nurse load
   model) and apply the decision.
3. **Start triage:** true CTAS 1 bypasses the desk (triage done at arrival).
   Others queue ambulance-first, then by arrival; free nurses take the next
   patients. When a patient reaches the desk, the AI triager may start work
   (prefetch).
4. **Discharge** patients whose departure time has passed: `admitted` or
   `discharged`.
5. **Walk-outs:** a waiting walk-in whose wait exceeds their patience leaves
   (`lwbs`); their wait is recorded, flagged as left.
6. **Assign physicians:**
   - Assigned CTAS 1 go straight to resus in the main lane regardless of
     capacity, taking the main physician who is free soonest.
   - Fast track (when open) takes its lane's queue. The main lane takes its
     own queue; if empty, it takes overflow from the fast-track queue. When
     fast track is closed, everyone queues for main.
   - Intake zone (when open) takes waiting walk-ins with assigned CTAS ≥ 3
     who haven't deteriorated, using idle main physicians.
   - Each lane sorts its queue by the arm's queue policy and fills while a
     physician is free and capacity allows. Emergent patients (assigned 1–2)
     may use hallway spaces; if even those are full, skip to the next
     patient rather than stopping.
7. **SLO check:** a waiting walk-in reaching 240 minutes is a breach (once
   per patient); emit `slo.breach`.

**When a patient is seen:** record the wait, target miss (against current
true CTAS), lane. Treatment time = max(treatment, assessment) × 1.5 if
deteriorated. A deteriorated patient is admitted even if they wouldn't have
been (boarding 90 min). Departure = seen + treatment + boarding. In
fast-track or intake lanes the chair frees after min(treatment, 60 min); the
patient then waits for results in the results area.

## The two arms

| | Manual ED (baseline) | AI-assisted ED |
|---|---|---|
| Triager | Nurse model | LLM triage service (`40`), rules fallback |
| Queue policy | CTAS-then-FIFO | SLO-aware |
| Intake zone | Scheduled 11:00–21:00 | Dynamic: open whenever a main physician is idle |
| Bed request | After the physician's decision | At triage, when admission is predicted |

### Nurse triager (baseline)

- True CTAS 1 is always recognised.
- Under-triage probability = 0.12 + 0.004 × patients waiting.
- Subtle presentations: with probability 0.6, assigned 1 or 2 levels too low
  (`true + 1` or `true + 2`, chosen at random).
- Otherwise: under-triage by one level with the probability above,
  over-triage by one level with probability 0.08, else correct.
- Clamp to 1–5.
- **Reassessment:** if the vital-sign level is more urgent than assigned, act
  on it with probability 0.5; otherwise, if the true level is more urgent,
  catch it by clinical gestalt with probability 0.1.

These rates are **calibrated assumptions**, not measurements.

### Rules triager (AI arm fallback and guardrail)

- Base level from the complaint (`COMPLAINT_BASE` in `31-catalog.md`;
  unknown complaint = 3). Benign-sounding complaints for dangerous
  conditions start low, as real lookups do.
- First-order vital-sign modifiers; the most urgent matching level wins:

| Level | Any of |
|---|---|
| 1 | GCS ≤ 9 · SpO2 < 86 · SBP < 80 · HR ≥ 140 · RR ≥ 36 |
| 2 | GCS ≤ 13 · SpO2 < 92 · SBP < 90 · HR ≥ 120 · RR ≥ 28 · T ≥ 38.5 with HR > 110 or SBP < 100 |
| 3 | GCS = 14 · SpO2 < 95 · HR > 100 · RR > 24 · SBP ≥ 200 · T ≥ 38.0 with HR > 100 · pain ≥ 8 |
| 4 | pain ≥ 4 |
| 5 | none of the above |

- Level = min(base, vital-sign level). Rationale names the base and any
  modifiers. Model name `ctas-rules-v1`.
- Reassessment re-scores on every vitals check and acts only if more urgent.

### Queue policies

- **CTAS-then-FIFO (baseline):** sort by assigned CTAS, then arrival.
  Lanes: assigned 4–5 → fast track, else main.
- **SLO-aware (AI):** sort key
  1. assigned CTAS 1–2: `(0, level, arrival)`
  2. walk-ins waiting ≥ 180 min: `(1, −wait)`
  3. everyone else: `(2, −wait / target_min(assigned))`

  Lanes: use the triage decision's fast-track hint if present; else assigned
  4–5 → fast track; also assigned-3 walk-ins under 65 who haven't
  deteriorated; else main.

## The four AI decisions (AI arm only)

Each is counted and emitted as `ai.decision` **only when it changed care
compared with standard practice**, with a human-readable reason.

| Decision | Fires when | Reason text |
|---|---|---|
| `triage` | the AI's level is more urgent than the rules level | first two red flags, else the first sentence of the rationale (≤120 chars) |
| `queue` | a patient is seen ahead of anyone CTAS-then-FIFO would have seen first | "waited 2 h 05, approaching the 4 h walk-in limit" or "waited 45 min against a 30 min CTAS 3 target" |
| `intake` | the dynamic zone sees a patient outside the scheduled hours | "2 physicians free, 3 walk-ins waiting" |
| `bed` | admission is predicted at triage (first time only) | as triage |

**Early bed request:** for a correctly predicted admission, boarding is
shortened by **60 minutes** (not below zero). False positives cost nothing in
this MVP (a known simplification).

**Under-triage** is counted on the first assessment when the assigned level
is less urgent than the current true level.

## Metrics (per arm)

Counters since opening: seen, SLO breaches, CTAS target misses (walk-outs
included), under-triaged, deteriorations, LWBS, late AI decisions applied or
dropped, admission prediction TP/FP/FN, boarding minutes saved, decisions by
kind. Every completed wait is kept (time, wait, arrival true CTAS, current
true CTAS, walk-in, left).

A metrics object: waiting, in_treatment, avg and P90 wait over the last
60 minutes, max walk-in wait currently waiting, the counters, and per true
arrival CTAS: waiting, seen, avg wait, P90 wait, target misses.
Percentile: nearest-rank. Snapshot every 15 sim-minutes, persisted and
emitted.

## Warm-up

A run can simulate **N hours before opening** (default 30 for the web app)
so it opens on a loaded, steady-state ED:
- runs as fast as possible; the AI triager blocks on each decision;
- with `cache_only`, an LLM cache miss falls back to rules instead of calling
  the API;
- events are muted, surges don't apply;
- at the end, KPI counters reset, patients stay, the clock restarts at the
  opening time, and `run.started` is emitted with a warm-up summary.

## Surge presets

Surges add patients **on top of** the unchanged normal day, from their own
stream (MRN prefix `S`), within a window on the opening day (clipped to
opening, never during warm-up). Rate-based surges add a **fixed count** (the
expected number, rounded) at times weighted by the normal hourly rate.

| Key | Label | Window | Extra |
|---|---|---|---|
| `evening-rush` | Evening rush (+35%, 17:00–21:00) | 17:00, 4 h | +35% of the normal rate, normal mix |
| `mvc` | Multi-vehicle collision (8 patients, 18:30) | 18:30, 30 min | fixed list, all ambulance: L1_MAJOR_TRAUMA ×2, L4_BACK_PAIN ×2, L4_LACERATION ×2, L3_HEAD_INJURY_ANTICOAG, L4_ANKLE; collision-specific notes |
| `flu-wave` | Respiratory wave (+15%, 12:00–24:00) | 12:00, 12 h | +15%, mix: L5_URTI 30, L3_FEVER_ADULT 20, L5_SORE_THROAT 15, L3_SOB_MILD 12, L3_VOMITING 10, L2_ASTHMA 6, L2_SEPSIS 5, L1_RESP_FAILURE 2 |

With every override off, a surge patient must be generated exactly like a
normal patient.
