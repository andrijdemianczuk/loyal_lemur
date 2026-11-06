# ER Triage Decision Support

AI-assisted emergency department intake and triage, demonstrated on a live,
synthetic hospital data feed. The same stream of arriving patients is run
through two parallel EDs — **manual triage** and **AI-assisted triage** — with
the same staff and beds, so the effect on wait times is visible side by side,
in real time.

**The question it answers:** *which decisions, backed by AI, need to be made
to improve wait times?* The demo is organized around four of them:

| # | Decision | Manual ED | AI-assisted ED |
|---|---|---|---|
| 1 | **Who is most urgent?** | Nurse triage under pressure | Claude triages with a rationale; it can raise acuity above the vital-sign rules, never lower it |
| 2 | **Who is seen next?** | CTAS, then first-come | SLO-aware queue: CTAS 1–2 first, then by how far each patient is through their CTAS target; walk-ins nearing 4 h go first |
| 3 | **When do we open more capacity?** | Rapid-assessment zone on fixed hours (11:00–21:00) | Zone opened whenever physicians are free and walk-ins are waiting |
| 4 | **Who will need a bed?** | Bed requested after the physician decides to admit | Claude predicts admission at triage and the bed request starts then |

- **SLI:** time from arrival to physician, by CTAS level
- **SLO:** walk-in patients seen in under 4 hours
- **Triage scale:** CTAS (Canadian Triage and Acuity Scale, levels 1–5)
- **Data:** 100% synthetic. No real patient information.

## Results

Mean per day over 12 simulated days, recorded with Claude, measured from a
warmed-up ED (30 h of history before opening), identical resources:

| Metric | Manual | AI-assisted | Change |
|---|---|---|---|
| Avg wait to physician | 68 min | 32 min | −53% |
| P90 wait to physician | 177 min | 74 min | −58% |
| Walk-ins past the 4 h SLO | 12.1 | 0 | −100% |
| Under-triaged at intake | 24.2 | 4.4 | −82% |
| Deteriorated while waiting | 7.9 | 5.0 | −37%\* |
| Left without being seen | 8.4 | 0.6 | −93% |
| Seen after true CTAS target | 47.8 | 31.7 | −34% |

The improvements are calibrated to land in published ranges (rapid-assessment
zones about 20–40%), not tuned to look dramatic. Results vary a lot by day:
on the quietest days there is nothing to decide and the two EDs perform about
the same.

\* **Deteriorations are a trend, not a proven result.** Compared day by day
(same patients in both EDs), the AI ED does better on 7 days, worse on 3 and
ties on 2, which is not statistically significant over 12 days (sign test
p ≈ 0.34). Under-triage (better on 12 of 12 days), average wait (10 of 12),
4-hour breaches and walk-outs do hold up.

### What each decision is worth

The same 12 days replayed with each AI decision switched back to standard
practice in turn (change in the AI ED against all four on, per day):

| Without | Avg wait | P90 wait | Walk-ins past 4 h | Deteriorated | Under-triaged |
|---|---|---|---|---|---|
| AI triage (rules CTAS instead) | +7.0 | +16.3 | +0.2 | +1.1 | +19.3 |
| SLO-aware queue | −2.2 | +1.7 | +2.0 | −0.1 | 0 |
| Dynamic rapid-assessment zone | +16.9 | +55.6 | +3.7 | +2.7 | 0 |
| Early bed requests | +5.6 | +13.4 | +0.2 | +1.2 | 0 |
| All four | +41.4 | +95.9 | +14.2 | +5.8 | +19.3 |

- The **dynamic zone** is the biggest single lever.
- **Triage** is the safety decision: it barely moves the average wait on a typical day, but it keeps under-triage at 4 a day instead of 24 and protects the hardest days.
- The **queue** trades 2 minutes of average wait for zero 4-hour breaches.
- **Bed requests** add to all of it.
- The decisions back each other up: switch all four off and the AI ED falls back to the manual one.

Slide: [`docs/slides/decision-worth.html`](docs/slides/decision-worth.html).
Method and caveats: [`BUILD_LOG.md`](BUILD_LOG.md), day 3.

These are simulation results, not clinical evidence.

### Under a surge

Three time-limited surge presets add patients on top of the same normal day
(same patients, plus extra ones from a separate random stream), recorded for
all 12 days. Mean per day, manual → AI:

| Preset | Extra patients | Avg wait | Walk-ins past 4 h | Deteriorated | Left without being seen |
|---|---|---|---|---|---|
| Normal day | 0 | 68 → 32 min | 12.1 → 0 | 7.9 → 5.0 | 8.4 → 0.6 |
| Evening rush (+35%, 17:00–21:00) | 12 | 104 → 56 min | 21.7 → 1.8 | 15.9 → 9.2 | 16.1 → 2.0 |
| Multi-vehicle collision (18:30) | 8 by ambulance | 101 → 48 min | 18.4 → 0.1 | 14.9 → 7.2 | 13.8 → 0.8 |
| Respiratory wave (+15%, 12:00–24:00) | 12 | 101 → 51 min | 21.5 → 0.9 | 14.8 → 8.9 | 16.2 → 1.9 |

The ED runs close to capacity, so a dozen extra patients raise the manual
ED's average wait by about half. The presets are sized to stress it without
collapsing it. The collision is a fixed casualty list (2 major trauma, an
anticoagulated head injury, and walking wounded) with collision-specific
triage notes.

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
uv run er-triage serve          # dashboard at http://127.0.0.1:8000
uv run pytest
```

Put your Anthropic API key in `.key` (gitignored). Copy `.env.example` to
`.env` to change settings (all use the `ER_` prefix).

## Running the demo

The demo replays recorded Claude decisions, so it is deterministic, free, and
works offline. The delivery script is [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md).

```bash
brew services start postgresql@17
nohup uv run er-triage serve --port 8765 > var/server.log 2>&1 &
```

Open http://127.0.0.1:8765, choose seed **8** (backup **4**), opening 14:00,
"Normal day", AI triage "Claude (recorded replay)", warm start on, then
**Start new run** and **Pause**. At 2 sim-min/s, three real minutes covers
14:00–20:00; **Skip to end of day** fast-forwards to Sat 14:00 for the
full-day results.

Start the server with `nohup`, not as a child of a process that may be
stopped, or it goes down with it.

## Recording and replaying

Every Claude response is stored in the `llm_responses` table, keyed by the
exact request (prompt version, patient, vitals). A replay with `--offline`
makes zero API calls and reproduces the recording exactly; a cache miss falls
back to the rules triager and is counted. `initdb --drop` preserves the table.
Recordings are pinned to every input, including the opening time, so record
with the same settings you will replay with:

```bash
# Record one day (about $0.15 of API calls, including the 30 h warm-up), then replay it for free
uv run er-triage simulate --seed 8 --ai claude --warmup 30 \
    --start 2026-11-06T14:00:00-07:00 --minutes 1440 --speed 600
uv run er-triage simulate --seed 8 --ai claude --offline --warmup 30 \
    --start 2026-11-06T14:00:00-07:00 --minutes 1440 --speed 600
