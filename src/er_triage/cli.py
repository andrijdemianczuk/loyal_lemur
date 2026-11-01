import argparse
import asyncio
from datetime import datetime

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
    try:
        while (engine.clock.now() - engine.clock.start).total_seconds() / 60 < args.minutes:
            await asyncio.sleep(engine.tick_seconds)
            n = len(engine.active) // 2
            print(f"  {engine.clock.now():%a %H:%M}  patients: {n:4d}  "
                  f"events: {bus.stats.emitted}", flush=True)
    finally:
        await engine.stop()
        await bus.aclose()
