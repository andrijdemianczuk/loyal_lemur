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

Calibrated to a crowded urban ED (8-18h boarding). Flow levers alone land
within published ranges for rapid-assessment zones (~20-40%).

Result with Claude triage, mean of 8 simulated days, identical resources:

| Metric                          | Manual   | AI-assisted | Change |
|---------------------------------|----------|-------------|--------|
| Under-triaged at intake         | 20.5     | 6.4         | -69%   |
| Avg wait to physician           | 52.8 min | 31.6 min    | -40%   |
| P90 wait to physician           | 165 min  | 91 min      | -45%   |
| Walk-in 4h SLO breaches / day   | 10.5     | 0.8         | -93%   |
| CTAS 2 average wait             | 14.4 min | 9.1 min     | -37%   |
| Deteriorated while waiting      | 8.6      | 5.2         | -39%   |
| Left without being seen         | 7.2      | 1.6         | -78%   |

Better triage alone mostly changes *who* waits (sick patients first); the
overall wait reduction comes from flow decisions. Both are needed.

## AI triage (Claude)

`src/er_triage/ai/claude_triage.py`:

- **Routing:** Claude Haiku 5.5 triages every patient; low-confidence cases
  escalate to Claude Sonnet 5.5 (~8%). Structured output via
  `messages.parse` with a Pydantic schema; the static CTAS system prompt is
  prompt-cached.
- **Inputs:** only what a triage nurse sees. Never ground truth or ED load.
- **Guardrail:** Claude can raise acuity above the vital-sign rules, never
  lower it.
- **Resilience:** any error, refusal, or timeout falls back to the CTAS rules
  calculator. In live mode the patient is triaged provisionally by rules if
  Claude hasn't answered yet, and Claude's decision is applied on arrival
  (or recorded for audit if the patient was already seen).
- **Replay:** every response is stored in `llm_responses`, keyed by the exact
  request. Re-running a seed with `--offline` replays it with zero API calls
  and identical results. `initdb --drop` preserves this table.

Offline accuracy on 120 stratified synthetic patients
(`uv run er-triage eval-triage`):

| Triager          | Exact | Under-triage | Emergent missed | Subtle caught |
|------------------|-------|--------------|-----------------|---------------|
| Nurse model      | 75%   | 22%          | 16              | 5/16          |
| CTAS rules       | 81%   | 18%          | 13              | 0/16          |
| Claude (routed)  | 94%   | 1%           | 0               | 16/16         |

Caveat: synthetic triage notes are cleaner than real ones. This is a
demonstration, not clinical validation.

```bash
uv run er-triage simulate --minutes 1440 --speed 120 --seed 3 --ai claude            # record
uv run er-triage simulate --minutes 1440 --speed 120 --seed 3 --ai claude --offline  # replay
```

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
