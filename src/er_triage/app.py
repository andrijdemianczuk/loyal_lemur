import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select

from er_triage.config import get_settings
from er_triage.db import ping, session_scope
from er_triage.events import EventBus, build_bus
from er_triage.models import Encounter, Patient, TriageAssessment, VitalSigns
from er_triage.web.manager import RunParams, SimulationManager

STATIC = Path(__file__).parent / "web" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    bus = build_bus(settings)
    bus.start()
    app.state.bus = bus
    app.state.sim = SimulationManager(settings, bus)
    try:
        yield
    finally:
        await app.state.sim.stop()
        await bus.aclose()


app = FastAPI(title="ER Triage Decision Support", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _sim(request: Request) -> SimulationManager:
    return request.app.state.sim


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


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


class StartRequest(BaseModel):
    seed: int = 3
    speed: float = Field(2.0, gt=0, le=60)
    surge: float = Field(1.0, gt=0, le=3)
    volume: float = Field(150, gt=0, le=600)
    ai_mode: str = Field("replay", pattern="^(claude|replay|rules)$")
    start: str = "2026-11-06T14:00:00-07:00"
    warmup_hours: float = Field(30, ge=0, le=72)


class SpeedRequest(BaseModel):
    speed: float = Field(gt=0, le=60)


@app.post("/api/run")
async def start_run(body: StartRequest, request: Request) -> dict[str, str]:
    run_id = await _sim(request).start(RunParams(**body.model_dump()))
    return {"run_id": str(run_id)}


@app.post("/api/stop")
async def stop_run(request: Request) -> dict[str, bool]:
    await _sim(request).stop()
    return {"ok": True}


@app.post("/api/pause")
def pause(request: Request) -> dict[str, bool]:
    _sim(request).pause()
    return {"ok": True}


@app.post("/api/resume")
def resume(request: Request) -> dict[str, bool]:
    _sim(request).resume()
    return {"ok": True}


@app.post("/api/speed")
def speed(body: SpeedRequest, request: Request) -> dict[str, bool]:
    _sim(request).set_speed(body.speed)
    return {"ok": True}


@app.get("/api/state")
async def state(request: Request) -> dict:
    return await asyncio.to_thread(_sim(request).snapshot)


@app.get("/api/stream")
async def stream(request: Request) -> StreamingResponse:
    """Server-sent events: a full state snapshot every second."""
    sim = _sim(request)

    async def events() -> AsyncIterator[str]:
        while not await request.is_disconnected():
            snap = await asyncio.to_thread(sim.snapshot)
            yield f"data: {json.dumps(snap, default=str)}\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@app.get("/api/encounter/{encounter_id}")
def encounter_detail(encounter_id: uuid.UUID) -> dict:
    with session_scope() as s:
        enc = s.get(Encounter, encounter_id)
        if enc is None:
            raise HTTPException(404, "encounter not found (it may not be saved yet)")
        p: Patient = enc.patient
        vitals = s.scalars(select(VitalSigns).where(VitalSigns.encounter_id == enc.id)
                           .order_by(VitalSigns.recorded_at)).all()
        assessments = s.scalars(select(TriageAssessment)
                                .where(TriageAssessment.encounter_id == enc.id)
                                .order_by(TriageAssessment.assessed_at)).all()
        return {
            "encounter": {
                "id": str(enc.id), "arm": enc.arm, "status": enc.status, "lane": enc.lane,
                "assigned_ctas": enc.assigned_ctas, "current_ctas": enc.current_ctas,
                "arrived_at": enc.arrived_at, "triaged_at": enc.triaged_at,
                "physician_seen_at": enc.physician_seen_at, "departed_at": enc.departed_at,
                "deteriorated_at": enc.deteriorated_at,
            },
            "patient": {
                "name": f"{p.first_name} {p.last_name}", "mrn": p.mrn, "sex": p.sex,
                "date_of_birth": p.date_of_birth, "arrival_mode": p.arrival_mode,
                "chief_complaint": p.chief_complaint, "triage_note": p.triage_note,
                "history": p.history, "true_ctas": p.true_ctas,
            },
            "vitals": [
                {"at": v.recorded_at, "hr": v.heart_rate, "sbp": v.systolic_bp,
                 "dbp": v.diastolic_bp, "rr": v.resp_rate, "spo2": v.spo2,
                 "temp": v.temp_c, "pain": v.pain_score, "gcs": v.gcs}
                for v in vitals
            ],
            "assessments": [
                {"at": a.assessed_at, "source": a.source, "ctas": a.ctas_level,
                 "rationale": a.rationale, "red_flags": a.red_flags, "model": a.model,
                 "latency_ms": a.latency_ms, "applied": a.applied}
                for a in assessments
            ],
        }
