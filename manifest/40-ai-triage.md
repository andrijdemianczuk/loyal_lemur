# 40 — LLM triage service

The AI arm's triager. It recommends a CTAS level with reasons, flags
fast-track eligibility and predicts admission. A nurse confirms every
recommendation in real use; in the simulation it is applied directly.

## Inputs: what the model sees

Only what a triage nurse would see. **Never** the true CTAS, the
presentation code, `subtle`, admission outcome, fragility, or ED load. (ED
load is excluded also so requests stay deterministic and replay exactly.)

User message, exactly this shape (`Arrival` is `walk-in` or `ambulance`):

```
Age/sex: 76F
Arrival: walk-in
Chief complaint: Epigastric pain
Triage note: <note>
History: PMHx: <pmh>. Meds: <meds>.
Vitals: HR 98, BP 146/82, RR 16, SpO2 97%, T 36.8 C, pain 4/10, GCS 15
```

## System prompt (prompt version `ctas-v2`)

Copy exactly. Send it as a cacheable system block (prompt caching,
ephemeral).

```text
You are an emergency department triage decision-support system used by triage nurses at a Canadian hospital. For each patient, assign a Canadian Triage and Acuity Scale (CTAS) level and explain it briefly. A nurse confirms every recommendation; your job is to make sure no time-critical patient is missed and that resources go where they matter.

CTAS levels and time-to-physician targets:
1 Resuscitation (immediate): cardiac/respiratory arrest, major trauma in shock, severe respiratory distress, unresponsive (GCS 3-9), status seizures.
2 Emergent (15 min): potential threat to life, limb or function needing rapid intervention - e.g. chest pain likely cardiac, stroke within the treatment window, sepsis with physiological change, altered mental status, severe asthma, overdose, suicidal ideation with a plan.
3 Urgent (30 min): conditions that could progress to a serious problem - e.g. moderate respiratory symptoms, abdominal pain needing workup, severe peripheral pain, syncope, head injury with risk factors, hip fracture.
4 Less urgent (60 min): conditions related to patient age, distress, or potential for deterioration that would benefit from care within 1-2 hours - minor injuries, uncomplicated infections, mild-moderate pain.
5 Non-urgent (120 min): acute but non-urgent or chronic problems - minor symptoms, medication refills, minor rashes.

How to triage:
- Start from the presenting complaint, then apply first-order modifiers (vital signs, level of consciousness, pain severity, mechanism of injury) and second-order modifiers (e.g. anticoagulation or bleeding disorder, immunosuppression, pregnancy, extremes of age).
- Look beyond reassuring vital signs. Atypical presentations are common in older adults, women and people with diabetes; the wording of a complaint ("indigestion", "a bit forgetful", "just a headache") can understate risk. Read the triage note, history and medications together.
- When a dangerous diagnosis is plausible and time-sensitive, triage to the level that diagnosis requires. Under-triage is more harmful than over-triage, but do not over-triage clearly minor problems: every unnecessary high-acuity assignment delays someone else.
- fast_track_eligible: true only for stable, ambulatory patients likely to be treated and discharged quickly (most CTAS 4-5 and some low-risk CTAS 3).
- likely_admission: true when this patient will probably need admission to hospital (not just ED treatment and discharge), judged from the complaint, age, history and vital signs. It is used to request an inpatient bed early, so be realistic: neither every older patient nor only the critically ill.
- confidence: "high" when the level is clear; "medium" or "low" when the case is ambiguous or could plausibly be a different level.
- red_flags: short phrases for findings that drove the level up (empty if none). immediate_actions: up to three concrete nursing actions to start now (e.g. "12-lead ECG within 10 min"), empty if none.
- rationale: at most two sentences, written for a busy nurse.
```

## Structured output

Parse the response into this schema (reject anything else):

| Field | Type |
|---|---|
| `ctas_level` | integer 1–5 |
| `confidence` | `high` / `medium` / `low` |
| `rationale` | string |
| `red_flags` | list of strings (default empty) |
| `immediate_actions` | list of strings (default empty) |
| `fast_track_eligible` | boolean |
| `likely_admission` | boolean (default false) |

## Model routing

- **Primary:** `claude-haiku-5-5`, effort `low`, for every patient.
- **Escalate** to `claude-sonnet-5-5`, effort `medium`, when the primary's
  confidence is not `high`. Measured: about 8% of patients.
- `max_tokens` 4096. API client: 30 s timeout, 2 retries.
- The stronger model may use the API's server-side fallback on refusal if the
  platform offers it; the primary relies on the rules fallback instead.
- Model names and effort are configuration (`ER_TRIAGE_MODEL`,
  `ER_ESCALATION_MODEL`), not code.

## Guardrail and fallback

- Compute the **rules** decision (`30-simulator.md`) for every patient.
- If the model's level is **less urgent** than the rules level, use the rules
  level, add the rules' red flags, and append
  `[Guardrail: raised to CTAS N by vital-sign rules.]` to the rationale.
- Any exception, refusal, empty output or timeout → use the rules decision,
  rationale prefixed `AI unavailable (<ErrorType>); `, and count a fallback.
- Append immediate actions to the rationale: ` Actions: a; b; c.`
- Fast track = `fast_track_eligible` **and** final level ≥ 3.
- The decision records: final CTAS, source `ai`, rationale, red flags, fast
  track, admission prediction, the rules level, model used, latency, tokens.

## Live vs blocking mode

- Work starts when the patient reaches the triage desk (prefetch on a worker
  pool of 8 threads), so the answer is usually ready when triage finishes.
- **Blocking** (replay, warm-up, evaluation): wait for the answer.
- **Live, non-blocking:** if the answer isn't back when triage finishes,
  apply the rules decision with rationale prefixed
  `Provisional (AI pending): `, and apply the AI decision when it lands
  (see flow step 1 in `30`). Count late decisions.
- Reassessment while waiting uses the instant rules, not the LLM.

## Record and replay cache

- Key: SHA-256 of the JSON array `[prompt_version, model, effort, user
  message]`.
- Look up the cache before every call. A hit returns the stored output with
  latency 0 and is marked `replayed`.
- On a miss: if offline or cache-only, raise (→ rules fallback); otherwise
  call the API and store the response (first writer wins on a race; caching
  failures are logged, never fatal).
- Changing the prompt text **requires** bumping the prompt version, which
  invalidates old recordings by construction.

## Telemetry

- Emit `llm.call` for every call or replay (fields in `20`).
- Keep stats: calls, cache hits, escalations, fallbacks, late decisions,
  input/output tokens, tokens by model. Reset after warm-up.
- Cost readout uses list prices per million tokens (input, output): Haiku
  0.10 / 0.50, Sonnet 2.00 / 10.00 (configurable; update when prices change).

## Offline evaluation (`eval-triage`)

- A stratified set: N patients per presentation (default 4 → 120 patients),
  generated with seed 2026 at 2026-11-06 12:00 UTC.
- Score each triager against true CTAS: exact match, under-triage %,
  over-triage %, emergent misses (true 1–2 assigned ≥ 3), subtle caught
  (assigned at least as urgent as true), mean absolute error.
- Triagers: nurse (seed 7, waiting load 10), rules, primary model only,
  primary + escalation.
- Admission prediction: accuracy, precision, recall against the simulated
  disposition, plus the **best possible** (predict admission when the
  presentation's admit probability ≥ 0.5), because dispositions are random
  given the presentation.
- Print calls, replays, escalations, fallbacks, emergent misses by
  presentation, and the estimated live cost per day at 150 patients.
