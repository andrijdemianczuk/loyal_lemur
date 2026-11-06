# Target: local workstation (default)

The reference target: everything runs on one machine, no containers.

## Platform

| Concern | Choice |
|---|---|
| Language | Python 3.14, managed with `uv` |
| Package | `er-triage`, source in `src/er_triage/`, console script `er-triage` |
| Database | PostgreSQL 17, local, database and role `er_triage`; SQLAlchemy 2 ORM, `psycopg` 3 driver |
| Web | FastAPI + uvicorn; static files served by FastAPI |
| UI | No build step: one `index.html`, `app.js`, `app.css`; Alpine.js and ECharts from CDNs |
| LLM | Anthropic Python SDK; structured output parsed into a Pydantic model |
| Synthetic data | Faker, locale `en_CA` |
| Settings | `pydantic-settings`, env prefix `ER_`, optional `.env` file |
| Tests | `pytest`; DB tests use the same local Postgres |

## Prerequisites (check before building)

- `uv`, Python 3.14
- PostgreSQL 17 running locally (macOS: `brew install postgresql@17 && brew services start postgresql@17`), then `createuser er_triage && createdb -O er_triage er_triage`
- An Anthropic API key in a file named `.key` at the project root, or `ANTHROPIC_API_KEY` in the environment. `.key` is gitignored and never printed.

## Layout

```
pyproject.toml
src/er_triage/
  config.py  db.py  models.py  cli.py  app.py
  events/  (schema, bus, sinks)
  sim/     (catalog, generator, clock, triage, ed, feed, surge)
  ai/      (claude_triage, evaluate)
  web/     (manager.py, static/)
tests/
var/       (gitignored: event files, analysis output)
```

## Conventions

- Default ports: dashboard on 8000 (`serve --port` to change).
- `.gitignore`: `.venv/`, `.key`, `.env`, `var/`, `__pycache__/`, `.pytest_cache/`.
- Start the server with `nohup` for long demos so it isn't tied to a terminal.
