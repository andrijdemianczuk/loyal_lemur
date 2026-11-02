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
   blocked by boarders, and no ordering can create a bed. (Day 2)
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

---

## Remaining work

### Phase 6: Demo polish (next)

- [x] **Warm start** (day 2).
- [x] **Recorded seeds** matching the UI defaults: 3 and 7, normal and surge, opening 14:00 (day 2).
- [x] **Deterioration fix:** early bed requests from admission prediction (day 2).
- [ ] **Scenario presets:** time-limited surges (e.g. a 3–4 h evening rush). A 24-hour 1.5× surge overwhelms both EDs, which isn't realistic. Pre-record each preset.
- [x] **Choose demo seeds:** 8 (backup 4), from 12 recorded days (day 2).
- [x] **Check the 60-minute boarding assumption:** it's conservative against the published simulations (day 2).
- [x] **Dry run of the delivery script** (day 2): found 5 issues, all fixed.
- [ ] **"AI decisions" panel:** make all four decisions visible as they happen, with reasons, and emit them as events (next session).
- [ ] **Decision ablation:** what each decision contributes, over 12 days, replayed at no API cost (next session).
- [ ] **Rehearse the script** in person end to end, timed, at the target screen resolution.
- [ ] **Optional realism:** make walk-outs more likely after very long overnight waits.
- [ ] **Optional realism:** give false-positive bed requests a cost (idle inpatient bed time).
- [x] **Demo script** (day 2): `docs/DEMO_SCRIPT.md`, a 10-minute slot with a 3-minute live segment, plus a pipeline-pitch add-on and Q&A.
- [ ] **Narrative panel text** per profile in the dashboard ("Why it matters" is generic today).
- [ ] **README refresh.**
- [x] **Push to GitHub** (day 2, through `3f5b6fe`).

### Phase 7: Event-pipeline integration (optional)

- [ ] Route the HEC event stream through a pipeline platform (cloud free tier or local).
- [ ] PHI masking, routing and filtering by destination, and volume/cost reduction.
- [ ] Observability of AI calls (latency, cost, escalations) from the event stream.

### Known issues / notes

- Computer-use screen control lacks macOS Accessibility and Screen Recording permissions. Visual checks use headless Chrome on `/?snapshot` instead.
- Start the dev server with `nohup`, not inside a background task.
- Never wipe `llm_responses` without asking. It holds the recorded demo runs.
- The AI ED has slightly more deteriorations on 3 of the 12 recorded days (seeds 1, 3, 7). Disclose this if asked; see day 2.
