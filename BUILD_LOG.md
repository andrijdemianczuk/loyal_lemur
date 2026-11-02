# Build Log

A running record of what has been built, what was decided, and what remains.
Updated at the end of each working day.

**Goal:** a locally hosted AI decision-support demo for ER intake and triage.
Two simulated emergency departments receive the same synthetic arrivals. One is
triaged manually and the other with AI assistance. A live dashboard compares
them against the SLI/SLO:

- **SLI:** wait time to physician, by acuity (CTAS 1–5)
- **SLO:** walk-ins seen within 4 hours

**Stack:**
- **Runtime:** Python 3.14 (uv), PostgreSQL 17 (Homebrew)
- **Backend:** FastAPI
- **Frontend:** no-build UI (Alpine.js and ECharts from CDNs)
- **AI:** Anthropic API (Claude Haiku 5.5, escalating to Sonnet 5.5)
- **Events:** event bus with file, console and HEC sinks

---

## Status at a glance

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation: schema, config, event bus | Done |
| 2 | Synthetic EHR feed | Done |
| 3 | Two-arm ED flow model and calibration | Done |
| 4 | Claude triage for the AI arm | Done |
| 5 | Live web dashboard; steady-state recalibration | Done |
| 6 | Demo polish: warm start, scenarios, scripts, push | Next |
| 7 | Event-pipeline integration (optional) | Not started |

---

## Day 1 — 2026-11-01

### Phase 1: Foundation (`02c461b`)

- uv project (`er-triage`) with Postgres via SQLAlchemy 2 and psycopg.
- Settings come from pydantic-settings with `ER_` env vars.
- The API key is read from `.key`, which is gitignored and takes precedence over the environment.
- Schema:
  - sim runs, patients and encounters (one encounter per ED arm)
  - vital signs and triage assessments
  - metric snapshots
  - LLM response cache
- Event bus is non-blocking and batched. Sinks:
  - JSONL file
  - console
  - HEC, the Splunk HTTP Event Collector format, which HEC-compatible pipelines accept
  - in-memory
- Event types: run lifecycle, arrival, vitals, triage, deterioration, physician assigned, departure, SLO breach, metrics, LLM call.
- Demo profiles are neutral: `value-pitch` and `pipeline-pitch`. The repo is public.

### Phase 2: Synthetic EHR feed (`83a3659`)

- Arrivals follow a time-of-day Poisson process (default 150 per day).
- About 30 CEDIS-style presentations, including "subtle" cases that are easy to under-triage.
- Patients have realistic paired history and medications, Faker `en_CA` demographics and triage notes.
- Vitals are rechecked over time. Deterioration is driven by a per-patient fragility value.
- Ground-truth acuity (`true_ctas`) is stored for scoring and is never shown to the triagers.
- The sim clock has adjustable speed.

### Phase 3: Two-arm ED model (`efad9d3`, `f56d44f`)

- Both EDs have identical resources:
  - 6 doctors (5 main and 1 fast track)
  - 20 beds plus 4 hallway spaces for CTAS ≤2
  - fast track (09:00–23:00, 4 chairs, 60-minute chair cap)
  - intake zone and results area
  - resus bypass for CTAS 1
  - boarding for admitted patients
- **Manual ED:**
  - nurse triage with a calibrated error model: under/over-triage, missed subtle cases, error that grows with load
  - CTAS-then-FIFO queue
  - intake zone open on fixed hours
- **AI ED:**
  - SLO-aware queue: CTAS 1–2 first, then walk-ins approaching 4 hours, then by fraction of target elapsed
  - smarter fast-track streaming
  - intake zone opened dynamically
- Metrics are fair: measured against true acuity, grouped by arrival acuity, and walk-outs keep their waits.
- Determinism: per-patient RNG streams and a fixed 1-minute step grid. Both arms see identical patients, and replays match exactly.
- Results are calibrated to the published literature (~20–40% improvements). We chose credible numbers over dramatic ones.

### Phase 4: Claude triage (`8a21dba`)

