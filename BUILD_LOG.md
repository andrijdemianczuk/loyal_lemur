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
| 6 | Demo polish: warm start, scenarios, scripts, push | In progress |
| 6a | Deterioration investigation; early bed requests | Done |
| 6b | 12-day validation, literature check, demo script, dry run | Done |
| 6c | AI decisions panel; decision ablation; script rework; slide; README; surge presets | Done |
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
- Everything is committed locally. Nothing has been pushed to GitHub yet. *(Correction, day 2: `ccab432` and everything before it had in fact been pushed.)*
- The dashboard server is running on port 8765.

---

## Day 2 — 2026-11-02

### Warm start (`d4f6a6e`)

**Problem:** every run started from an empty ED. Day 1 showed the system only
reaches steady state on day 2, so the opening minutes of a demo showed an
unrealistically quiet department.

**What we built:**
- The run's start time now means *when the demo opens*. The simulation begins
  30 simulated hours earlier and fast-forwards headlessly. That takes about
  1.2 seconds, so the UI simply waits for it.
- During warm-up:
  - the AI arm replays recorded Claude decisions only; a cache miss falls back to the rules triager, with no API calls and no stalls
  - no events are published, and downstream sees a single `run.started` event carrying a warm-up summary
  - any surge setting is held back until opening
- At opening, KPI counters and Claude stats reset. Patients carry over, so the
  ED opens loaded (about 17–31 patients, roughly half of them boarding).
- UI: a "Warm start" toggle (default on), a "Warming up…" button state, and a
  note that says how many patients were already in each ED.
- CLI: `simulate --warmup HOURS`. Run with `--ai claude`, it also records
  the warm-up decisions for replay.
- Fixed: the "Opens at" select always showed 00:00. It was a type mismatch
  between the select's string option values and a numeric model value.

### Opening time, KPI tiles, first recordings (`80ddf60`)

- **Opening time 14:00.** An hour-by-hour trace showed the waiting room nearly
  empty at 10:00, with queues building from 15:00 to 22:00. Opening at 14:00
  means the evening crunch arrives about 2 minutes into a demo at the default speed.
- **Wait tiles now measure "since opening".** The "last hour" average swung
  with the SLO-aware queue, and in one evening snapshot it showed the AI ED
  32% *slower* while it had 5 fewer SLO breaches. Since-opening values are
  steadier and match the numbers we quote. The last-hour line chart stays.
- **Recorded demo seeds:** seeds 3 and 7, each at normal volume and at 1.5×
  surge, covering 30 h of warm-up plus 24 h after opening. Offline replay
  reproduced every number exactly, with 0 cache misses.

### The deterioration investigation (`9f238ae`)

This is the most important story of the day, and a good one for the
presentation: **the data contradicted our headline claim, we found out why,
and we fixed the cause instead of the metric.**

**1. The problem.** The first recordings showed the AI ED with *more*
patients deteriorating while waiting on normal days (8 → 12 and 11 → 18).
Yesterday's 4-seed average had shown −38%. A clinician in the audience would catch this immediately.

**2. First finding: Claude's caution crowded the CTAS 2 queue.**
- Claude assigned CTAS 2 to 27 patients whose ground truth was CTAS 3,
  including all 14 anticoagulated head injuries. That's clinically defensible:
  anticoagulation is a CTAS modifier.
- The AI ED's CTAS 2 queue was twice as long (60 vs 28), so truly emergent
  patients waited 35 min vs 9 min, against a 15-minute target.
- The manual ED had a lucky shortcut: the nurse over-triaged 8 CTAS 2
  patients to CTAS 1, and CTAS 1 goes straight to resus without needing a bed.

**3. Hypotheses we tested and rejected.** Each was tested on the recorded seeds:

| Change to the AI arm | Effect on deteriorations |
|---|---|
| Rank CTAS 1–2 by current vital signs | No change |
| Rank CTAS 3 by Claude's red flags | No change (±1) |
| Rank CTAS 3 by *true* deterioration risk (diagnostic only, uses ground truth) | No change |
| Undo Claude's CTAS 3→2 over-triage (diagnostic only) | CTAS 2 waits halved, but CTAS 3 deteriorations rose |
| Open the intake zone only when no CTAS 1–2 is waiting | Much worse (deteriorations about doubled) |
| Stop streaming CTAS 3 walk-ins to fast track | No change |

**Conclusion:** queue order was never the lever. Whatever the order, patients
wait for **main beds, and about half of those beds are held by admitted
patients boarding** while they wait for an inpatient bed.

**4. Why the manual ED looked better.** A 12-seed comparison (AI arm on the
rules triager, so no API cost) showed deteriorations essentially flat (+4%)
while walk-outs fell 73%. The manual ED loses 5–12 patients a day to "left
without being seen", and a patient who has walked out can no longer
deteriorate in our count. The AI ED keeps nearly everyone, so more at-risk
patients are still in the waiting room. "Deteriorated or left unseen"
combined was −36% for the AI.

**5. The lever that works: predict admission at triage and request the bed then.**
This is a known operational intervention: today the bed request starts only
after the physician decides to admit. A diagnostic that shortened boarding
for admitted patients in the AI arm (12 seeds, rules triage, perfect
prediction):

