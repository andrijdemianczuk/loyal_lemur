# The build manifest

This folder is the whole project, written as specifications instead of code.
A coding agent reads it and builds a working copy of the system: the
simulator, the AI triage service, the dashboard, the event stream and the
tests. The source code in `src/` is one build of this manifest; it is not the
only one.

**The idea:** the spec is the source, and code is a build artefact. You
version, review and diff the specs. You rebuild the code when you need it, for
whatever target you need it on. That makes the system:

- **Repeatable:** the same manifest produces a system that passes the same
  acceptance checks.
- **Portable:** change the target file, not the specs, to build for a
  different platform.
- **Reviewable:** a design change is a diff to a few paragraphs of Markdown,
  not to hundreds of lines of code.

This is an early MVP of the approach. See "What this MVP does not do yet" below.

## Build it

You need [Claude Code](https://claude.com/claude-code) and the prerequisites
in the target file (`targets/local.md` by default).

```bash
./manifest/build-it ../er-triage-build
```

This creates the target folder, copies the manifest into it, and starts
Claude Code there with one instruction: **build it**. The agent follows
[`AGENT.md`](AGENT.md): it reads the specs in order, builds, and runs the
acceptance checks in [`80-acceptance.md`](80-acceptance.md) before it reports
done.

Already have the manifest in an empty folder? Open Claude Code there and type
`build it`.

To build for a different target, pass it as the second argument:

```bash
./manifest/build-it ../er-triage-build targets/local.md
```

## What's in it

| File | Defines |
|---|---|
| [`AGENT.md`](AGENT.md) | How the agent builds: order, rules, when it's done |
| [`00-intent.md`](00-intent.md) | The problem, the users, the SLI/SLO, what "better" means |
| [`10-architecture.md`](10-architecture.md) | Components, data flow, the decisions behind them |
| [`20-data-and-events.md`](20-data-and-events.md) | Database tables and the event contract |
| [`30-simulator.md`](30-simulator.md) | Synthetic patients, the two-arm ED model, the four decisions |
| [`31-catalog.md`](31-catalog.md) | The 30 clinical presentations, as data |
| [`40-ai-triage.md`](40-ai-triage.md) | The LLM triage service: prompt, schema, routing, guardrails, cache |
| [`50-web.md`](50-web.md) | The API and the dashboard |
| [`60-operations.md`](60-operations.md) | CLI, configuration, runbook |
| [`80-acceptance.md`](80-acceptance.md) | The tests and measured results that define "built correctly" |
| [`targets/`](targets/) | Platform choices: language, database, packaging |

## Updating the manifest

When the system changes, change the manifest first, then rebuild or patch the
code to match. A change isn't finished until `80-acceptance.md` still passes.
Numbers in the specs that came from measurement say so, with the date.

## What this MVP does not do yet

- **No exact reproduction.** A rebuild uses its own random-number streams and
  records its own LLM responses, so results match within the tolerances in
  `80-acceptance.md`, not to the decimal.
- **One target.** Only `targets/local.md` exists. Others (containers, a cloud
  service) are a new target file each.
- **Proven once, not yet routinely.** One clean-room rebuild (2026-11-09:
  an empty folder, no access to the original code or database) passed every
  check in `80-acceptance.md`: 43 of 43 tests, every evaluation and 12-day
  result inside its tolerance, and offline replay with no model calls. The
  LLM exact-match check passed narrowly (88.3% against an 88% floor).
  Rebuilding on every manifest change, in CI, is the next step.
- **The LLM costs money once.** A fresh build has no recorded responses; the
  acceptance run records them (a few US dollars at list prices).
