# 00 — Intent

## The problem

An emergency department (ED) makes hundreds of time-critical decisions a day
under load, with static rules and partial information: how urgent each
patient is, who is seen next, when to open extra assessment capacity, and
when to ask for an inpatient bed. Late or wrong decisions turn into waiting,
patients leaving without being seen, and patients deteriorating in the
waiting room.

## What we're building

A **decision-support system for ED intake and triage**, demonstrated on a
simulated ED with synthetic patients. The same stream of patients feeds two
identical EDs:

- **Manual ED (baseline):** standard practice. Nurse triage with realistic
  error, CTAS-then-first-come queueing, extra assessment space on fixed
  hours, bed requested after the admission decision.
- **AI-assisted ED:** the same staff and beds, with four decisions supported
  by AI: triage level, queue priority, opening the intake zone, and early bed
  requests.

A live dashboard compares the two side by side. Every AI decision is visible
with its reason, and emitted as an event for downstream systems.

## Users

- **Presenter:** runs a deterministic, offline demo in about 10 minutes.
- **Analyst:** runs headless simulations, evaluations and ablations.
- **Downstream platforms:** consume the event stream (a pipeline, a SIEM, a
  warehouse).

## Scale used for triage: CTAS

Canadian Triage and Acuity Scale, levels 1–5, with time-to-physician targets:
1 immediate, 2 = 15 min, 3 = 30 min, 4 = 60 min, 5 = 120 min.

## Measures

- **SLI:** wait from arrival to physician, by acuity.
- **SLO:** walk-ins seen within **4 hours**.
- Also reported: P90 wait, CTAS target misses, under-triage, deteriorations
  while waiting, left without being seen (LWBS).
- **Fairness rules for measurement** (these are requirements):
  - Judge every outcome against the patient's **true** acuity, never the
    level an ED assigned.
  - Count walk-outs: a patient who leaves keeps their wait in the statistics,
    so an ED can't look faster by losing patients.
  - Measure **steady state**: simulate a warm-up before the reported period
    so the ED isn't empty at the start.
  - Headline numbers are cumulative since opening, not rolling windows.

## What "better" means, and what it doesn't

- Credible beats dramatic: the model is calibrated so improvements land in
  the range published for comparable interventions (roughly 20–40% on
  waits for individual levers). Don't tune for bigger numbers.
- The AI arm may trade small amounts of one outcome for another (for
  example, CTAS-3 target misses for zero 4-hour breaches). That tradeoff is
  reported, not hidden.

## Non-goals

- Not clinical guidance, not a medical device, no real patient data.
- No authentication, multi-user support or production hardening (MVP).
- No trained ML models in this version (see `10-architecture.md`, next steps).
