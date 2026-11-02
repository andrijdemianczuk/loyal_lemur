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
   - Seed **8** (most representative of the 12 days; seed **5** is the backup)
   - Opens at **14:00**
   - Arrivals **Normal day**
   - AI triage **Claude (recorded replay)**
   - Warm start **on**
4. Click **Start new run**, then **Pause** right away. The clock should read Fri 14:00.
5. Speed **2 sim-min/s**: 1 simulated hour passes every 30 seconds.
6. "Show ground truth" off. Pick the light or dark theme to suit the screen share.
7. Close everything else. The demo runs fully offline, with no API calls and nothing to rate-limit.

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

At 2 sim-min/s this covers 14:00 to about 20:00, which brings in the evening crunch.

| When (sim) | Look at | Say |
|---|---|---|
| 14:00–15:00 | Live feed, a new arrival | "Each arrival is triaged by Claude in the AI ED. Here's why it decided what it did." **Click a patient** in the AI queue and show the rationale, red flags and immediate actions. |
| | Drawer: the "Likely admission" chip | "Claude also predicts who'll need admission, so the bed request starts at triage instead of hours later. That's the lever that matters most, and I'll come back to it." |
| 16:00–18:00 | "Under-triaged" tile | "The nurse under-triages about 1 patient in 5 under pressure. Claude does it about 1 in 100. Those are the patients who end up waiting too long for their acuity." |
| 18:00–20:00 | "Longest walk-in wait" chart | "Here's the evening rush. The manual ED's longest walk-in wait climbs toward the 4-hour line. The AI ED re-prioritizes walk-ins approaching 4 hours and opens the rapid-assessment zone when physicians are free." |
| ~20:00 | Press **Pause** | Move on to the results. |

### 4:30–6:00 · Results (paused)

Point at the KPI tiles, then quote the 12-day averages:

> "Across 12 simulated days, same patients each day:
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
Seed 8 ranked first and seed 5 second. They're typical days, not the best
ones. Every claim quotes the 12-day average.

**What does it cost to run?**
A full simulated day of live Claude calls costs cents. The demo replays
recorded decisions, so it's free, deterministic and works offline.

**What would it take to deploy for real?**
Clinical validation on real (de-identified) data, integration with the EHR
triage workflow, the nurse confirming every recommendation (it's decision
support, not automation), and monitoring of accuracy and drift. The event
stream is designed for that monitoring.
