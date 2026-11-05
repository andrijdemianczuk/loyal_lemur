"""In-process event bus with background batching.

``emit`` is synchronous, thread-safe, and never blocks or raises, so the
simulator can call it from hot paths and worker threads. A background task
flushes batches to every sink; a slow or failing sink cannot stall the
simulation. If the buffer overflows, the oldest
events are dropped and counted.
"""

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from er_triage.events.schema import Event, EventType
from er_triage.events.sinks import Sink

log = logging.getLogger(__name__)


@dataclass
class SinkStats:
    sent: int = 0
    failed: int = 0
    last_error: str | None = None


@dataclass
class BusStats:
    emitted: int = 0
    dropped: int = 0
    sinks: dict[str, SinkStats] = field(default_factory=dict)


class EventBus:
    def __init__(
        self,
        sinks: list[Sink],
        batch_size: int = 100,
        flush_seconds: float = 1.0,
        max_buffer: int = 50_000,
    ) -> None:
        self.sinks = sinks
        self.batch_size = batch_size
        self.flush_seconds = flush_seconds
        self._buffer: deque[Event] = deque()
        self._max_buffer = max_buffer
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._closing = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self.stats = BusStats(sinks={s.name: SinkStats() for s in sinks})

    def add_sink(self, sink: Sink) -> None:
        self.sinks.append(sink)
        self.stats.sinks[sink.name] = SinkStats()

    def emit(self, event_type: EventType, data: dict[str, Any] | None = None, **envelope: Any) -> Event:
        event = Event(event_type=event_type, data=data or {}, **envelope)
        if len(self._buffer) >= self._max_buffer:
            self._buffer.popleft()
            self.stats.dropped += 1
        self._buffer.append(event)
        self.stats.emitted += 1
        if len(self._buffer) >= self.batch_size and self._loop is not None:
            # emit may be called from worker threads (e.g. DB-bound sim ticks).
            self._loop.call_soon_threadsafe(self._wake.set)
        return event

    def start(self) -> None:
        if self._task is None:
            self._loop = asyncio.get_running_loop()
            self._task = asyncio.create_task(self._run(), name="event-bus")

    async def _run(self) -> None:
        while not self._closing:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.flush_seconds)
            except TimeoutError:
                pass
            self._wake.clear()
            await self.flush()

    async def flush(self) -> None:
        while self._buffer:
            n = min(self.batch_size, len(self._buffer))
            batch = [self._buffer.popleft() for _ in range(n)]
            await asyncio.gather(*(self._write(s, batch) for s in self.sinks))

    async def _write(self, sink: Sink, batch: list[Event]) -> None:
        stats = self.stats.sinks[sink.name]
        try:
            await sink.write(batch)
            stats.sent += len(batch)
        except Exception as exc:  # a broken sink must never stop the sim
            stats.failed += len(batch)
            stats.last_error = f"{type(exc).__name__}: {exc}"
            log.warning("event sink %s failed: %s", sink.name, stats.last_error)

    async def aclose(self) -> None:
        if self._task is not None:
            # Let the flush loop finish its in-flight batch rather than
            # cancelling it mid-write (a cancelled write loses that batch).
            self._closing = True
            self._wake.set()
            await self._task
            self._task = None
        await self.flush()
        for sink in self.sinks:
            await sink.close()
