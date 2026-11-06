# 80 — Acceptance: what "built correctly" means

A build is accepted when every automated test passes and every measured check
is inside its tolerance. Report each with its measured value.

A rebuild uses its own random streams and records its own LLM responses, so
individual days differ from the reference build. **Checks are on aggregates
over 12 days, with tolerances**, not on exact numbers.

## A. Automated tests (all must pass)

**Simulator and generator**
- Catalog integrity: codes unique; CTAS 1–5; every level has presentations;
  ranges valid.
- Daily volume and CTAS mix are within sampling error of the spec.
- Night is quieter than day.
- Same seed → identical arrivals.
- Vital-sign modifiers produce the levels in the rules table.
- Rules triager flags abnormal vitals.
- Clock: speed change, pause, resume without jumps; pause at an exact time.
- The feed engine populates both arms; every patient has one encounter per
  arm.
- **Arms are independent:** changing only the AI arm changes no baseline
  outcome.
- **Stream independent of tick timing:** irregular wall-clock ticks give the
  same simulation.
- Flow invariants: no patient in two states; capacities respected (hallway
  only for assigned 1–2); every departure has a disposition.
- Warm-up opens loaded, counts KPIs from opening, publishes nothing during
  warm-up, and ends in the same state a plain run reaches.
- Early bed request shortens boarding only for true admissions.
- AI decisions are counted and emitted for the AI arm only.

**LLM triage** (API mocked)
- The prompt contains no ground truth (no true CTAS, code, subtle flag,
  admission outcome).
- Uses the model's decision when valid.
- Guardrail: never less urgent than the vital-sign rules.
- Non-high confidence escalates to the second model.
- Any failure falls back to rules.
- Fast track only for final CTAS ≥ 3.
- Live mode: provisional rules decision, then the late decision applies.
- Cache-only mode never calls the API.
- Admission prediction is passed through.

**Events**
- File sink writes JSON Lines; HEC sink posts Splunk format with the token
  header.
- A failing sink doesn't stop the others.
- Buffer overflow drops the oldest and counts it.

**Surges**
- Preset codes exist; surge counts are fixed and inside the window; window
  clipped to opening; collision list is coherent; respiratory wave uses its
  mix; with overrides off a surge patient equals a normal one; a surge adds
  patients without changing the normal day.

**Database:** tables create, and a patient gets one encounter per arm.
(`initdb --drop` keeping the LLM cache is checked by hand; see D.)

## B. Triage evaluation (`eval-triage`, 4 per presentation = 120 patients)

| Check | Reference (2026-11-06, prompt `ctas-v2`) | Accept if |
|---|---|---|
| LLM (with escalation) exact CTAS match | 92% (primary only: 91%) | ≥ 88% |
| LLM emergent misses (true 1–2 assigned ≥ 3) | 0 | 0 |
| LLM subtle cases caught | 16 / 16 | ≥ 14 / 16 |
| Rules exact match | 81% | 75–87% |
| Nurse exact match | 75% | 65–85% |
| Escalation rate | ~9% (11 of 120) | 3–20% |
| Rules fallbacks | 1 (a missing cache entry) | ≤ 1 |
| Admission prediction accuracy vs best possible | 76% vs 81% | within 10 points of best possible |
| Estimated live cost | ~$0.06/day at 150 patients | report it |

## C. Measured results (12 days)

Seeds 1–12, normal day, opening `2026-11-06T14:00:00-07:00`, 30 h warm-up,
24 h after opening, blocking AI triage:

```
er-triage simulate --seed N --start 2026-11-06T14:00:00-07:00 --warmup 30 --minutes 1440 --speed 600
```

Record once (expected cost about US$1–2 at list prices), then every check
must reproduce with `--offline` and **zero** API calls.

| Check (12-day mean per day) | Reference (2026-11-04) | Accept if |
|---|---|---|
| Manual ED average wait | 68.4 min | 40–110 min (calibration band) |
| AI ED average wait vs manual | 32.0 vs 68.4 (−53%) | AI ≤ 70% of manual |
| AI P90 wait vs manual | 74 vs 177 | AI ≤ 70% of manual |
| Walk-ins past 4 h | 0 vs 12.1 | AI ≤ 10% of manual |
| Under-triaged | 4.4 vs 24.2 | AI ≤ 35% of manual |
| Deteriorated while waiting | 5.0 vs 7.9 | AI < manual |
| Left without being seen | 0.6 vs 8.4 | AI ≤ 30% of manual |
| Offline replay | 0 API calls | 0 API calls, identical scorecards |

Day-to-day variation is large (reference manual average wait ranged from 10
to 260 min). Don't judge a build on one day, and **report** days where the
AI ED does worse rather than hiding them: in the reference build the AI ED
had more deteriorations on 3 of 12 days.

## D. Running system

- `serve` starts; `/health` returns `status: ok`.
- After `initdb --drop`, the `llm_responses` row count is unchanged.
- A run with warm start opens on a loaded ED, both arms update every second,
  and the AI decisions panel shows all four decision types during the
  reference demo day (seed 8). In the reference build: bed, triage and queue
  within the first 2 hours; intake from about 21:00, once the scheduled zone
  would have closed.
