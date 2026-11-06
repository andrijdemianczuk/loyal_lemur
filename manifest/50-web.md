# 50 — Web API and dashboard

## Simulation manager

Owns at most one live run for the web app.

**Run parameters** (defaults): seed 3, speed 2.0 sim-min/s, surge multiplier
1.0, preset `normal` (or a key from `30`), volume 150/day, AI mode `replay`
(`claude` = live API, `replay` = cache only and blocking, `rules` = no LLM),
opening time `2026-11-06T14:00:00-07:00`, warm-up 30 h.

- **Start:** stop any existing run, build the engine with the simulated start
  = opening − warm-up, run the warm-up off the event loop (report
  "warming up" meanwhile), then hand the engine over and start ticking.
  Replay mode makes the AI triager blocking so replays are exact at any speed.
- **Pause / resume / set speed** act on the sim clock.
- **Skip to end of day:** fast-forward (speed 120) to 24 h after opening,
  then pause exactly there and restore the previous speed.
- **Series:** sample both arms every 5 sim-minutes for the charts.
- **State snapshot** (JSON, about once a second): run info (seed, preset,
  opening, warm-up summary, skipping), sim clock, per arm: since-opening KPIs
  (avg and P90 wait, SLO breaches, target misses, under-triaged,
  deteriorations, LWBS, seen), by-CTAS table, capacity in use (main beds +
  hallway, fast track, intake, results area, boarding), waiting list rows
  (name, age/sex, complaint, assigned vs true CTAS, wait, lane or "triage",
  flags for near-SLO and deteriorated), admission prediction and boarding
  saved; the time series; recent feed events; recent AI decisions (kept in
  their own buffer of 100 so busy events can't push them out); telemetry
  (event counts by type, sink stats, LLM calls, replays, escalations,
  fallbacks, tokens, estimated cost).

## API

| Method | Path | Does |
|---|---|---|
| GET | `/` | the dashboard |
| GET | `/health` | `status` ok/degraded, `database` reachable, `anthropic_key_configured`, `demo_profile`, event bus stats |
| POST | `/api/run` | start a run (body: run parameters, validated: speed 0–60, surge 0–3, volume 0–600, warm-up 0–72 h) |
| POST | `/api/stop` | stop the run |
| POST | `/api/pause` · `/api/resume` | pause or resume |
| POST | `/api/skip` | skip to the end of the day |
| POST | `/api/speed` | body `{speed}` |
| GET | `/api/state` | one state snapshot |
| GET | `/api/stream` | server-sent events: a full snapshot every second |
| GET | `/api/encounter/{id}` | one encounter: timeline, patient, all vitals, all triage assessments (source, CTAS, rationale, red flags, model, latency, applied, admission prediction); 404 if not saved yet |

## Dashboard

One page, no build step, readable on a projector.

- **Header:** title "ED Triage Decision Support", sim clock, controls: seed,
  opens at (00/06/08/10/14/18:00), arrivals (normal day or a surge preset),
  AI triage (recorded replay / live API / rules only), warm start toggle,
  Start new run, Pause/Resume, speed, Skip to end of day.
- **KPI tiles**, each showing the AI ED and the manual ED side by side with
  the difference: average wait, P90 wait, walk-ins past 4 h, longest walk-in
  wait now.
- **Two charts over time:** average wait for both EDs; longest walk-in wait
  against the 4 h line. Shade a surge window if one is active.
- **Two ED columns** ("Manual triage ED", "AI-assisted ED"): capacity in use,
  by-CTAS waiting and average wait, and the waiting list (who, complaint,
  assigned CTAS with "really N" when it differs from true, wait, lane;
  near-SLO and deteriorated flags). Clicking a patient opens the detail
  drawer.
- **"Why it matters" panel:** plain-language differences so far
  (deteriorations, walk-outs, SLO breaches, under-triage, in words: "3 fewer").
- **"AI decisions" panel:** the four decisions as they happen, each with time,
  tag (triage / queue / intake / bed), patient, and reason. Counts per
  decision. Bed requests show boarding time saved.
- **"AI triage engine" panel:** calls, replays, escalations, fallbacks,
  tokens, estimated cost.
- **"Behind it: the event stream" panel:** events by type and per-sink
  delivery (sent / failed), so a downstream pipeline is visibly fed.
- **Patient drawer:** name, complaint, triage note, history, assigned vs true
  CTAS, the triage decisions (source, level, rationale, red flags, model),
  and a vitals table.
- **`?snapshot`:** render one state fetch without a live connection (for
  headless screenshots).
- Empty state: "No simulation running".
