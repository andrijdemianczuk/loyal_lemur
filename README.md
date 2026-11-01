# ER Triage Decision Support

AI-assisted emergency department intake and triage, demonstrated on a live,
synthetic hospital data feed. The same stream of arriving patients is run
through two parallel EDs — **manual triage** and **AI-assisted triage** — so
the effect on wait times is visible side by side, in real time.

- **SLI:** time from arrival to physician, by CTAS level
- **SLO:** walk-in patients seen in under 4 hours
- **Triage scale:** CTAS (Canadian Triage and Acuity Scale, levels 1–5)
- **Data:** 100% synthetic. No real patient information.

## Architecture

```
EHR feed simulator ──▶ PostgreSQL ◀──▶ Triage engine (Claude)
        │                                   │
        └──────── event bus ────────────────┘
                     │
        ┌────────────┼──────────────┐
        ▼            ▼              ▼
   JSONL file   HTTP Event       Web dashboard
                Collector        (live updates)
                (Cribl / Splunk)
```

## Quick start

```bash
brew install postgresql@17 && brew services start postgresql@17
createuser er_triage && createdb -O er_triage er_triage

uv sync
uv run er-triage initdb
uv run er-triage serve          # http://127.0.0.1:8000/health
uv run pytest

# Headless synthetic feed: 8 simulated hours at 60 sim-minutes per second
uv run er-triage simulate --minutes 480 --speed 60 --seed 42
```

Put your Anthropic API key in `.key` (gitignored). Copy `.env.example` to
`.env` to change settings.

## Synthetic EHR feed

`src/er_triage/sim/` generates a live patient stream:

- **Arrivals:** Poisson process (~150 visits/day by default) shaped by a
  time-of-day curve: quiet overnight, peak late morning through evening.
  `--surge` multiplies the rate.
- **Presentations:** ~30 CEDIS-style chief complaints with a CTAS mix of
  roughly 1/12/40/33/14% for levels 1-5, realistic vitals, triage narratives,
  paired history and medications, and arrival mode (ambulance share rises
  with acuity).
- **Subtle presentations:** dangerous conditions that look benign at the
  front desk (atypical ACS, subarachnoid hemorrhage, ectopic pregnancy,
  anticoagulated head injury). This is where decision support adds value.
- **Deterioration:** each patient has a latent fragility. Risk accumulates
  while they wait and escalates once they pass their CTAS target. A patient
  who deteriorates moves up one acuity level, with matching vital-sign changes.
  Fragility is drawn once per patient, so both ED arms face the same patient.
- **Reproducibility:** arrivals and vitals use separate random streams, so a
  seed always produces the same patients however each arm behaves.

Ground truth (`true_ctas`, `presentation_code`, `fragility`) is stored for
scoring and is never shown to either triage arm. All data is synthetic and
simplified; it is not clinical guidance.

## Two-arm ED model

`src/er_triage/sim/ed.py`. Both arms get **identical resources**: 5 main
physicians, 20 beds (+4 hallway stretchers for CTAS 1-2 only), resus
bypass, a fast track (1 physician, 4 chairs, 09:00-23:00), a 3-chair intake
zone, a 10-space results-waiting area, and 2 triage nurses. Admitted
patients board for 4-12h (access block). They differ only in decisions:

|                 | Baseline (manual)                    | AI-assisted                                   |
|-----------------|--------------------------------------|-----------------------------------------------|
| Triage          | Nurse model with realistic error     | Decision support (rules now; Claude in Phase 4) |
| Reassessment    | Notices deterioration ~50% of time   | Re-scores at every vitals check               |
| Queue order     | CTAS, then first-come-first-served   | CTAS 1-2 first; walk-ins near SLO; then % of target elapsed |
| Fast track      | Assigned CTAS 4-5                    | Also stable ambulatory CTAS 3 under 65        |
| Intake zone     | Fixed hours (11:00-21:00)            | Opened dynamically when physicians are idle   |

Every per-patient outcome (treatment time, admission, boarding, patience,
deterioration threshold, vitals noise) is drawn once and shared by both
arms; a test proves changing one arm cannot change the other. Performance
is scored against **true** acuity, and patients who leave without being
seen keep their wait in the statistics so an ED can't look faster by
losing patients.

Calibrated result (rules-based AI arm, mean of 8 simulated days): average
wait to physician -40%, walk-in 4h SLO breaches 6.5/day to 0,
deteriorations while waiting -43%, LWBS -83%. Under a 1.25x surge: -15%
average wait, -55% SLO breaches, at the cost of +15% CTAS target misses.

## Event stream

Every clinical and operational event (arrivals, vitals, triage decisions,
deterioration, departures, SLI snapshots, SLO breaches, LLM calls) is emitted
as a versioned JSON envelope through a non-blocking batched bus. Sinks:

| Sink      | Use                                                        |
|-----------|------------------------------------------------------------|
| `file`    | `var/events.jsonl` (default)                               |
| `console` | stdout                                                     |
| `hec`     | HTTP Event Collector — Cribl Stream's Splunk HEC source, or Splunk |

Patient events carry synthetic PHI on purpose, so downstream pipelines can
demonstrate masking and redaction.
