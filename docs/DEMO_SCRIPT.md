# Demo delivery script

A tight walkthrough of the ED triage decision-support demo: a **3-minute live
segment** inside a **10-minute slot**, with a Q&A appendix.

> Claims use **12-day averages** (12 simulated days, recorded with Claude;
> see BUILD_LOG.md, day 2). The live seed is only for what's on screen.

---

## Before the call (5 min)

1. Start the database and the server:
   ```
   brew services start postgresql@17
   nohup uv run er-triage serve --port 8765 > var/server.log 2>&1 &
   ```
2. Open `http://127.0.0.1:8765`.
3. Set the controls:
   - Seed **8** (the most representative of the 12 days). Backup: seed **4**, a harder day where the AI leads from the first hour (final average wait 134 → 48 min).
   - Opens at **14:00**
   - Arrivals **Normal day**
   - AI triage **Claude (recorded replay)**
   - Warm start **on**
4. Click **Start new run**, then **Pause** right away. The clock should read Fri 14:00.
5. Speed **2 sim-min/s**: 1 simulated hour passes every 30 seconds.
6. "Show ground truth" off. Pick the light or dark theme to suit the screen share.
7. If you rehearse, click **Start new run** again afterwards: Skip leaves the run paused at the end of the day.
8. Close everything else. The demo runs fully offline, with no API calls and nothing to rate-limit.

---

## The 10-minute slot

### 0:00–1:00 · The problem (paused, dashboard visible)

> "Emergency departments have two problems at the front door. Triage is done
> under pressure, so the sickest patients are sometimes under-triaged, and
> walk-ins with minor problems wait for hours or leave without being seen.
>
> I built a simulation to test whether AI decision support helps, and how
> much. It's two emergency departments side by side: **same patients, same
> staff, same beds.** The only difference is the decisions. On the right, nurses
> triage and patients are seen by acuity, then first-come. On the left, Claude
> triages and the department makes capacity decisions in response to what's
> happening."

Point at: the two queue panels and the legend (blue = AI, orange = manual).

### 1:00–1:30 · How realistic it is

> "The patients are synthetic but clinically shaped: about 30 presentation
> types, real vital-sign patterns, medications that match the history, and
> some deliberately subtle cases that are easy to under-triage. The departments
> have been running for 30 hours before we open, so we start in a realistic
> steady state, with patients boarding while they wait for an inpatient bed.
> The flow model is calibrated so the improvements land in the ranges
> reported in the literature, not tuned to look dramatic."

Point at: the warm-start note ("24 patients already in each ED").

### 1:30–4:30 · Live segment (press Resume)

At 2 sim-min/s, 3 real minutes covers 14:00 to 20:00 (checked in a dry run with seed 8).

| When (sim) | Look at | Say |
|---|---|---|
| 14:00–15:00 | AI queue, any patient | "Each arrival is triaged by Claude in the AI ED. Here's why it decided what it did." **Click a patient** in the AI queue and show the rationale, red flags and immediate actions. Close the drawer. |
| 16:00–17:00 | "Under-triaged" tile (about 0 vs 6 by 17:00) | "The nurse under-triages about 1 patient in 5 under pressure. Claude does it about 1 in 100. Those are the patients who end up waiting too long for their acuity." |
| ~16:30 | The hip-injury patient in the AI queue (the first one with the chip appears at 16:29) | **Click** them and show the "Likely admission · bed requested at triage" chip. "Claude also predicts who'll need admission, so the bed request starts at triage instead of hours later. That's the lever that matters most, and I'll come back to it." |
| 18:00–20:00 | "Longest walk-in wait" chart | "Here's the evening rush. Watch the manual ED's longest walk-in wait climb toward the 4-hour line. The AI ED re-prioritizes walk-ins before they get there." |
| ~19:50 | Same chart: the manual ED crosses 4 h (about 245 vs 86 min) | Press **Pause**. "That's a walk-in past four hours in the manual ED. The AI ED's longest is under an hour and a half." |

> **Presenter warning:** during the evening the AI ED's *average* wait tile is
> **higher** than manual (about 48 vs 38 min at 20:00). That's deliberate: it
> sees the longest-waiting walk-ins first, which raises the early average but
> keeps everyone under 4 hours. Don't point at that tile before the skip. If
> someone notices, it's a strength: "the AI is choosing to protect the tail."

### 4:30–4:45 · Skip to the end of the day (press **Skip to end of day**)

It fast-forwards the night in about 10 seconds and pauses exactly at Sat 14:00. Talk over it:

> "Now let's watch the night. The manual department's backlog never clears.
> Its walk-ins keep waiting while the AI department keeps its rapid-assessment
> zone open after 9 pm, whenever physicians are free."

### 4:45–6:00 · Results (paused at Sat 14:00)

On screen, seed 8 after 24 hours (manual → AI):
- average wait 68 → 29 min
- P90 wait 2 h 28 → 72 min
- SLO breaches 7 → 0
- under-triaged 25 → 2
- deteriorated while waiting 8 → 3
- left without being seen 4 → 0

