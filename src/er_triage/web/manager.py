"""Owns the running simulation for the web app: start/pause/speed controls,
a time series of metrics for charts, and JSON state snapshots."""

import asyncio
import statistics
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from er_triage.cli import build_ai_triager
from er_triage.config import Settings
from er_triage.events import EventBus, EventType
from er_triage.events.sinks import MemorySink
from er_triage.models import Arm, EncounterStatus, Lane
from er_triage.sim.catalog import WALK_IN_SLO_MIN, effective_target_min
from er_triage.sim.ed import WAITING, ActiveEncounter, EDArm, percentile
from er_triage.sim.feed import FeedEngine

SERIES_EVERY = timedelta(minutes=5)
FEED_TYPES = {
    EventType.PATIENT_ARRIVED, EventType.TRIAGE_ASSESSED, EventType.PATIENT_DETERIORATED,
    EventType.SLO_BREACH, EventType.PATIENT_DEPARTED, EventType.LLM_CALL,
    EventType.AI_DECISION,
}

# Rough list prices (USD per million tokens) for the cost readout.
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00)}


@dataclass
class RunParams:
    seed: int = 3
    speed: float = 2.0
    surge: float = 1.0
    volume: float = 150.0
    ai_mode: str = "replay"  # claude | replay | rules
    start: str = "2026-11-06T14:00:00-07:00"  # when the live run opens
    warmup_hours: float = 30.0  # simulated before ``start``; 0 = empty ED


