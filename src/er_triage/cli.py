import argparse
import asyncio
from datetime import datetime, timedelta

from er_triage.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="er-triage")
    sub = parser.add_subparsers(dest="command", required=True)

    initdb = sub.add_parser("initdb", help="create database tables")
    initdb.add_argument("--drop", action="store_true", help="drop existing tables first")

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

    args = parser.parse_args()
    match args.command:
        case "initdb":
            from er_triage.db import init_db

            init_db(drop=args.drop)
            print(f"tables ready in {get_settings().database_url}")
        case "serve":
            import uvicorn

            uvicorn.run("er_triage.app:app", host=args.host, port=args.port, reload=args.reload)
        case "simulate":
            asyncio.run(_simulate(args))


async def _simulate(args: argparse.Namespace) -> None:
    from er_triage.events import build_bus
    from er_triage.models import EncounterStatus
    from er_triage.sim.ed import WAITING
    from er_triage.sim.feed import FeedEngine

    settings = get_settings()
    bus = build_bus(settings)
    bus.start()
    engine = FeedEngine(
        bus,
        sim_start=datetime.fromisoformat(args.start),
        speed=args.speed or settings.sim_speed,
        seed=args.seed,
        daily_volume=args.volume,
        arrival_multiplier=args.surge,
    )
    run_id = engine.create_run()
    print(f"run {run_id}: {args.minutes:g} sim minutes at {engine.clock.speed:g}x "
          f"(~{args.minutes / engine.clock.speed:.0f}s real)")
    engine.start()
    end = engine.clock.start + timedelta(minutes=args.minutes)
    try:
        while engine.clock.now() < end:
            await asyncio.sleep(engine.tick_seconds)
            line = "  ".join(
                f"{arm.value:>8}: wait {len(a.by_status(*WAITING)):3d} "
                f"treat {len(a.by_status(EncounterStatus.IN_TREATMENT)):3d} "
                f"breach {a.counters.slo_breaches:3d}"
                for arm, a in engine.arms.items()
            )
            print(f"  {engine.clock.now():%a %H:%M}  {line}", flush=True)
    finally:
        await engine.stop()
        await bus.aclose()
    _scorecard(engine, end)


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
