# ER Triage Decision Support

AI-assisted emergency department intake and triage, demonstrated on a live,
synthetic hospital data feed. The same stream of arriving patients is run
through two parallel EDs — **manual triage** and **AI-assisted triage** — so
the effect on wait times is visible side by side, in real time.

- **SLI:** time from arrival to physician, by CTAS level
- **SLO:** walk-in patients seen in under 4 hours
- **Triage scale:** CTAS (Canadian Triage and Acuity Scale, levels 1–5)
- **Data:** 100% synthetic. No real patient information.

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
uv run er-triage serve          # http://127.0.0.1:8000/health
uv run pytest
```

Put your Anthropic API key in `.key` (gitignored). Copy `.env.example` to
`.env` to change settings.

## Event stream

Every clinical and operational event (arrivals, vitals, triage decisions,
deterioration, departures, SLI snapshots, SLO breaches, LLM calls) is emitted
as a versioned JSON envelope through a non-blocking batched bus. Sinks:

| Sink      | Use                                                        |
|-----------|------------------------------------------------------------|
| `file`    | `var/events.jsonl` (default)                               |
| `console` | stdout                                                     |
| `hec`     | HTTP Event Collector — Cribl Stream's Splunk HEC source, or Splunk |

Patient events carry synthetic PHI on purpose, so downstream pipelines can
demonstrate masking and redaction.
