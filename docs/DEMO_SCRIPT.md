# Demo delivery script

A tight walkthrough of the ED triage decision-support demo: a **3-minute live
segment** inside a **10-minute slot**, with a Q&A appendix.

**The question this demo answers:** *which decisions, backed by AI, need to be
made to improve wait times?* Every section is organized around four decisions.
The metrics are the evidence for each one.

> Claims use **12-day averages** (12 simulated days, recorded with Claude;
> see BUILD_LOG.md, days 2 and 3). The live seed is only for what's on screen.
> "Switched off" figures come from the decision ablation (day 3): the same 12
> days replayed with one decision at a time reverted to standard practice.

## The four decisions (presenter's map)

| # | Decision | Manual ED today | AI-assisted ED | Evidence (12-day average) | Where on screen |
|---|---|---|---|---|---|
| 1 | **Who is most urgent?** | Nurse triage under pressure | Claude triages, with a rationale; it can raise acuity above the vital-sign rules, never lower it | Under-triaged 24 → 4 a day. Switched off: back to 24, and on the three hardest days average wait rises 18–56 min (no change on a typical day). Exact CTAS match 93% vs 75% for the nurse model; 16/16 subtle cases caught | AI decisions: "triage raised above rules"; "Under-triaged" tile; patient drawer |
| 2 | **Who is seen next?** | By acuity, then first-come | Patients seen by how far through their CTAS target they are; walk-ins approaching 4 hours go first | Walk-ins past 4 h: 12 → 0 a day. Switched off: average wait 2 min *lower*, but 2 walk-ins a day pass 4 h. A deliberate tradeoff: it protects the tail | AI decisions: "seen out of CTAS order"; "Longest walk-in wait" chart; ⚠ SLO flags |
| 3 | **When do we open more capacity?** | Rapid-assessment zone on fixed hours (11:00–21:00) | Opened whenever physicians are free and walk-ins are waiting | **Biggest single lever.** Switched off: average wait +17 min (32 → 49), P90 +56 min, 3.7 walk-ins a day past 4 h, +2.7 deteriorations a day. Worse on 11 of 12 days | AI decisions: "zone used after hours"; capacity line ("intake closed" vs open) |
| 4 | **Who will need a bed?** | Bed requested only after the physician decides to admit (in one published study, about 5 hours after triage) | Claude predicts admission at triage, so the bed request starts then | Frees about 22 h of bed time a day. Switched off: average wait +6 min, +1.2 deteriorations a day. Prediction 77% accurate (best possible 81%) | AI decisions: "beds requested at triage"; "Likely admission" chip |

**The thesis:** each decision earns its place differently. The zone shortens
waits and reduces harm, triage prevents misses, the queue protects the tail,
and bed requests add to all of it. Together they're worth more than the sum of
their parts: switch all four off and the AI department falls back to the
manual one.

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

### 0:00–1:00 · The problem is four decisions (paused, dashboard visible)

> "Wait times in an emergency department aren't set by how hard people work.
> They're set by four decisions, made over and over, all day, under pressure,
> with incomplete information:
> **who is most urgent, who is seen next, when to open more capacity, and who
> is going to need a bed.**
>
> I built a simulation to test what happens when AI backs those decisions.
> It's two emergency departments side by side: **same patients, same staff,
> same beds.** On the right, those decisions are made the way most departments
> make them today. On the left, Claude makes the triage call and the
> department makes the other three decisions from what's happening right now."

Point at: the two queue panels and the legend (blue = AI, orange = manual).

### 1:00–1:30 · How realistic it is

> "The patients are synthetic but clinically shaped: about 30 presentation
> types, real vital-sign patterns, medications that match the history, and
> some deliberately subtle cases that are easy to under-triage. Both
> departments have been running for 30 hours before we open, so we start in a
> realistic steady state, with patients boarding while they wait for an
> inpatient bed. The flow model is calibrated so the improvements land in the
> ranges reported in the literature, not tuned to look dramatic."

Point at: the warm-start note ("24 patients already in each ED").

### 1:30–4:30 · Live: watch the decisions happen (press Resume)

At 2 sim-min/s, 3 real minutes covers 14:00 to 20:00 (checked in a dry run with seed 8).

The **AI decisions** panel (bottom right) logs each time the AI ED acts
differently from standard practice, with the reason. Its four counters are the
four decisions. Click any line to open that patient. Counts on seed 8 at 20:00:
9 triage raised, 9 seen out of order, 0 zone after hours, 19 beds requested.