- Haiku 5.5 is the primary triager. When its confidence is not "high", the case escalates to Sonnet 5.5, which happens about 8% of the time.
- Output is structured: CTAS level, confidence, rationale, red flags, immediate actions, fast-track eligibility.
- Guardrails:
  - Claude can never triage below the vital-sign rules.
  - The rules triager is the fallback on any error.
  - The prompt contains no ground truth.
- Live mode applies a provisional rules decision first. A late Claude decision is still applied, or logged with `applied=False` if the patient was already seen.
- Replay cache (`llm_responses`): record a seed once, then replay offline for deterministic demos at zero cost. `initdb --drop` preserves this table.
- Offline eval (`er-triage eval-triage`), exact CTAS match:

  | Triager | Exact match |
  |---|---|
  | Nurse | 75% |
  | Rules | 81% |
  | Claude | 94% |

  Claude had 0 emergent misses and caught 16 of 16 subtle cases.
- Total API spend to date: about $1.20.

### Phase 5: Live dashboard (`25a03ee`)

- FastAPI with server-sent events (SSE), one full state snapshot per second.
- Run controls: seed, start time, surge, AI mode (live / replay / rules), pause/resume, speed (0.5–60×).
- 6 KPI tiles comparing AI with manual.
- 3 charts, each with a data-table view:
  - wait over time
  - longest walk-in wait against the SLO
  - waiting room by acuity
- Live queues for both EDs with capacity. A ground-truth toggle shows under-triaged patients.
- Patient drawer: vitals, triage note, and every triage decision with Claude's rationale.
- Panels: "Why it matters", AI engine (calls, replays, escalations, cost) and live event feed. The `pipeline-pitch` profile adds a pipeline panel.
- Light and dark themes, colorblind-safe. Color only identifies the ED.
- **Recalibration:** 8–18 h boarding collapsed both EDs over multiple days. Boarding is now 4–10 h, and results are measured on days 2–3 (steady state) rather than day 1.

  Steady-state results (4 seeds, days 2–3, per day):

  | Metric | Manual | AI | Change |
  |---|---|---|---|
  | Under-triaged | 23.2 | 4.8 | −80% |
  | Avg wait to physician | 60 min | 35 min | −42% |
  | P90 wait | 164 min | 96 min | −42% |
  | Walk-in SLO breaches | 8.7 | 0 | −100% |
  | Deteriorations while waiting | 6.8 | 4.2 | −38% |
  | Left without being seen | 5.9 | 0.8 | −87% |

**End of day state:**
- 23 tests passing.
- Everything is committed locally. Nothing has been pushed to GitHub yet.
- The dashboard server is running on port 8765.

---

## Remaining work

### Phase 6: Demo polish (next)

- [ ] **Warm start:** fast-forward so demos open on a loaded, steady-state ED instead of an empty one.
- [ ] **Scenario presets:** e.g. evening surge, quiet start then a sudden rush. Each one is pre-recorded for offline replay.
- [ ] **Recorded seeds** whose start times match the UI defaults. The replay cache depends on start time, and the current recordings are at 08:00 while the UI default is 10:00.
- [ ] **Narrative content** for each profile (`value-pitch`, `pipeline-pitch`).
- [ ] **Demo scripts:** one 3-minute walkthrough per profile.
- [ ] **README refresh.**
- [ ] **Push to GitHub** (needs explicit approval).

### Phase 7: Event-pipeline integration (optional)

- [ ] Route the HEC event stream through a pipeline platform (cloud free tier or local).
- [ ] PHI masking, routing and filtering by destination, and volume/cost reduction.
- [ ] Observability of AI calls (latency, cost, escalations) from the event stream.

### Known issues / notes

- Computer-use screen control lacks macOS Accessibility and Screen Recording permissions. Visual checks use headless Chrome on `/?snapshot` instead.
- Start the dev server with `nohup`, not inside a background task.
- Never wipe `llm_responses` without asking. It holds the recorded demo runs.
