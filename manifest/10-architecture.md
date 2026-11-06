# 10 — Architecture

## Components

```
 Patient generator ──► Feed engine (1-min steps) ──► ED arm: manual ──┐
 (synthetic EHR)            │                         ED arm: AI ──────┤
                            │                            │             │
                            │                    LLM triage service    │
                            │                    (cache ◄─► Anthropic) │
                            ▼                                          ▼
                      PostgreSQL ◄─────────────────────────── Event bus ──► sinks
                            │                                 (file, console, HEC)
                            ▼
                 Simulation manager ──► FastAPI (REST + SSE) ──► Dashboard
```

| Component | Responsibility | Spec |
|---|---|---|
| Patient generator | Synthetic arrivals, demographics, notes, vitals, care-path outcomes | `30`, `31` |
| Feed engine | Advances simulated time in fixed 1-minute steps; admits arrivals to both arms; vitals, deterioration, snapshots | `30` |
| ED arm | One ED: triage desk, queues, lanes, physicians, beds, departures, KPIs | `30` |
| Triagers | Nurse (baseline), rules (fallback and guardrail), LLM (AI arm) | `30`, `40` |
| Queue policies | CTAS-then-FIFO (baseline); SLO-aware (AI) | `30` |
| LLM triage service | Prompt, structured output, model routing, guardrail, fallback, cache | `40` |
| Event bus | Typed events, batched, to any number of sinks; failures counted | `20` |
| Simulation manager | One live run for the web app: start, pause, speed, skip, state snapshot | `50` |
| Web API + dashboard | REST controls, server-sent state stream, single-page UI | `50` |
| CLI | `initdb`, `serve`, `simulate`, `eval-triage` | `60` |

## Decisions and why

1. **LLM for judgement, deterministic code for everything else.** The LLM
   reads the complaint, note, history and medications together; that is
   where rules miss atypical presentations. Queue order, capacity policies
   and the vital-sign floor are deterministic: auditable, instant, testable.
2. **Two models, routed by confidence.** A fast, cheap primary model triages
   everyone; only cases it isn't highly confident about go to a stronger
   model (about 8% of cases when measured).
3. **Guardrail and fallback.** The LLM may raise acuity above the vital-sign
   rules, never lower it. Any error, refusal or timeout falls back to the
   rules. The ED never stalls on the API.
4. **Non-blocking in live mode.** If the LLM answer isn't back when triage
   finishes, the patient proceeds on the rules decision and the LLM decision
   is applied when it lands (or logged as too late).
5. **Record and replay.** Every LLM response is cached under a key built from
   everything that affects it. Replays are exact, offline and free; this is
   what makes demos deterministic and ablations cheap.
6. **Determinism by construction.** Per-patient random streams and a fixed
   time grid: both arms see identical patients, and a day depends only on its
   seed, never on wall-clock timing.
7. **Events as the integration surface.** A stable envelope; downstream
   platforms decide what to keep, mask or route. Patient events deliberately
   carry synthetic identifiers so pipelines can demonstrate masking.
8. **Same resources in both arms.** Only decisions differ, so any difference
   in outcome is attributable to the decisions.

## Next steps (not in this MVP)

- **Classic ML for admission prediction:** a calibrated tabular model (for
  example gradient boosting) with the LLM's reading of the note as one
  feature. Admission prediction is high-volume and needs probabilities, which
  suits classic ML better than an LLM.
- **Drift detection:** decision mix and outcomes by prompt and model version.
- **Evaluation against a clinical gold set** instead of simulator labels.
- **Further decoupling:** model behind a gateway; policies as configuration.