| When (sim) | Decision | Look at | Say |
|---|---|---|---|
| ~15:11 | **1 · Who is most urgent?** | AI decisions: "Triage · Raised to CTAS 2 (rules: 4): 76F epigastric pain". **Click it** | "The vital-sign rules say CTAS 4: she can wait an hour. Claude reads the whole picture: 76, diabetic, epigastric pain and fatigue. That's a possible heart attack, so CTAS 2. Here's its rationale and what the nurse should do now. It can raise acuity above the rules but never lower it." Close the drawer. |
| 16:00–17:00 | **1** | "Under-triaged" tile (about 0 vs 6 by 17:00) | "Under pressure, a nurse under-triages about 1 patient in 5. Claude does it about 1 in 100. Those are the patients who end up waiting too long for how sick they are." |
| ~16:03 | **4 · Who will need a bed?** | AI decisions: "Bed · Bed requested at triage: 76M hip injury - fall" (suspected hip fracture). **Click it** | Show the "Likely admission · bed requested at triage" chip. "Claude also predicts who'll be admitted, so the bed request starts now instead of hours from now. On its own that's worth about 6 minutes of average wait and one fewer patient deteriorating a day." |
| 18:00–19:50 | **2 · Who is seen next?** | AI decisions, "Queue" lines, e.g. 18:57 "Seen ahead of 6: 35M sore throat · waited 3 h 04, approaching the 4 h walk-in limit"; ⚠ SLO flags in the manual queue | "Evening rush. In the manual ED it's acuity, then first-come, so a walk-in with a minor problem can wait indefinitely. The AI ED sees walk-ins approaching four hours first, before they get there. Every one of those is logged with its reason." |
| ~19:50 | **2** | "Longest walk-in wait" chart: the manual line crosses 4 h (about 245 vs 86 min) | Press **Pause**. "There: a walk-in past four hours in the manual ED. The AI ED's longest wait is under an hour and a half." |

> **Presenter warning:** during the evening the AI ED's *average* wait tile is
> **higher** than manual (about 48 vs 38 min at 20:00). That's decision 2 at
> work: seeing the longest-waiting walk-ins first raises the early average
> but keeps everyone under 4 hours. Don't point at that tile before the skip.
> If someone notices, use it: "the AI is choosing to protect the tail, and
> you'll see it pay off overnight."

### 4:30–4:45 · Skip the night (press **Skip to end of day**)

It fast-forwards in about 10 seconds and pauses exactly at Sat 14:00. Talk over it:

> "**Decision 3: when do we open more capacity?** At 9 pm the manual
> department closes its rapid-assessment zone, because that's the schedule.
> The AI department keeps it open whenever physicians are free and patients
> are waiting. Watch the manual backlog build overnight, and never clear."

Point at: the "zone used after hours" counter, which goes from 0 to 7
by midnight while the manual zone is closed.

### 4:45–6:15 · The four decisions, scored (paused at Sat 14:00)

On screen, seed 8 after 24 hours (manual → AI):
- average wait 68 → 29 min
- P90 wait 2 h 28 → 72 min
- SLO breaches 7 → 0
- under-triaged 25 → 2
- deteriorated while waiting 8 → 3
- left without being seen 4 → 0

Point at the tiles while you score each decision with the 12-day averages:

> "That's one typical day. Across 12 simulated days:
> - **Who is most urgent:** under-triaged patients fall from 24 a day to 4.
> - **Who is seen next:** walk-ins past four hours fall from 12 a day to none,
>   and people leaving without being seen from 8 a day to fewer than 1.
> - **When to open capacity:** keeping the rapid-assessment zone open whenever
>   physicians are free is the biggest single lever. On fixed hours, the
>   average wait rises by 17 minutes and nearly 3 more patients a day
>   deteriorate while waiting.
> - **Who will need a bed:** requesting beds at triage frees about 22 hours of
>   bed time a day. Overall, deteriorations while waiting trend down by about
>   a third, though over 12 days that isn't statistically significant yet.
>
> Together, average wait to physician drops from 68 to 32 minutes, and the
> 90th percentile from about 3 hours to 74 minutes. On the quietest days it
> makes no difference, because there's nothing to decide. The gains come under
> pressure."

### 6:15–8:00 · What each decision is worth (the credibility moment)

Show the slide, `docs/slides/decision-worth.html` (open in a browser, full
screen; add `?dark` for the dark version). Its numbers (12-day averages; each
row switches one decision back to standard practice, change against all four on):

