# Build instructions for the coding agent

When the user says **"build it"**, build the system this manifest describes,
in the current folder, and stop only when the acceptance checks pass or you
are blocked.

## Inputs

- The specs: `manifest/00-intent.md` to `manifest/80-acceptance.md`, read in
  numeric order. Build the system in the current folder, next to `manifest/`;
  never modify the manifest itself.
- The target: the file named in `manifest/TARGET` if present, otherwise
  `manifest/targets/local.md`. The target decides the language, packages, database and
  layout. The specs decide behaviour. If they conflict, the specs win;
  tell the user.

## Order of work

1. **Read everything first.** Read every spec and the target before writing
   code. Write a short build plan (components, order, open questions) and
   show it to the user.
2. **Check prerequisites** listed in the target (runtime, database, API key).
   If one is missing, say exactly what to install or set, and wait.
3. **Build in this order**, running the relevant tests after each step:
   1. Project skeleton, configuration, database schema (`20`, target)
   2. Event envelope, bus and sinks (`20`)
   3. Presentation catalog and patient generator (`30`, `31`)
   4. ED model: both arms, policies, deterioration, warm-up (`30`)
   5. Rules and nurse triagers (`30`)
   6. LLM triage service with cache, guardrail and fallback (`40`)
   7. Headless CLI (`60`)
   8. Web API and dashboard (`50`)
4. **Run acceptance** (`80-acceptance.md`): the automated tests first, then
   the evaluation and the measured-results checks. Record what you measured.
5. **Report:** what was built, the acceptance results against their
   thresholds, anything you had to decide that the specs didn't, and anything
   that failed.

## Rules

- **Specs are the contract.** Don't add features they don't describe. Where a
  spec is silent, choose the simplest thing that satisfies it and list the
  choice in your report.
- **Exact values are exact.** Parameters, prompt text, schema fields, event
  names and catalog rows are to be copied, not paraphrased.
- **Never show ground truth to a triager** (see `30` and `40`). This is the
  one rule that, if broken, makes every result meaningless.
- **Determinism is a requirement**, not a nicety. Both ED arms must see
  identical patients, and the same seed must produce the same day.
- **Secrets:** read the API key from where the target says. Never print,
  log or commit it.
- **Cost:** live LLM calls cost money. Record responses in the cache and
  replay them. Ask before any step expected to cost more than US$5.
- **Don't fake acceptance.** If a measured result is outside its tolerance,
  report it as a failure with the numbers. Don't tune parameters that the
  specs fix in order to pass.

## Done means

- All automated tests pass.
- Every check in `80-acceptance.md` is reported with its measured value and
  pass/fail.
- The dashboard starts and shows a running two-arm simulation.