| Boarding cut | Deteriorations, manual → AI | Avg wait, manual → AI |
|---|---|---|
| None | 7.9 → 8.2 (+4%) | 68 → 47 min |
| 60 min | 7.9 → 5.5 (−31%) | 68 → 36 min |
| 90 min | 7.9 → 4.6 (−42%) | 68 → 30 min |

We chose **60 minutes**, the conservative end. It still needs checking
against published effect sizes before we quote it as realistic.

**6. Implementation.**
- Claude's triage output gains `likely_admission`. The prompt version moves to
  `ctas-v2`; the v1 cache is kept.
- In the AI arm, a correctly predicted admission boards 60 minutes less. A
  missed admission gets no benefit. False alarms cost nothing in the model,
  but they are counted and shown.
- `eval-triage` now scores admission prediction. Because the simulated
  disposition is random given each presentation's admission rate, we also
  report a "best possible" ceiling:

  | Predictor | Accuracy | Precision | Recall |
  |---|---|---|---|
  | Haiku + Sonnet | 77% | 65% | 87% |
  | Best possible | 81% | 73% | 81% |

  Triage accuracy held up with the new prompt: 93% exact (94% on v1), 0
  emergent misses, 16 of 16 subtle cases caught.
- UI:
  - the AI engine panel shows early bed requests (made, needed, missed) and boarding time saved
  - the patient drawer marks "Likely admission · bed requested at triage"
  - "Why it matters" says "more" or "fewer" instead of showing negative counts, and adds a line for bed time freed

**7. Results on the recorded demo seeds** (24 h after opening, manual → AI):

| | Seed 3 normal | Seed 7 normal | Seed 3 surge | Seed 7 surge |
|---|---|---|---|---|
| Avg wait (min) | 98 → 54 | 94 → 45 | 221 → 157 | 212 → 152 |
| P90 wait (min) | 278 → 131 | 315 → 101 | 422 → 337 | 517 → 270 |
| Walk-in SLO breaches | 16 → 0 | 16 → 0 | 70 → 46 | 47 → 25 |
| Under-triaged | 28 → 5 | 27 → 6 | 52 → 9 | 60 → 9 |
| Left without being seen | 12 → 0 | 5 → 0 | 49 → 17 | 37 → 19 |
| Deteriorated while waiting | 8 → 11 | 11 → 13 | 39 → 31 | 52 → 39 |
| …of which CTAS 3, after their target time | 5 → 7 | 6 → 6 | 29 → 22 | 29 → 24 |

- Before the fix, normal-day deteriorations were 8 → 12 and 11 → 18. The
  early bed request closed most of that gap, but on these two seeds the AI
  ED still has slightly more.
