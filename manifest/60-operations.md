# 60 — Operations: CLI, configuration, runbook

## CLI (`er-triage`)

| Command | Options | Does |
|---|---|---|
| `initdb` | `--drop`, `--drop-cache` | create tables; `--drop` recreates all but the LLM cache; `--drop-cache` also drops the cache |
| `serve` | `--host` (127.0.0.1), `--port` (8000), `--reload` | run the web app |
| `simulate` | `--minutes` (240), `--speed`, `--seed`, `--start` (ISO, default `2026-11-06T08:00:00-07:00`), `--volume` (150), `--surge` (1.0), `--preset` (`evening-rush`/`mvc`/`flu-wave`), `--ai` (`claude`/`rules`), `--offline`, `--warmup` HOURS (0), `--live` | headless run; prints a progress line per tick and a scorecard at the end |
| `eval-triage` | `--per-code` (4), `--offline` | offline triage evaluation (`40`) |

`simulate` is **blocking by default** (exact replays); `--live` makes AI
triage non-blocking as in a real deployment. `--offline` never calls the API.

**Scorecard** (whole period after opening, both arms side by side): patients
seen, average and P90 wait to physician, walk-in 4 h SLO breaches, seen after
true CTAS target, under-triaged at intake, deteriorated while waiting, left
without being seen, still waiting at end. Then: LLM calls (replayed,
escalated, fallbacks, late), late AI decisions applied/dropped, and events
emitted/dropped with per-sink sent/failed. The final metrics snapshot is
emitted **before** the bus closes.

## Configuration

Environment variables with prefix `ER_`, or a `.env` file:

| Setting | Default |
|---|---|
| `ER_DATABASE_URL` | `postgresql+psycopg://er_triage@localhost:5432/er_triage` |
| `ER_DEMO_PROFILE` | `value-pitch` (or `pipeline-pitch`: adds the event-stream story) |
| `ER_SIM_SPEED` | 1.0 |
| `ER_AI_TRIAGER` | `claude` (or `rules`) |
| `ER_TRIAGE_MODEL` / `ER_ESCALATION_MODEL` | `claude-haiku-5-5` / `claude-sonnet-5-5` |
| `ER_LLM_OFFLINE` | false |
| `ER_EVENT_SINKS` | `file` (comma-separated: `file`, `console`, `hec`) |
| `ER_EVENT_FILE` | `var/events.jsonl` |
| `ER_EVENT_BATCH_SIZE` / `ER_EVENT_FLUSH_SECONDS` | 100 / 1.0 |
| `ER_HEC_URL`, `ER_HEC_TOKEN`, `ER_HEC_VERIFY_TLS` | unset, unset, true |

**API key:** read from `.key` at the project root (bare key or `NAME=value`);
else `ANTHROPIC_API_KEY`. The file wins, so the demo always bills to the
project key. Never printed or logged.

## Runbook

**Start for a demo**
1. Start the database (target file says how).
2. `er-triage serve --port 8765` under `nohup`, logging to `var/server.log`.
3. `GET /health` → `status: ok`, `database: true`.
4. Open the dashboard: seed 8, opens 14:00, normal day, recorded replay, warm
   start on → Start new run → Pause. Resume when presenting.

**Record a demo day** (costs money once; replays are free):
`er-triage simulate --seed 8 --start 2026-11-06T14:00:00-07:00 --warmup 30
--minutes 1440 --speed 600` with the API key present. Replay the same command
with `--offline`; it must make zero API calls.

**Known operational issues**
- The server may not exit on SIGTERM while a browser holds a server-sent
  events connection. After a restart, check only one process listens on the
  port.
- The HEC sink retries once, then drops the batch (counted). Production
  senders need disk buffering.
- Recorded responses are tied to prompt version, model, effort and the exact
  patient text; changing the opening time or the prompt means re-recording.