| | Avg wait | P90 wait | Walk-ins past 4 h | Deteriorated | Under-triaged |
|---|---|---|---|---|---|
| Manual ED | 68 min | 177 min | 12.1 | 7.9 | 24.2 |
| **AI ED, all four decisions** | **32 min** | **74 min** | **0** | **5.0** | **4.4** |
| without AI triage | +7 | +16 | +0.2 | +1.1 | **+19** |
| without the SLO-aware queue | −2 | +2 | **+2.0** | 0 | 0 |
| without the dynamic zone | **+17** | **+56** | **+3.7** | **+2.7** | 0 |
| without early bed requests | +6 | +13 | +0.2 | +1.2 | 0 |
| all four off | +41 | +96 | +14 | +5.8 | +19 |

> "We switched off each decision in turn and replayed the same 12 days. Each
> one earns its place, and each in a different way.
>
> - **The capacity decision is the biggest lever.** Opening the
>   rapid-assessment zone whenever physicians are free is worth 17 minutes of
>   average wait and almost 3 fewer deteriorations a day. It's worse without
>   it on 11 of the 12 days.
> - **Triage is a safety decision, not a speed decision.** On a typical day,
>   switching Claude off doesn't change the average wait. What changes is
>   that 19 more patients a day are under-triaged, and on the hardest days
>   waits climb by up to an hour.
> - **The queue decision is a deliberate tradeoff.** It costs 2 minutes of
>   average wait and buys zero walk-ins past four hours.
> - **Bed requests** add 6 minutes and one fewer deterioration a day.
>
> And they back each other up: individually they add up to about 27 minutes;
> switch all four off and you lose 41, which puts you back at the manual
> department.
>
> We also tested ideas that didn't work: ordering the queue by vital signs,
> by risk, even by each patient's *true* risk, which no real system could
> know. None of them reduced deteriorations. The order patients are seen in
> can't fix the real constraint, which is beds and capacity.
>
> So, *which decisions need AI?* Two need a model reading the patient:
> triage and admission prediction. That's where Claude reads the history the
> rules miss. Two need the live state of the department: the queue and the
> zone. They run on that triage output, and that's where most of the minutes
> come from."

### 8:00–10:00 · Close and questions

> "Four decisions, made all day long: who's most urgent, who's next, when to
> open capacity, who'll need a bed. Back them with AI, with the same staff,
> beds and patients, and you get shorter waits, fewer people walking out and
> fewer missed emergencies. Every decision comes with a rationale, so it can
> be audited. The AI can raise acuity above the vital-sign rules but never
> lower it, any failure falls back to the rules, and it's designed so a
> nurse confirms every call. The whole thing runs on a laptop, and the AI calls for a full
> simulated day cost cents."

**Pipeline-pitch profile:** add 30 s here on the event stream panel: "Every
one of those decisions, and every arrival, vital sign and model call, is a
versioned event. The patient events carry synthetic PHI, so the pipeline can
mask, route and reduce the data before it reaches analytics. The decision
and model-call events give you AI observability: what was decided, why, how
fast and at what cost."

---

## Q&A appendix

**Which of the four decisions matters most?**
We measured it by replaying the same 12 days with each decision switched off
in turn (the slide above):
- **Decision 3 (opening capacity)** is the biggest single lever: +17 min average wait and +2.7 deteriorations a day without it, worse on 11 of 12 days.
- **Decision 1 (triage)** is the safety decision: under-triage goes from 4 to 24 a day without it. Its effect on waits is concentrated on the hardest days.
- **Decision 2 (who's next)** trades 2 minutes of average wait for zero 4-hour breaches.
- **Decision 4 (beds)**: +6 min and +1.2 deteriorations a day without it.

Caveats: these are one-at-a-time removals, and the decisions interact (all
four off costs more than the sum). Without triage, Claude's fast-track
streaming is also off, because it comes with the triage call.

**What happens under a surge?**
We recorded three surge presets on the same 12 days: an evening rush (12 extra
walk-ins, 17:00–21:00), a multi-vehicle collision (8 ambulance patients at
18:30) and a respiratory wave (12 extra patients, 12:00–24:00). The manual
department's average wait rises to about 100 minutes in each; the AI
department's to about 50. The relative gains hold (−47 to −52% average wait,
−40 to −51% deteriorations, not tested for significance), and the AI department is worse than manual on
almost no day. Under the evening rush it starts to miss the 4-hour target too
(about 2 walk-ins a day, against 22). To show it live, choose **Arrivals →
Evening rush** with seed 8; the surge is shaded on the charts.

**Is the AI making these decisions on its own?**
No. It's decision support. The nurse confirms every triage call; the queue,
the rapid-assessment zone and the bed requests are recommendations a charge
nurse or bed manager acts on. In the simulation they're applied automatically
to measure their effect.

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