- These two seeds are among the less favourable of the 12 days. Over 12
  seeds, the same 60-minute lever gives about −31% (with perfect prediction;
  Claude's recall is 87%).
- Under surge, the AI ED has 20–25% fewer deteriorations.

**8. What we are *not* claiming.**
- **Zero CTAS 3 deteriorations.** Both EDs share the same 20 beds with about
  half of them held by boarders, and some patients deteriorate within minutes
  of arrival. Zero would be neither achievable nor credible to a clinical audience.
- **Simulated outcomes as evidence.** Effect sizes come from a calibrated
  simulation, not clinical evidence.

**Presentation framing:**
- Better triage alone doesn't reduce harm; it reshuffles who waits.
- Harm falls when the AI frees capacity: predicting admissions at triage
  turns a 4–10 h boarding problem into earlier bed requests.
- We tested this honestly, including the experiments that failed.

### 12-day results with Claude, and choosing demo seeds

Seeds 3 and 7 looked unfavourable, so we recorded 10 more normal days with
Claude (seeds 1, 2, 4–6, 8–12). All 12 replay exactly offline.

Per simulated day, averaged over 12 days:

| Metric | Manual | AI | Change |
|---|---|---|---|
| Avg wait to physician | 68 min | 32 min | −53% |
| P90 wait | 177 min | 74 min | −58% |
| Walk-ins past 4 h SLO | 12.1 | 0 | −100% |
| Under-triaged at intake | 24.2 | 4.4 | −82% |
| Deteriorated while waiting | 7.9 | 5.0 | −37% |
| Left without being seen | 8.4 | 0.6 | −93% |
| Seen after true CTAS target | 47.8 | 31.7 | −34% |

- **The day-to-day spread is large.** Manual average waits range from 10 min
  (quiet days) to 260 min (seed 9). On the quietest days the AI ED is slightly
  slower (10 → 12 min), because there is nothing to optimize.
- **Deteriorations fall on 9 of 12 days.** The AI ED is slightly worse on 3:
  seeds 1 (2 → 3), 3 (8 → 11) and 7 (11 → 13).
- **Seed selection method:** rank each day by how close its relative
  AI-vs-manual changes (avg wait, P90, deteriorations, SLO breaches, walk-outs,
  under-triage) and its busyness are to the 12-day average.
  - **Seed 8** ranked first, so it's the demo seed: wait 68 → 29 min, deteriorations 8 → 3, SLO breaches 7 → 0.
  - **Seed 5** ranked second, so it's the backup: wait 69 → 41 min, deteriorations 8 → 4.
  - Seeds 3 and 7 ranked 3rd and 4th.
- **Credibility note:** with the bed lever, the headline numbers sit above
  the ~20–40% range the flow levers were calibrated to. We quote them as the
  combined effect of flow levers plus early bed requests, and we disclose
  that zero SLO breaches is a property of the SLO-aware queue in this
  simulation.

### Literature check: is a 60-minute boarding cut realistic?

**Short answer:** yes. It's conservative compared with the best available
evidence, but that evidence is simulation and retrospective, not prospective
trials.

| Source | Type | Finding |
|---|---|---|
| [Cheng, Argon, Ganesaraman & Ziya (2026), *Proactive Inpatient Bed Requests for ED Admissions*, arXiv 2607.15432](https://arxiv.org/abs/2607.15432) | Simulation based on data from a large ED (preprint) | From a 248-min boarding baseline, proactive bed requests cut boarding by about 70–170 min (30–70%) and ED length of stay by 6–15%, at a cost of about 1–95 min of idle bed time. A simple "greedy" policy cut boarding by about 152 min and length of stay by about 58 min, with about 35 min idle. |
| Chen et al. (2023), *Using Hospital Admission Predictions at Triage for Improving Patient Length of Stay in Emergency Departments*, Operations Research ([doi:10.1287/opre.2022.2405](https://pubsonline.informs.org/doi/10.1287/opre.2022.2405)) | Simulation (academic ED data) | Individualized early bed requests at triage reduce ED length of stay "without generating excessive false early bed requests." We could not verify the exact figures (paywalled). |
| [Triage nurse prediction of hospital admission (PubMed 22464226)](https://pubmed.ncbi.nlm.nih.gov/22464226) | Prospective, one community ED | Nurses predicted admission with 75.6% sensitivity and 84.5% specificity. It took about 5 hours from triage to an inpatient bed request. |
| [Hong et al. (2018), PLOS ONE](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0201016) | Retrospective, 560,486 visits | Triage-only models predict admission with AUC of about 0.87. |
| [Qiu et al. (2015), Health Care Management Science](https://link.springer.com/article/10.1007/s10729-014-9283-1) | Model tested on VA data | A bed-reservation policy driven by triage predictions reduced boarding times. |

**How our model compares:**
- **Size of the cut:** our boarding is 4–10 h (mean 420 min). A 60-min cut on
  correctly predicted admissions is about 14% of mean boarding, below the
  whole 30–70% simulated range.
- **Predictor quality:** Claude's recall (87%) and precision (65%) are in the
  same range as triage nurses and published models.
- **Gap:** our model gives false alarms no cost. In reality they idle an
  inpatient bed for a while (about 1–95 min in the Cheng et al. simulation),
  which costs the hospital rather than the ED.
- **Honest caveat:** no prospective trial measuring boarding reductions has
  been published yet. Our search found simulations and retrospective models
  only.

### Dry run of the delivery script

We ran the script for real against the dashboard (seed 8, paused at 14:00,
resumed at 2 sim-min/s) and sampled the screen every 15 seconds.

**What worked:**
- 3 real minutes covers exactly 14:00–20:00.
- By about 19:50 the manual ED's longest walk-in crosses 4 hours, while the AI ED's longest is 86 min. That's a natural climax to pause on.
- By 20:00, under-triage is 0 vs 10 and SLO breaches 0 vs 2.

**What it caught:**
1. **The average-wait tile favours manual during the evening** (48 vs 38 min at 20:00). The SLO-aware queue deliberately sees long-waiting walk-ins first, which raises the early average. Hour by hour, the AI pulls ahead at 23:00 and finishes the day at 29 vs 68 min, because the manual ED's backlog never clears overnight. The script had you pointing at that tile at 20:00 and quoting −53%.
2. **The first queued patient with a "Likely admission" chip appears at 16:29**, not at 14:00–15:00 as scripted.
3. **The backup seed (5) had the same problem for longer:** the AI trailed on average wait until 05:00.
4. **Fast-forwarding at 60× broke replay fidelity.** In replay mode the dashboard didn't wait for recorded decisions, so at high speed 18 arrived late, the patients' paths diverged, and 11 cache misses followed. Under-triage showed 7 instead of the recorded 2.
5. **Pausing by hand at 60× overshoots** by about an hour.

**Fixes:**
- **Replay mode now waits for each recorded decision.** A cache lookup is instant, so this costs nothing, and replays are now identical to the recording at any speed. Live API mode is unchanged (provisional rules, then the late decision is applied).
- **New "Skip to end of day" button** (`POST /api/skip`). It fast-forwards at 120× with the charts animating and pauses exactly 24 h after opening (`SimClock.pause_at`). Verified: 10.5 s, Sat 14:00 exactly, 0 late decisions, 0 fallbacks, and every number identical to the recording.
- **Script restructured:**
  - live segment from 14:00 to the 4-hour crossing at about 19:50
  - the admission chip moved to about 16:30
  - a presenter warning about the evening average tile
  - a 10-second skip over the night, narrated
  - results at Sat 14:00
  - backup seed changed to **4**: a harder day where the AI leads from the first hour (134 → 48 min)
  - new Q&A answers for the evening average and the 11-hour overnight walk-in wait
- **Realism flag (not changed):** a manual walk-in waits about 11 hours overnight. Our walk-out model is simple, and more of those patients would leave in reality.

### API spend, day 2

| Item | Calls | Cost (approx.) |
|---|---|---|
| v1 recordings (4 seeds) | 713 | $0.36 |
| v2 eval set + recordings | 1,322 | $0.67 |
| 10 more seeds (v2) | 2,781 | $1.48 |
| **Running total** | | **about $3.70** |

Costs are at the list prices in our price table.

### End of day state

**Summary of the day:**
- Demos open on a warmed-up ED at 14:00.
- We found and fixed the deterioration problem with early bed requests, and validated the result over 12 recorded days.
- The literature check supports the 60-minute assumption.
- The demo script is written, dry-run tested and fixed.
- The script is reworked around the core question: *which decisions, backed by AI, need to be made to improve wait times?* It's told as four decisions: who is most urgent, who is seen next, when to open capacity, and who will need a bed.

**State:**
- 28 tests passing.
- Everything through `73c0937` is pushed to GitHub. This end-of-day update is the only later commit.
- The database needs `ALTER TABLE triage_assessments ADD COLUMN admit_predicted boolean`.
  It is already applied locally; `initdb` on a fresh database creates it.
- Recorded demo runs (`ctas-v2`), all opening Fri 14:00:
  - seeds 1–12 at normal volume
  - seeds 3 and 7 at 1.5× surge
  - they live in the local `llm_responses` table, not in the repo
- Demo: seed **8**, backup **4**.
- Shut down for the day: Postgres stopped (`brew services stop postgresql@17`) and the dashboard server stopped.
- Deliverables for the presentation:
  - `docs/DEMO_SCRIPT.md`: the delivery script and Q&A, organized around the four AI-backed decisions (who is most urgent, who is seen next, when to open capacity, who will need a bed), with a presenter's decision map (`0852d04`)
  - this log: the day-2 story, results and lessons learned
- Analysis helpers (gitignored) in `var/analysis/`:
  - `pick.py` ranks seeds
  - `timeline.py` gives hourly metrics per seed
  - `dryrun.py` samples the live dashboard

**Next session:**
1. Start up:
   - `brew services start postgresql@17`
   - start the server with `nohup` (see the script's "Before the call")
   - set up seed 8, paused at Fri 14:00
2. **Make the four decisions visible on the dashboard: an "AI decisions" panel.**
   Today the screen mostly shows outcomes. Decision 3 (opening the
   rapid-assessment zone) is only an "open/closed" word in the capacity line,
   and decision 2 only shows indirectly through the walk-in chart. Log each
   decision as it happens, with its reason. For example:
   - "16:29 bed requested at triage: 81F hip fracture"
   - "21:00 kept rapid-assessment zone open: 2 physicians free, 5 walk-ins waiting"
   - "19:40 moved walk-in ahead: waiting 3 h 10, approaching the 4 h limit"
   - triage calls that raised acuity above the rules

   The decisions should also be emitted as events, so the pipeline-pitch
   profile can use them. Then update the script's live segment to point at
   the panel.
3. **Measure what each decision contributes.** Run all 12 recorded days with
   each AI decision switched off in turn: Claude triage → rules, SLO-aware queue →
   acuity-then-first-come, dynamic intake zone → scheduled hours, early bed
   requests → off. Report the change in average and P90 wait, SLO breaches,
   deteriorations and walk-outs. This replays from the existing recordings at
   no API cost (today's experiments had 0 cache misses), but check fallbacks
   per run. The result replaces the hedged "which decision matters most?" Q&A
   answer and becomes a slide: "what each decision is worth".
4. Timed in-person run-through of the four-decision script at the target screen resolution, after 2 and 3. Adjust the script from it.
5. README refresh: how to run, record and replay, and the headline results.
6. Scenario presets with time-limited surges, if there's time before presenting.

---

## Day 3 — 2026-11-04

### AI decisions panel (`c43578b`)

**Why:** the dashboard showed outcomes, but the point of the demo is the
*decisions*. Decision 3 was only an "open/closed" word on the capacity line,
and decision 2 only showed indirectly in the walk-in chart.

**What:** a new `ai.decision` event, emitted by the AI ED each time it acts
differently from standard practice, with the patient and the reason:

| Decision | Logged when | Example (seed 8) |
|---|---|---|
| `triage` | Claude assigns higher acuity than the vital-sign rules | "Raised to CTAS 2 (rules: 4): 76F epigastric pain · older diabetic woman, possible atypical ACS" |
| `queue` | A patient is seen ahead of someone that CTAS-then-first-come would have seen first | "Seen ahead of 6: 35M sore throat · waited 3 h 04, approaching the 4 h walk-in limit" |
| `intake` | The rapid-assessment zone is used outside the manual schedule (11:00–21:00) | "Rapid-assessment zone kept open: 31F earache · 3 physicians free, 4 walk-ins waiting" |
| `bed` | Claude predicts admission at triage (once per patient) | "Bed requested at triage: 76M hip injury · suspected L hip fracture" |

- The panel replaces the Live feed: four counters (one per decision, since opening) that also act as filters, and a list of the latest decisions. Click a line to open the patient.
- `TriageDecision` now carries `rules_ctas`, so "raised above the rules" is measured, not inferred.
- **Emit-only.** Replaying seed 8 gives exactly the recorded result (28.9 vs 67.5 min, 0 cache misses).
- **Decision:** the queue decision was first logged only when the 3-hour walk-in guard fired. That happened twice a day: the SLO-aware ordering rarely lets walk-ins get that close. The ordering itself is the decision, so it's now logged whenever someone is seen out of CTAS-then-first-come order.
- **Decision:** the intake zone is logged only when its use differs from the manual schedule. That makes it a night-time decision: it shows during the skip, not during the 14:00–20:00 live segment.
- Per demo day (seed 8): 53 beds requested, 25 triage upgrades, 12 seen out of order, 10 after-hours zone uses. That's about 4 per simulated hour, readable at 2×.
- The script's live segment now points at specific panel lines (15:11 triage upgrade, 16:03 bed request, 18:57 queue move), and at the zone counter during the skip.
- New test: all four decisions fire for the AI arm, none for the manual arm, and events match counters. 29 tests passing.

### Decision ablation: what each decision is worth

**Method:** the 12 recorded normal days, replayed offline with one decision at
a time reverted to standard practice. Each change applies from the start of the
30-hour warm-up, so every variant reaches its own steady state. 72 runs, about a
minute in total, 0 cache misses, no API cost.

- **without triage:** rules CTAS instead of Claude's. Claude still predicts admissions, but its fast-track streaming hint is dropped, because it comes with the triage call.
- **without queue:** CTAS-then-first-come ordering and lanes.
- **without zone:** the rapid-assessment zone runs on the manual schedule.
- **without beds:** no early bed requests.
- **all four off:** standard practice with rules triage.

**Results** (mean per day; change against all four on):

| | Avg wait | P90 wait | Walk-ins past 4 h | Deteriorated | Walk-outs | Under-triaged |
|---|---|---|---|---|---|---|
| Manual ED | 68.4 | 176.8 | 12.1 | 7.9 | 8.4 | 24.2 |
| **AI, all four on** | **32.0** | **74.2** | **0.0** | **5.0** | **0.6** | **4.4** |
| without triage | +7.0 | +16.3 | +0.2 | +1.1 | +0.8 | +19.3 |
| without queue | −2.2 | +1.7 | +2.0 | −0.1 | +0.7 | 0 |
| without zone | +16.9 | +55.6 | +3.7 | +2.7 | +1.5 | 0 |
| without beds | +5.6 | +13.4 | +0.2 | +1.2 | +0.2 | 0 |
| all four off | +41.4 | +95.9 | +14.2 | +5.8 | +9.1 | +19.3 |

How consistent each effect is (days worse / better without the decision, of 12):

| Without | Avg wait | P90 wait | Deteriorations |
|---|---|---|---|
| triage | 4 / 8 (median −1.8 min) | 4 / 8 | 3 / 5 |
| queue | 4 / 8 | 3 / 8 | 2 / 4 |
| zone | 11 / 1 (median +10.8) | 11 / 0 | 7 / 0 |
| beds | 8 / 4 (median +4.4) | 8 / 4 | 6 / 1 |

**What it means:**
1. **The dynamic zone is the biggest single lever** on every outcome, and the most consistent.
2. **Triage is a safety decision, not a speed decision.** On a typical day it doesn't change the average wait. Its value is under-triage (4 vs 24 a day) and protecting the hardest days: seeds 3, 4 and 7 lose 18–56 min of average wait without it.
3. **The queue is a deliberate tradeoff:** about 2 minutes of average wait for zero 4-hour breaches.
4. **Early bed requests** are solid but second: +5.6 min and +1.2 deteriorations a day without them.
5. **The decisions back each other up.** Single removals add up to about 27 min of average wait; switching all four off costs 41. With all four off, the AI ED is roughly back to the manual ED (73.5 vs 68.4 min), which is a sanity check: the gap comes from the four decisions, not the model setup.

**Correction to day 2.** On day 2 we said that with only the first three
decisions, the AI ED had *more* deteriorations than manual, and that bed
requests were the decision that reduces harm. That came from 2 seeds and a
rules-triage test. Across 12 Claude days without bed requests, the AI ED has
6.2 deteriorations a day vs 7.9 for manual, and is worse on only 2 days. The
zone matters more for harm than bed requests (+2.7 vs +1.2 a day).

**Script rework:** the presenter's map, the thesis, the scoring section, the
6:15–8:00 segment (now "What each decision is worth", with the table as a
slide) and the "which decision matters most?" Q&A now use the ablation
numbers. The day-2 "bed requests matter most" line is gone.

Ablation script (gitignored): `var/analysis/ablation.py`. Raw results are in
`var/analysis/ablation.json`; re-print the summary with `--summarize`.

### Slide, README, push (`00788fd`, `a5bc568`)

- `docs/slides/decision-worth.html`: a self-contained 16:9 slide of the ablation (light and dark), linked from the script's 6:15–8:00 segment.
- README rewritten around the four decisions, with the 12-day results, the ablation, how to run the demo, and how recording and replay work. Stale resource numbers were corrected.
- Pushed to GitHub through `a5bc568`.
- An offline replay of `eval-triage` has 1 cache miss (one escalation response was never stored), so it shows 92% exact / 76% admission accuracy against the recorded 93% / 77%. The docs keep the recorded figures.

### Surge presets

**Why:** the only surge was a whole-day 1.5× multiplier, which overwhelms
both EDs, and it drew patients from the same random stream as the normal day,
so a surge day was a different day altogether.

**Design:**
- Surge patients come from their own random stream (MRNs prefixed `S`), layered on top of an unchanged normal day. A test proves the normal day's patients are identical with and without a surge.
- The normal day's recorded triage calls still apply: only the surge patients needed recording (467 live calls for 3 presets × 12 days, about $0.20).
- Windows are clock times on the opening day, clipped to the opening time, so they never overlap the warm-up.
- Poisson-rate presets use a fixed count (the expected number), and only the times are random. Before this, the evening rush varied from 17 to 38 extra patients by seed.
- The UI's Arrivals menu now offers Normal day and the three presets; the whole-day 1.25×/1.5× options were removed (the `--surge` CLI flag remains). The surge window is shaded on the time charts, and a note gives the preset and patient count.

**Sizing (user decision):** the ED runs near capacity, so it's very
sensitive. In the manual ED (exact without recording, because it never uses
Claude), +8 patients raised the average wait about 35%; +17 nearly doubled it
and more than doubled deteriorations; +25 gave 151 min. We chose a moderate
size so the ED is clearly stressed but not collapsed:

| Preset | What | Extra patients |
|---|---|---|
| Evening rush | +35% arrivals, 17:00–21:00, normal mix | 12 |
| Multi-vehicle collision | Fixed casualty list at 18:30, all by ambulance: 2 major trauma, anticoagulated head injury, 2 neck/back, 2 lacerations, ankle; collision-specific triage notes | 8 |
| Respiratory wave | +15% arrivals, 12:00–24:00, weighted to URTI, fever, sore throat, SOB, vomiting, asthma, sepsis, respiratory failure | 12 |

**Results** (12 days, mean per day, manual → AI):

| Preset | Avg wait | P90 wait | Past 4 h | Under-triaged | Deteriorated | Walk-outs |
|---|---|---|---|---|---|---|
| Normal day | 68 → 32 | 177 → 74 | 12.1 → 0 | 24.2 → 4.4 | 7.9 → 5.0 | 8.4 → 0.6 |
| Evening rush | 104 → 56 | 255 → 140 | 21.7 → 1.8 | 27.3 → 4.7 | 15.9 → 9.2 | 16.1 → 2.0 |
| Collision | 101 → 48 | 259 → 116 | 18.4 → 0.1 | 28.4 → 4.4 | 14.9 → 7.2 | 13.8 → 0.8 |
| Respiratory wave | 101 → 51 | 243 → 125 | 21.5 → 0.9 | 28.2 → 5.3 | 14.8 → 8.9 | 16.2 → 1.9 |

The relative gains hold under every preset. The AI ED is worse than manual on
average wait on 1 of 36 surge days and on deteriorations on 4. Under the
evening rush it starts missing the 4-hour target (1.8 a day). Replays of seed 8
match the recordings exactly with 0 fallbacks.

Helpers (gitignored): `var/analysis/surge_size.py` (manual-arm sizing),
`var/analysis/record_surge.sh` (recording), `var/analysis/surge_summary.py`
(the table above, from `var/rec4/`).

### HEC sink against a real pipeline endpoint

First time the HEC sink has sent to a real collector (a cloud pipeline
platform's HEC source on port 8088) rather than a test transport. It worked
with configuration only (`ER_EVENT_SINKS=file,hec`, URL and token in `.env`).

- **Delivery stats:** `simulate` now ends with an `Events:` line: emitted,
  dropped, and sent or failed per sink. Before this, a failing sink only
  logged a warning.
- **Two events lost at shutdown:** the first run delivered 336 of 338. The
  final scorecard saves a whole-run metrics snapshot, which emits an event,
  and it ran after the bus had closed. The scorecard now runs before
  `bus.aclose()`. Now 338 of 338.
- **Bus shutdown drains instead of cancelling:** `aclose()` used to cancel the
  flush task, which could drop a batch taken off the buffer mid-write. It now
  signals the loop to finish and awaits it. (Not the cause above, kept anyway.)
- **Volume, measured (seed 8, one ED, both arms, 24 h):** 2,007 events, about
  1.3 MB. Largest: vitals 492, triage 312, metrics 192, arrivals 150, Claude
  calls 175, AI decisions 100. Too small to carry a cost argument by itself;
  the pipeline story is masking and routing. `patient.arrived` carries full
  synthetic PHI (name, DOB, health card, postal code, MRN); `llm.call`
  carries the MRN.

### State

- 36 tests passing.
- Pushed through `3df56e7` (surge presets). The HEC fixes above are uncommitted.
- API spend today: about $0.20 (surge recordings). Running total about $3.90.

**Next:**
1. The user's repeated run-throughs of the script, then adjust it.
2. Phase 7 has started: a PHI-masking pipeline, then routes by destination.
3. Talk tracks for the four audiences. Company-specific material stays out of
   the public repo.

---

## Day 4 — 2026-11-05

### Event pipeline: masking and routing by destination (Phase 7)

Built on a cloud pipeline platform's free tier, fed by the HEC sink with no
code changes. The platform configuration lives in the platform, not in this
repo; this section records the design and what we measured.

**Design:**
- **Parse once at the source.** HEC events arrive with the whole event as a
  JSON string in `_raw`. A pre-processing step parses it, so route filters can
  use `event_type`.
- **Masking pipeline** (applied to every destination except audit):
  - record and health card numbers become a salted SHA-256 hash, first 16
    characters: the same patient gets the same token, so joins still work;
  - names and date of birth removed (`age` is already a field);
  - postal code cut to its first 3 characters;
  - the MRN in `llm.call` gets the same hash, so Claude calls stay linked;
  - `_raw` is **rebuilt from the masked fields**. Masking the parsed fields
    alone leaves the original in `_raw`.
- **Four routes**, in order:

  | Route | Gets | Masked | Final |
  |---|---|---|---|
  | audit | every event, original | no | no (copy) |
  | alerts | `patient.deteriorated`, `slo.breach` | yes | no (copy) |
  | analytics | everything except `vitals.recorded` | yes | yes |
  | vitals | what's left (vitals), discarded | — | yes |

  Vitals are kept in the audit store only. Nothing of ours reaches the
  platform's default route: every event has a deliberate destination.
- **Three storage datasets** (audit, analytics, alerts), queried with the
  platform's search.

**Measured, one full replayed day** (seed 8, both arms, offline replay):

| Route | Events | Bytes |
|---|---|---|
| audit | 2,009 | 1.20 MB |
| analytics | 1,517 | 0.98 MB (about 20% less, all from leaving out vitals) |
| alerts | 18 | 9.4 KB |
| vitals (audit only) | 492 | 0.25 MB |

- Masking is byte-neutral: the 16-character hashes are longer than the
  originals, which cancels out the removed names and dates.
- The alert dataset reproduces the scorecard exactly: manual 8
  deteriorations and 7 SLO breaches, AI 3 deteriorations and no breaches.
- One AI triage decision (the 76F epigastric pain at 15:11) can be traced
  from the masked analytics view to the full audit record, with Claude's
  rationale, in two queries.

**Three things went wrong, each caught by checking the destination rather
than the pipe:**
1. **The platform's JSON serializer dropped the nested `data` object.** The
   route monitor then showed a 73% "reduction", which was really the clinical
   payload going missing. Found by reading one stored event. Replaced with an
   explicit expression that builds the JSON.
2. **Byte counts read 0 B** after the first masking version, because the
   platform measures bytes from `_raw` and the pipeline had deleted it.
   Rebuilding `_raw` fixed both the measurement and the design.
3. **One route's output was left on the default destination.** The route
   monitor showed a healthy flow while the analytics dataset stayed empty.

**Web server:** settings are only read at startup, so the server running
since day 3 had no HEC sink. It was restarted with the `pipeline-pitch`
profile, so live demo runs now stream to the pipeline. The old process didn't
exit on SIGTERM while a browser held its server-sent-events connection, and
needed a hard kill. (Known issue below.)

### State

- 36 tests passing. Pushed through `ce5feba` (HEC delivery fixes).
- No API spend today: every replay was offline. Running total about $3.90.
- Presentation material for specific audiences is kept outside this public
  repo.

**Next:**
1. Timed rehearsals of the demo, then adjust.
2. Phase 7: observability of AI calls (latency, escalations) from the stream.
3. Consider a buffered HEC sender (today it retries once, then counts the
   batch as failed).

---

## Lessons learned (running list)

Things we would tell someone building a similar system. Each one cost us
something to learn.

### About the domain

1. **Better triage alone doesn't reduce harm; it reshuffles who waits.**
   Accurate triage decides *who* waits. Wait times and deteriorations only
   fall when the AI also frees capacity: the dynamic intake zone, fast-track
   streaming, and early bed requests. (Days 1–2)
2. **Find the binding constraint before you optimize.** We tried five
   queue-ordering ideas against deteriorations. None worked, not even
   ordering by each patient's *true* risk. The constraint was main beds
   blocked by boarders, and no ordering can create a bed. (Day 2) The day-3
   ablation refined this: physician capacity (the dynamic zone) turned out to
   matter even more than beds. The constraint is capacity, not order. (Day 3)
3. **Over-triage has a cost.** Claude's caution was clinically defensible
   (anticoagulated head injuries at CTAS 2). It still doubled the CTAS 2
   queue and slowed the truly emergent patients. "Err on the side of
   caution" has to be weighed against the capacity it consumes. (Day 2)
4. **Ground truth can be debatable.** Our simulator labels the anticoagulated
   head injury CTAS 3; many clinicians would say CTAS 2. When the AI
   "disagrees" with the label, check the label too. (Day 2)

### About measurement

5. **Measure steady state, never from empty.** Day-1 numbers from an empty
   ED looked fine, then collapsed over several days. Hence the warm start. (Days 1–2)
6. **Count what leaves.** Patients who walk out can no longer deteriorate
   or breach an SLO, so an ED can look safer by losing them. We count
   walk-outs' waits, and we report "left without being seen" next to
   deteriorations. (Days 1–2)
7. **Rolling windows mislead on a live dashboard.** A "last hour" average
   showed the AI ED 32% slower while it had fewer SLO breaches. Headline
   numbers should be cumulative since opening. (Day 2)
8. **Small samples lie.** Average waits ranged from 10 to 260 minutes across
   12 simulated days. Two seeds were not enough to judge a policy. We
   compare across 12 days and demo days that are representative of the
   average, and we say so. (Day 2)
9. **Credible beats dramatic.** We calibrated to published improvement
   ranges (about 20–40%) rather than chasing bigger numbers. A clinical
   audience discounts results that look too good. (Day 1)

### About method

10. **Use diagnostics before building.** "Oracle" experiments, which are
    allowed to use ground truth but would never ship, told us the upper
    bound of an idea before we spent effort on it. Ordering by true risk did
    nothing, and a perfect admission prediction was worth −31%. (Day 2)
11. **Report the failed experiments too.** The rejected hypotheses are what
    make the final result believable. (Day 2)
12. **Show the ceiling, not just the score.** Admission prediction at 77%
    sounds mediocre until you see that 81% is the best possible, because
    dispositions are random given the presentation. (Day 2)

### About engineering

13. **Record-and-replay makes LLM demos deterministic and nearly free.** Total
    API spend for the project so far is a few dollars. Replays are exact,
    so demos can't be derailed by latency, outages or randomness. (Days 1–2)
14. **Cache keys pin recordings to every input.** Changing the start time or
    the prompt invalidates recordings. We recorded twice on day 2; settle
    the design first, then record. Version the prompt explicitly. (Day 2)
15. **Verify that background jobs actually started.** A zsh word-splitting
    mistake made a batch of recordings fail instantly. It cost nothing but
    time, because we checked the logs before waiting. (Day 2)
16. **Build guardrails into the AI path from the start.** Claude can never
    triage below the vital-sign rules, any error falls back to rules, and
    late decisions are logged rather than silently dropped. This is what
    lets the AI be fast without being fragile. (Day 1)

17. **Dry-run the demo against the real system, not the numbers.** Every
    number in the script was correct, but the order in which they appear on
    screen wasn't. At 20:00 the dashboard showed the opposite of what the
    script said. The dry run also found that fast-forwarding broke replay
    fidelity, which no test covered. (Day 2)
18. **Re-measure a story when the system changes.** "Bed requests are what
    reduce harm" came from 2 seeds and an older configuration. The 12-day
    ablation with Claude reversed it, and the script was built on it. The
    cheapest time to find that out is before presenting. (Day 3)
19. **Ablate one at a time, and all at once.** Single removals show what each
    decision is worth; switching all off shows the decisions back each
    other up (27 min vs 41 min), and that all-off lands back on the manual
    baseline, which validates the setup. Report how many days each effect
    holds on, not only the mean: triage's +7 min mean is a median of −2. (Day 3)
20. **Verify at the destination, not at the pipe.** Three pipeline bugs on
    day 4 all looked healthy on the route monitor: a serializer that dropped
    the payload (reported as a 73% "reduction"), byte counts measured from a
    field we had deleted, and a route sending to the wrong place. Reading one
    stored event, and reconciling counts end to end, found all three. A big
    volume reduction is a reason to check, not to celebrate. (Day 4)
21. **Account for every emitted event.** `simulate` now prints emitted vs sent
    per sink. That one line exposed two events emitted after the bus had
    closed. (Days 3–4)

---

## Remaining work

### Phase 6: Demo polish (next)

- [x] **Warm start** (day 2).
- [x] **Recorded seeds** matching the UI defaults: 3 and 7, normal and surge, opening 14:00 (day 2).
- [x] **Deterioration fix:** early bed requests from admission prediction (day 2).
- [x] **Scenario presets** (day 3): evening rush, multi-vehicle collision, respiratory wave; recorded for 12 days.
- [x] **Choose demo seeds:** 8 (backup 4), from 12 recorded days (day 2).
- [x] **Check the 60-minute boarding assumption:** it's conservative against the published simulations (day 2).
- [x] **Dry run of the delivery script** (day 2): found 5 issues, all fixed.
- [x] **"AI decisions" panel** (day 3): all four decisions visible as they happen, with reasons, and emitted as `ai.decision` events.
- [x] **Decision ablation** (day 3): what each decision contributes, over 12 days, replayed at no API cost.
- [x] **"What each decision is worth" slide** (day 3).
- [ ] **Rehearse the script** in person end to end, timed, at the target screen resolution.
- [ ] **Optional realism:** make walk-outs more likely after very long overnight waits.
- [ ] **Optional realism:** give false-positive bed requests a cost (idle inpatient bed time).
- [x] **Demo script** (day 2): `docs/DEMO_SCRIPT.md`, a 10-minute slot with a 3-minute live segment, plus a pipeline-pitch add-on and Q&A.
- [ ] **Narrative panel text** per profile in the dashboard ("Why it matters" is generic today).
- [x] **README refresh** (day 3).
- [x] **Push to GitHub** (day 2, through `3f5b6fe`).

### Phase 7: Event-pipeline integration (optional)

- [x] Route the HEC event stream through a pipeline platform (cloud free tier or local). Day 3: delivery verified.
- [x] PHI masking, routing and filtering by destination, and volume/cost reduction. Day 4: 4 routes, 3 datasets, measured.
- [ ] Observability of AI calls (latency, cost, escalations) from the event stream.

### Known issues / notes

- **The web server may not exit on SIGTERM** while a browser holds a
  server-sent-events connection; it needed `kill -9` on day 4. Check that only
  one process listens on 8765 after a restart.
- **The HEC sink retries once, then drops the batch** (counted as failed).
  Fine for a demo; production senders need disk buffering.

- Computer-use screen control lacks macOS Accessibility and Screen Recording permissions. Visual checks use headless Chrome on `/?snapshot` instead.
- Start the dev server with `nohup`, not inside a background task.
- Never wipe `llm_responses` without asking. It holds the recorded demo runs.
- The AI ED has slightly more deteriorations on 3 of the 12 recorded days (seeds 1, 3, 7). Disclose this if asked; see day 2.