class SimulationManager:
    def __init__(self, settings: Settings, bus: EventBus) -> None:
        self.settings = settings
        self.bus = bus
        # Per-type event counts for the pipeline panel.
        self.feed = MemorySink(keep=0, types={str(t) for t in FEED_TYPES})
        bus.add_sink(self.feed)
        # Kept apart so busy event types can't push decisions out of view.
        self.decisions = MemorySink(keep=100, types={str(EventType.AI_DECISION)},
                                    name="memory-decisions")
        bus.add_sink(self.decisions)
        self.engine: FeedEngine | None = None
        self.params: RunParams | None = None
        self.series: list[dict[str, Any]] = []
        self._next_point: datetime | None = None
        self._sampler: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self.warming_up = False
        self.skip_until: datetime | None = None
        self._skip_restore_speed: float | None = None

    # -- controls -----------------------------------------------------------

    async def start(self, params: RunParams) -> uuid.UUID:
        async with self._lock:
            await self._stop_engine()
            triager = build_ai_triager(
                self.settings,
                "rules" if params.ai_mode == "rules" else "claude",
                offline=params.ai_mode == "replay",
                # Replays are instant cache lookups: wait for each one so the
                # run matches the recording exactly at any speed. Live API
                # calls stay non-blocking (provisional rules, applied late).
                blocking=params.ai_mode == "replay",
            )
            opens_at = datetime.fromisoformat(params.start)
            engine = FeedEngine(
                self.bus,
                sim_start=opens_at - timedelta(hours=params.warmup_hours),
                speed=params.speed,
                seed=params.seed,
                daily_volume=params.volume,
                arrival_multiplier=params.surge,
                ai_triager=triager,
                scenario=f"ui:{params.ai_mode}",
            )
            self.engine = None
            self.skip_until = None
            self.params = params
            self.series = []
            self.feed.recent.clear()
            self.decisions.recent.clear()
            # Snapshots report "warming up" until the engine is handed over.
            self.warming_up = params.warmup_hours > 0
            try:
                if self.warming_up:
                    await asyncio.to_thread(engine.warm_up, params.warmup_hours)
                else:
                    await asyncio.to_thread(engine.create_run)
            finally:
                self.warming_up = False
            self.engine = engine
            run_id = engine.run_id
            self._next_point = engine.clock.start
            engine.start()
            self._sampler = asyncio.create_task(self._sample_loop(), name="series-sampler")
            return run_id

    async def stop(self) -> None:
        async with self._lock:
            await self._stop_engine()

    async def _stop_engine(self) -> None:
        if self._sampler is not None:
            self._sampler.cancel()
            self._sampler = None
        if self.engine is not None:
            await self.engine.stop()

    def pause(self) -> None:
        if self.engine:
            self.engine.clock.pause()

    def resume(self) -> None:
        if self.engine:
            self.engine.clock.resume()

    def skip_to(self, hours_after_opening: float = 24, speed: float = 120) -> datetime | None:
        """Fast-forward (charts keep animating) and pause exactly at
        ``hours_after_opening`` after the run opened."""
        engine = self.engine
        if engine is None:
            return None
        until = engine.clock.start + timedelta(hours=hours_after_opening)
        if engine.processed_until >= until:
            return None
        self.skip_until = until
        self._skip_restore_speed = engine.clock.speed
        engine.stop_at = until
        engine.clock.set_speed(speed)
        engine.clock.resume()
        return until

    def _finish_skip(self, engine: FeedEngine) -> None:
        if self.skip_until is not None and engine.processed_until >= self.skip_until:
            engine.clock.pause_at(self.skip_until)
            engine.clock.set_speed(self._skip_restore_speed or 2.0)
            engine.stop_at = None
            self.skip_until = None

    def set_speed(self, speed: float) -> None:
        if self.engine:
            self.engine.clock.set_speed(speed)
            if self.params:
                self.params.speed = speed

    # -- time series ----------------------------------------------------------

    async def _sample_loop(self) -> None:
        while True:
            await asyncio.to_thread(self._sample)
            await asyncio.sleep(0.5)

    def _sample(self) -> None:
        engine = self.engine
        if engine is None:
            return
        self._finish_skip(engine)
        with engine.lock:
            t = engine.processed_until
            while self._next_point is not None and self._next_point <= t:
                point = {"t": self._next_point.isoformat()}
                for arm, ed in engine.arms.items():
                    m = ed.metrics(self._next_point)
                    point[arm.value] = {
                        "avg_wait": m["avg_wait_min"],
                        "p90_wait": m["p90_wait_min"],
                        "max_walk_in_wait": m["max_walk_in_wait_min"],
                        "waiting": m["waiting"],
                        "slo_breaches": m["slo_breaches"],
                    }
                self.series.append(point)
                self._next_point += SERIES_EVERY

    # -- snapshot -------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        engine = self.engine
        base = {
            "profile": self.settings.demo_profile,
            "params": asdict(self.params) if self.params else asdict(RunParams()),
            "decisions": list(self.decisions.recent)[-40:],
            "telemetry": self._telemetry(),
            "warming_up": self.warming_up,
        }
        if engine is None:
            return {**base, "run": None, "arms": {}, "series": []}
        with engine.lock:
            t = engine.processed_until
            arms = {arm.value: self._arm_state(ed, t) for arm, ed in engine.arms.items()}
        return {
            **base,
            "run": {
                "id": str(engine.run_id),
                "sim_time": t.isoformat(),
                "sim_start": engine.clock.start.isoformat(),
                "elapsed_min": round((t - engine.clock.start).total_seconds() / 60),
                "paused": engine.clock.paused,
                "speed": engine.clock.speed,
                "running": engine._task is not None and not engine._task.done(),
                "warmup": engine.warmup,
                "skipping": self.skip_until is not None,
            },
            "arms": arms,
            "series": self.series,
        }

    def _arm_state(self, ed: EDArm, t: datetime) -> dict[str, Any]:
        m = ed.metrics(t)
        m.pop("by_ctas_detail", None)
        # Since opening (counters reset after warm-up): steadier than the
        # last-hour window and the basis for the headline numbers.
        waits = [r.wait_min for r in ed.counters.waits]
        m["avg_wait_open_min"] = round(statistics.fmean(waits), 1) if waits else 0.0
        m["p90_wait_open_min"] = round(percentile(waits, 90), 1)
        waiting = sorted(
            ed.by_status(*WAITING),
            key=lambda e: (e.status != EncounterStatus.WAITING_PHYSICIAN,
                           ed.policy.key(e, t) if e.assigned_ctas else (9,)),
        )
        cfg = ed.config
        main_used = ed.occupied(Lane.MAIN, t)
        return {
            "metrics": m,
            "capacity": {
                "main": {"used": main_used, "beds": cfg.main_beds,
                         "hallway": max(0, main_used - cfg.main_beds),
                         "hallway_max": cfg.hallway_spaces},
                "fast_track": {"used": ed.occupied(Lane.FAST_TRACK, t),
                               "total": cfg.fast_track_chairs, "open": ed.fast_track_open(t)},
                "intake": {"used": ed.occupied(Lane.INTAKE, t), "total": cfg.intake_chairs,
                           "open": ed.intake_open(t), "mode": cfg.intake_mode},
                "results": {"used": ed.results_area_occupied(t),
                            "total": cfg.results_area_capacity},
                "boarding": sum(1 for e in ed.by_status(EncounterStatus.IN_TREATMENT)
                                if e.admitted and e.lane == Lane.MAIN),
            },
            "waiting": [self._patient_row(e, t) for e in waiting],
            "late": {"applied": ed.counters.ai_late_applied,
                     "dropped": ed.counters.ai_late_dropped},
            "admission": {"true_pos": ed.counters.admit_true_pos,
                          "false_pos": ed.counters.admit_false_pos,
                          "false_neg": ed.counters.admit_false_neg,
                          "boarding_saved_min": round(ed.counters.boarding_saved_min)},
            "decisions": dict(ed.counters.decisions),
        }

    @staticmethod
    def _patient_row(e: ActiveEncounter, t: datetime) -> dict[str, Any]:
        p = e.patient
        wait = e.wait_minutes(t)
        return {
            "encounter_id": str(e.encounter_id),
            "name": f"{p.first_name} {p.last_name}",
            "age": p.age,
            "sex": p.sex,
            "complaint": p.presentation.complaint,
            "arrival_mode": p.arrival_mode,
            "status": e.status,
            "assigned_ctas": e.assigned_ctas,
            "true_ctas": e.current_ctas,
            "lane": e.lane,
            "wait_min": round(wait, 1),
            "over_target": e.assigned_ctas is not None
            and wait > effective_target_min(e.current_ctas),
            "slo_risk": e.walk_in and wait >= WALK_IN_SLO_MIN * 0.75,
            "deteriorated": e.deteriorated,
        }

    def _telemetry(self) -> dict[str, Any]:
        stats = self.bus.stats
        out: dict[str, Any] = {
            "events_emitted": stats.emitted,
            "events_dropped": stats.dropped,
            "sinks": {k: asdict(v) for k, v in stats.sinks.items()},
            "event_counts": dict(self.feed.counts),
            "llm": None,
        }
        triager = self.engine.arms[Arm.AI].triager if self.engine else None
        if triager is not None and hasattr(triager, "stats"):
            cost = sum(PRICES.get(m, (0, 0))[0] * i / 1e6 + PRICES.get(m, (0, 0))[1] * o / 1e6
                       for m, (i, o) in triager.tokens_by_model.items())
            out["llm"] = {**triager.stats, "tokens_by_model": triager.tokens_by_model,
                          "est_cost_usd": round(cost, 4), "offline": triager.offline}
        return out
