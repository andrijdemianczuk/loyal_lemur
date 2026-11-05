import argparse
import asyncio
from datetime import datetime, timedelta

from er_triage.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="er-triage")
    sub = parser.add_subparsers(dest="command", required=True)

    initdb = sub.add_parser("initdb", help="create database tables")
    initdb.add_argument("--drop", action="store_true",
                        help="drop existing tables first (keeps recorded LLM responses)")
    initdb.add_argument("--drop-cache", action="store_true",
                        help="with --drop, also delete recorded LLM responses")

    serve = sub.add_parser("serve", help="run the web app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    sim = sub.add_parser("simulate", help="run the synthetic EHR feed headless")
    sim.add_argument("--minutes", type=float, default=240, help="simulated minutes to run")
    sim.add_argument("--speed", type=float, help="simulated minutes per real second")
    sim.add_argument("--seed", type=int, default=None)
    sim.add_argument("--start", default="2026-11-06T08:00:00-07:00",
                     help="simulated start time (ISO 8601)")
    sim.add_argument("--volume", type=float, default=150, help="arrivals per day")
    sim.add_argument("--surge", type=float, default=1.0, help="arrival rate multiplier")
    sim.add_argument("--preset", choices=["evening-rush", "mvc", "flu-wave"],
                     help="time-limited surge on the opening day (see sim/surge.py)")
    sim.add_argument("--ai", choices=["claude", "rules"], help="AI arm triager")
    sim.add_argument("--offline", action="store_true",
                     help="replay cached Claude responses only (rules on cache miss)")
    sim.add_argument("--warmup", type=float, default=0, metavar="HOURS",
                     help="simulate HOURS before --start first (steady-state ED); "
                          "with --ai claude this also records the warm-up for replay")
    sim.add_argument("--live", action="store_true",
                     help="don't wait for Claude; triage provisionally and apply late")

    ev = sub.add_parser("eval-triage", help="score triagers against ground truth")
    ev.add_argument("--per-code", type=int, default=4, help="patients per presentation")
    ev.add_argument("--offline", action="store_true", help="replay cached responses only")

    args = parser.parse_args()
    match args.command:
        case "initdb":
            from er_triage.db import init_db

            init_db(drop=args.drop, drop_cache=args.drop_cache)
            print(f"tables ready in {get_settings().database_url}")
        case "serve":
            import uvicorn

            uvicorn.run("er_triage.app:app", host=args.host, port=args.port, reload=args.reload)
        case "simulate":
            asyncio.run(_simulate(args))
        case "eval-triage":
            from er_triage.ai.evaluate import evaluate

            key = get_settings().anthropic_api_key()
            evaluate(key.get_secret_value() if key else None, args.per_code, args.offline)


async def _simulate(args: argparse.Namespace) -> None:
    from er_triage.events import build_bus
    from er_triage.models import Arm, EncounterStatus
    from er_triage.sim.ed import WAITING
    from er_triage.sim.feed import FeedEngine
    from er_triage.sim.surge import PRESETS

    settings = get_settings()
    bus = build_bus(settings)
    bus.start()
    ai_triager = build_ai_triager(settings, args.ai, offline=args.offline,
                                  blocking=not args.live)
    opens_at = datetime.fromisoformat(args.start)
    engine = FeedEngine(
        bus,
        sim_start=opens_at - timedelta(hours=args.warmup),
        speed=args.speed or settings.sim_speed,
        seed=args.seed,
        daily_volume=args.volume,
        arrival_multiplier=args.surge,
        ai_triager=ai_triager,
        surge=PRESETS[args.preset] if args.preset else None,
        opens_at=opens_at,
    )
    if args.warmup:
        w = engine.warm_up(args.warmup, cache_only=args.offline)
        print(f"warm-up: {w['hours']:g} h in {w['seconds']}s, in ED {w['in_ed']}"
              + (f", AI {w['ai']}" if "ai" in w else ""))
        run_id = engine.run_id
    else:
        run_id = engine.create_run()
    print(f"run {run_id}: {args.minutes:g} sim minutes at {engine.clock.speed:g}x "
          f"(~{args.minutes / engine.clock.speed:.0f}s real)")
    end = engine.clock.start + timedelta(minutes=args.minutes)
    engine.stop_at = end
    engine.start()
    try:
        try:
            while engine.processed_until < end:
                await asyncio.sleep(engine.tick_seconds)
                line = "  ".join(
                    f"{arm.value:>8}: wait {len(a.by_status(*WAITING)):3d} "
                    f"treat {len(a.by_status(EncounterStatus.IN_TREATMENT)):3d} "
                    f"breach {a.counters.slo_breaches:3d}"
                    for arm, a in engine.arms.items()
                )
                print(f"  {engine.processed_until:%a %H:%M}  {line}", flush=True)
        finally:
            await engine.stop()
        # The scorecard's final snapshot is itself an event: emit it before
        # the bus closes so every sink receives it.
        _scorecard(engine, end)
    finally:
        await bus.aclose()
    if stats := getattr(ai_triager, "stats", None):
        print(f"\n  Claude: {stats['calls']} calls ({stats['cache_hits']} replayed), "
              f"{stats['escalations']} escalated, {stats['fallbacks']} fallbacks, "
              f"{stats['late']} late")
        c = engine.arms[Arm.AI].counters
        print(f"  Late AI decisions: {c.ai_late_applied} applied, {c.ai_late_dropped} dropped "
              f"(patient already seen)")
    sinks = ", ".join(
        f"{name} {s.sent} sent" + (f", {s.failed} failed ({s.last_error})" if s.failed else "")
        for name, s in bus.stats.sinks.items()
    )
    print(f"  Events: {bus.stats.emitted} emitted, {bus.stats.dropped} dropped; {sinks}")


def build_ai_triager(settings, choice: str | None = None, *, offline: bool = False,
                     blocking: bool = False):
    from er_triage.sim.triage import RulesTriager

    if (choice or settings.ai_triager) == "rules":
        return RulesTriager()
    from er_triage.ai.claude_triage import ClaudeTriager

    key = settings.anthropic_api_key()
    return ClaudeTriager(
        key.get_secret_value() if key else None,
        primary_model=settings.triage_model,
        escalation_model=settings.escalation_model,
        offline=offline or settings.llm_offline,
        blocking=blocking,
    )


def _scorecard(engine, t: datetime) -> None:
    from er_triage.db import session_scope

    rows = {}
    with session_scope() as s:
        for arm, ed in engine.arms.items():
            rows[arm.value] = ed.snapshot(s, engine.run_id, t, window_min=float("inf"))
    labels = [
        ("seen", "Patients seen"),
        ("avg_wait_min", "Avg wait to physician (min)"),
        ("p90_wait_min", "P90 wait to physician (min)"),
        ("slo_breaches", "Walk-in 4h SLO breaches"),
        ("ctas_target_misses", "Seen after true CTAS target"),
        ("under_triaged", "Under-triaged at intake"),
        ("deteriorations", "Deteriorated while waiting"),
        ("lwbs", "Left without being seen"),
        ("waiting", "Still waiting at end"),
    ]
    print(f"\n  {'':32}{'baseline':>10}{'ai':>10}")
    for key, label in labels:
        print(f"  {label:32}{rows['baseline'][key]:>10}{rows['ai'][key]:>10}")