```

Add `--preset evening-rush|mvc|flu-wave` to record or replay a surge day
(only the surge patients are new, so recording a preset costs a few cents).

Seeds 1–12 have been recorded with prompt `ctas-v2`, opening Fri 2026-11-06
14:00, for the normal day and all three surge presets (plus seeds 3 and 7 at a
whole-day 1.5× surge). They live in the local database, not in the repo.

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
bypass, a fast track (1 physician, 4 chairs, 09:00-23:00), a 2-chair
rapid-assessment (intake) zone staffed by idle main physicians, an 8-space
results-waiting area, and 2 triage nurses. Admitted patients board for 4-10 h
(access block). They differ only in decisions:

|                 | Baseline (manual)                    | AI-assisted                                   |
|-----------------|--------------------------------------|-----------------------------------------------|
| Triage          | Nurse model with realistic error     | Claude (rules fallback), with a vital-sign guardrail |
| Reassessment    | Notices deterioration ~50% of time   | Re-scores at every vitals check               |
| Queue order     | CTAS, then first-come-first-served   | CTAS 1-2 first; walk-ins near SLO; then % of target elapsed |
| Fast track      | Assigned CTAS 4-5                    | Claude's fast-track call; stable ambulatory CTAS 3 under 65 |
| Intake zone     | Fixed hours (11:00-21:00)            | Opened dynamically when physicians are idle   |
| Bed request     | After the physician decides to admit | At triage for predicted admissions (60 min less boarding when right) |

Every per-patient outcome (treatment time, admission, boarding, patience,
deterioration threshold, vitals noise) is drawn once and shared by both
arms; a test proves changing one arm cannot change the other. Performance
is scored against **true** acuity, and patients who leave without being
seen keep their wait in the statistics so an ED can't look faster by
losing patients.

**Warm start:** a run simulates 30 hours before the demo opens (replay only,
events muted), so both EDs open in a realistic steady state with patients
already boarding. KPIs count from opening. Starting from an empty ED flatters
both arms.

The 60-minute boarding cut is deliberately conservative against published
simulations of proactive bed requests (30–70% cuts from a ~4 h baseline);
see the literature check in `BUILD_LOG.md`, day 2.

## AI triage (Claude)

`src/er_triage/ai/claude_triage.py`:

- **Routing:** Claude Haiku 5.5 triages every patient; low-confidence cases
  escalate to Claude Sonnet 5.5 (~8%). Structured output via
  `messages.parse` with a Pydantic schema; the static CTAS system prompt is
  prompt-cached.
- **Outputs:** CTAS level, rationale, red flags, immediate actions,
  fast-track eligibility and likely admission.
- **Inputs:** only what a triage nurse sees. Never ground truth or ED load.
- **Guardrail:** Claude can raise acuity above the vital-sign rules, never
  lower it.
- **Resilience:** any error, refusal, or timeout falls back to the CTAS rules
  calculator. In live mode the patient is triaged provisionally by rules if
  Claude hasn't answered yet, and Claude's decision is applied on arrival
  (or recorded for audit if the patient was already seen).

Offline accuracy on 120 stratified synthetic patients
(`uv run er-triage eval-triage`):

| Triager          | Exact | Under-triage | Emergent missed | Subtle caught |
|------------------|-------|--------------|-----------------|---------------|
| Nurse model      | 75%   | 22%          | 16              | 5/16          |
| CTAS rules       | 81%   | 18%          | 13              | 0/16          |
| Claude (routed)  | 93%   | 1%           | 0               | 16/16         |

Admission prediction at triage: 77% accurate (65% precision, 87% recall),
against a best possible 81% for this data, because the simulated disposition
is random given the presentation.

Caveat: synthetic triage notes are cleaner than real ones. This is a
demonstration, not clinical validation.

## Live dashboard

`uv run er-triage serve`, then open http://127.0.0.1:8000. FastAPI serves a
single page (Alpine.js + ECharts from CDN, no build step) that receives a full
state snapshot every second over server-sent events:

- KPI tiles comparing both EDs since opening, charts of wait to physician,
  longest walk-in wait against the 4 h SLO, and the waiting room by true
  acuity (each with a data-table view)
- both live queues with capacity (beds, hallway, boarding, fast track,
  intake, results area); "Show ground truth" reveals under-triaged patients
- **AI decisions panel:** each time the AI ED acts differently from standard
  practice, with the reason. One counter per decision (also a filter) and a
  list of the latest; click a line to open the patient
- click a patient for the triage note, vitals, and every triage decision
  with Claude's rationale, red flags, likely admission and latency
- controls: seed, opening time, arrivals (normal day or a surge preset, shaded
  on the time charts), AI mode (live
  Claude, recorded replay, rules only), warm start, pause/resume, speed,
  skip to end of day
- `ER_DEMO_PROFILE=pipeline-pitch` adds the event-stream and sink panel

Light and dark themes use the reference data-viz palette: color identifies
the ED (blue AI, orange manual) and nothing else. `/?snapshot` renders a
single static state (for screenshots).

## Event stream

Every clinical and operational event (arrivals, vitals, triage decisions,
AI decisions, deterioration, departures, SLI snapshots, SLO breaches, LLM
calls) is emitted as a versioned JSON envelope through a non-blocking batched
bus. Sinks:

| Sink      | Use                                                        |
|-----------|------------------------------------------------------------|
| `file`    | `var/events.jsonl` (default)                               |
| `console` | stdout                                                     |
| `hec`     | HTTP Event Collector — Cribl Stream's Splunk HEC source, or Splunk |

`ai.decision` events carry the decision (`triage`, `queue`, `intake`, `bed`),
the patient and the reason, so a downstream pipeline can observe what the AI
decided and why. Patient events carry synthetic PHI on purpose, so downstream
pipelines can demonstrate masking and redaction.

## Project docs

- [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md): the 10-minute delivery script and Q&A
- [`docs/slides/decision-worth.html`](docs/slides/decision-worth.html): "What each decision is worth" slide
- [`manifest/`](manifest/): the whole project as specifications. Run `./manifest/build-it <empty-folder>` and a coding agent rebuilds it from the Markdown
- [`BUILD_LOG.md`](BUILD_LOG.md): what was built each day, decisions, experiments (including the ones that failed) and lessons learned
