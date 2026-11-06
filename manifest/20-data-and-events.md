# 20 — Data model and event contract

## Enumerations

| Enum | Values |
|---|---|
| Arm | `baseline`, `ai` |
| ArrivalMode | `walk_in`, `ambulance` |
| EncounterStatus | `waiting_triage`, `waiting_physician`, `in_treatment`, `discharged`, `admitted`, `lwbs` |
| AssessmentSource | `nurse`, `rules`, `ai` |
| Lane | `main`, `fast`, `intake` |

## Tables

CTAS columns are small integers constrained to 1–5. Timestamps are
timezone-aware. Primary keys are UUIDs unless noted.

**`sim_runs`**: `id`, `scenario` (default `baseline_day`), `seed`,
`sim_start_at`, `speed`, `status` (default `running`), `config` (JSON),
`created_at`.

**`patients`** (one per arrival, shared by both arms): `id`, `run_id` →
sim_runs (cascade delete), `mrn`, `health_card_no`, `first_name`,
`last_name`, `date_of_birth`, `sex`, `postal_code` *(the six fields marked PHI
are synthetic)*, `arrival_mode`, `arrived_at`, `chief_complaint`,
`triage_note`, `history`, `presentation_code`, `true_ctas` (ground truth;
never shown to a triager), `fragility`.

**`encounters`** (one per patient per arm): `id`, `run_id`, `patient_id`,
`arm`, `status`, `assigned_ctas`, `priority_score`, `arrived_at`,
`triaged_at`, `physician_seen_at`, `departed_at`, `lane`, `current_ctas`
(true acuity including deterioration), `deteriorated_at`.

**`vital_signs`** (integer PK): `encounter_id`, `recorded_at`, `heart_rate`,
`systolic_bp`, `diastolic_bp`, `resp_rate`, `spo2`, `temp_c`, `pain_score`
(0–10), `gcs` (3–15).

**`triage_assessments`**: `id`, `encounter_id`, `source`, `assessed_at`,
`ctas_level`, `priority_score`, `rationale`, `red_flags` (JSON list),
`applied` (false when an LLM decision arrived too late to change care),
`admit_predicted`, `model`, `latency_ms`, `input_tokens`, `output_tokens`.

**`metric_snapshots`** (integer PK): `run_id`, `arm`, `sim_time`, plus every
field of the metrics object (see `30-simulator.md`, Metrics).

**`llm_responses`** (the replay cache): `cache_key` (unique, SHA-256 hex),
`model`, `prompt_version`, `request` (JSON), `response` (JSON), `latency_ms`,
`input_tokens`, `output_tokens`, `cache_read_tokens`, `created_at`.

### Database commands

- `initdb` creates all tables.
- `initdb --drop` drops and recreates everything **except** `llm_responses`.
- `initdb --drop --drop-cache` also drops the cache. Recorded responses cost
  money to recreate; never drop them by default.

## Event envelope

Every event, version `1.0`, source `er-triage-sim`:

| Field | Type | Notes |
|---|---|---|
| `event_id` | UUID | unique per event; used for end-to-end reconciliation |
| `event_type` | string | see below |
| `emitted_at` | timestamp (UTC) | wall clock |
| `sim_time` | timestamp | simulated time of the event |
| `run_id` | UUID | |
| `arm` | string or null | null for events shared by both arms |
| `source` | `er-triage-sim` | |
| `schema_version` | `1.0` | |
| `data` | object | per type |

## Event types

| Type | When | Key `data` fields |
|---|---|---|
| `run.started` / `run.stopped` | run lifecycle | scenario, seed, speed, config, warm-up summary |
| `patient.arrived` | arrival (once, both arms) | patient_id, encounter_ids per arm, **mrn, health_card_no, first_name, last_name, date_of_birth, postal_code** (synthetic PHI, on purpose), age, sex, arrival_mode, chief_complaint, triage_note, history, vitals |
| `vitals.recorded` | each vitals check | encounter_id, vitals |
| `triage.assessed` | each triage or reassessment | encounter_id, patient_id, source, ctas, previous_ctas, reassessment, applied, lane, rationale, red_flags, likely_admission, model |
| `patient.deteriorated` | deterioration | encounter_id, patient_id, previous_ctas, current_ctas, assigned_ctas, wait_min, vitals |
| `physician.assigned` | seen by a physician | encounter_id, patient_id, lane, wait_min, assigned_ctas, true_ctas, target_min, target_met, arrival_mode |
| `patient.departed` | discharge, admission or LWBS | encounter_id, patient_id, disposition, length_of_stay_min, true_ctas, assigned_ctas |
| `slo.breach` | walk-in reaches 4 h waiting | encounter_id, patient_id, slo_min, assigned_ctas, true_ctas |
| `metrics.snapshot` | every 15 sim-minutes per arm | the metrics object |
| `llm.call` | each LLM call (or replay) | mrn, model, effort, prompt_version, replayed, latency_ms, input_tokens, output_tokens, cache_read_tokens, ctas_level, confidence |
| `ai.decision` | an AI decision changed care vs standard practice (AI arm only) | decision (`triage`/`queue`/`intake`/`bed`), encounter_id, patient_id, age, sex, complaint, arrival_mode, reason, plus per-decision fields (below) |
| `queue.reprioritized` | reserved | — |

`ai.decision` extra fields: triage → `ctas`, `rules_ctas`; queue → `ctas`,
`wait_min`, `target_min`, `moved_ahead_of`; intake → `physicians_free`,
`walk_ins_waiting`; bed → `ctas`.

## Event bus and sinks

- Producers never block: events go into a bounded buffer (50,000 events);
  on overflow the oldest are dropped and counted.
- Batches flush every `event_batch_size` events (default 100) or
  `event_flush_seconds` (default 1.0).
- Sinks are selected by `ER_EVENT_SINKS` (comma-separated):
  - `file`: append JSON Lines to `var/events.jsonl`
  - `console`: JSON per line to stdout
  - `hec`: HTTP Event Collector (Splunk format) to `ER_HEC_URL` with
    `Authorization: Splunk <token>`, sourcetype `er_triage:event`. Retries
    once, then counts the batch as failed.
  - Memory sinks (used by the web app) keep counts and recent events.
- A failing sink never stops other sinks or the simulator. The bus keeps
  stats: emitted, dropped, and per sink sent / failed / last error.
- On shutdown the bus drains before closing, so the final events are sent.
- Events are muted during warm-up.
