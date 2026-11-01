from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI

from er_triage.config import get_settings
from er_triage.db import ping
from er_triage.events import EventBus, build_bus


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    bus = build_bus(get_settings())
    bus.start()
    app.state.bus = bus
    try:
        yield
    finally:
        await bus.aclose()


app = FastAPI(title="ER Triage Decision Support", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, object]:
    settings = get_settings()
    bus: EventBus = app.state.bus
    try:
        db_ok = ping()
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
        "anthropic_key_configured": settings.anthropic_api_key() is not None,
        "demo_profile": settings.demo_profile,
        "events": asdict(bus.stats),
    }