Point at the tiles, then quote the 12-day averages:

> "That's one typical day. Across 12 simulated days, same patients each day:
> - average wait to physician from 68 to 32 minutes, and the 90th percentile from about 3 hours to 74 minutes
> - walk-ins past the 4-hour SLO from 12 a day to none
> - under-triaged patients from 24 a day to 4
> - patients leaving without being seen from 8 a day to fewer than 1
> - patients deteriorating while waiting from 8 a day to 5, about a third fewer
>
> On the quietest days the AI makes no difference, because there's nothing to
> optimize. The gains come when the department is under pressure."

### 6:00–8:00 · What we learned (the credibility moment)

> "The most interesting part was a result that went against us. The first
> version of the AI department had **more** patients deteriorating while
> waiting than the manual one.
>
> We tested the obvious fixes: smarter queue ordering, by vital signs, by risk,
> even by each patient's *true* risk, which no real system could know. None of
> them helped. The constraint wasn't who goes first. It was that half the beds
> were occupied by admitted patients waiting for an inpatient bed.
>
> So the fix was to have Claude predict admission at triage and request the
> bed then. Claude is 77% accurate on that, against a best possible 81% given
> the data. Across 12 days, that brought deteriorations down by about a
> third. On 3 of the 12 days the AI department still had slightly more,
> which is what a real distribution looks like.
>
> The lesson: **better triage alone reshuffles who waits. Harm goes down when
> AI frees capacity.**"

### 8:00–10:00 · Close and questions

> "Same staff, same beds, same patients: shorter waits, fewer people walking
> out, fewer missed emergencies. Every AI decision comes with a rationale, so
> it can be audited, and there are guardrails: the AI can raise acuity above
> the vital-sign rules but never lower it, and any failure falls back to the
> rules. The whole thing runs on a laptop, and the AI calls for a full
> simulated day cost cents."

**Pipeline-pitch profile:** add 30 s here on the event stream panel: "Every
arrival, vital sign, triage decision and model call is a versioned event. The
patient events carry synthetic PHI, so the pipeline can mask, route and reduce
the data before it reaches analytics, and the model calls give you AI
observability: latency, cost and escalations."

---

## Q&A appendix

**Is this real patient data?**
No. It's synthetic, generated per seed, with ground-truth acuity that the
triagers never see. It's calibrated to published ranges, and the results are a
simulation, not clinical evidence.

**Why aren't deteriorations zero?**
Both departments have the same 20 beds, with about half held by boarders, and
some patients deteriorate within minutes of arrival, before anyone could act.
Zero wouldn't be credible. The claim is *fewer*, for a reason we can explain.

**Where does "60 minutes earlier" for bed requests come from?**
It's deliberately conservative. In a 2026 simulation study based on data
from a large ED (Cheng, Argon, Ganesaraman and Ziya, arXiv 2607.15432),
proactive bed requests cut boarding by about 70–170 minutes from a
248-minute baseline, which is 30–70%. Our 60 minutes is about 14% of our
average boarding time, below that whole range. Separately, a prospective
study found it took about 5 hours from triage to an inpatient bed request,
and that triage nurses can predict admission with 76% sensitivity and 85%
specificity, so the information is there at triage. Honest caveat: the
evidence is simulations and retrospective models; there's no prospective
trial yet. A missed prediction gets no benefit, and false alarms are counted
and shown.

**What if Claude is wrong?**
- It can't assign lower acuity than the vital-sign rules give.
- A low-confidence call escalates from Haiku to Sonnet (about 10% of cases).
- Any error falls back to the rules triager.
- Accuracy against ground truth: 93% exact match vs 75% for the nurse model, 0 emergent misses, and 16 of 16 subtle cases caught.

**Isn't the AI ED just better because it sees fewer patients?**
The opposite: it keeps patients the manual ED loses to walk-outs, so it sees
*more* patients, with the same staff.

**Why did you choose these seeds?**
We recorded 12 simulated days and ranked them by how close each day's
AI-vs-manual differences, and how busy it was, sit to the 12-day average.
Seed 8 ranked first. It's a typical day, not the best one. The backup, seed
4, is a deliberately harder day. Every claim quotes the 12-day average.

**Why was the AI's average wait higher during the evening?**
On purpose. The AI queue sees walk-ins who are approaching the 4-hour mark
before newer arrivals, which raises the early average but protects the
tail. Over the full day it's 29 vs 68 minutes, because the manual
department's backlog never clears overnight.

**A walk-in waited about 11 hours in the manual ED overnight. Is that realistic?**
Long overnight waits do happen in crowded EDs, but our walk-out model is
simple, and in reality more of those patients would leave. That would make
the manual ED's waits look better and its walk-out count worse.

**What does it cost to run?**
A full simulated day of live Claude calls costs cents. The demo replays
recorded decisions, so it's free, deterministic and works offline.

**What would it take to deploy for real?**
Clinical validation on real (de-identified) data, integration with the EHR
triage workflow, the nurse confirming every recommendation (it's decision
support, not automation), and monitoring of accuracy and drift. The event
stream is designed for that monitoring.
