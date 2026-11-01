import asyncio
import json

import httpx

from er_triage.events import EventBus, EventType
from er_triage.events.sinks import FileSink, HecSink


def test_file_sink_writes_jsonl(tmp_path):
    path = tmp_path / "events.jsonl"

    async def run():
        bus = EventBus([FileSink(path)], batch_size=10)
        bus.emit(EventType.PATIENT_ARRIVED, {"chief_complaint": "chest pain"}, arm="ai")
        bus.emit(EventType.METRICS_SNAPSHOT, {"avg_wait_min": 42.0})
        await bus.aclose()
        return bus

    bus = asyncio.run(run())
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert [e["event_type"] for e in lines] == ["patient.arrived", "metrics.snapshot"]
    assert lines[0]["data"]["chief_complaint"] == "chest pain"
    assert lines[0]["arm"] == "ai"
    assert bus.stats.sinks["file"].sent == 2


def test_hec_sink_posts_splunk_format():
    received = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(200, json={"text": "Success", "code": 0})

    async def run():
        sink = HecSink(
            "http://cribl.local:8088", "secret-token", transport=httpx.MockTransport(handler)
        )
        bus = EventBus([sink], batch_size=10)
        for i in range(3):
            bus.emit(EventType.VITALS_RECORDED, {"heart_rate": 80 + i})
        await bus.aclose()

    asyncio.run(run())
    assert len(received) == 1
    req = received[0]
    assert str(req.url) == "http://cribl.local:8088/services/collector/event"
    assert req.headers["Authorization"] == "Splunk secret-token"
    events = [json.loads(line) for line in req.content.decode().splitlines()]
    assert len(events) == 3
    assert events[0]["sourcetype"] == "er_triage:event"
    assert events[2]["event"]["data"]["heart_rate"] == 82


def test_failing_sink_does_not_break_other_sinks(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async def run():
        bus = EventBus(
            [HecSink("http://down:8088", None, transport=httpx.MockTransport(handler)),
             FileSink(tmp_path / "e.jsonl")],
        )
        bus.emit(EventType.SLO_BREACH, {"wait_min": 241})
        await bus.aclose()
        return bus

    bus = asyncio.run(run())
    assert bus.stats.sinks["hec"].failed == 1
    assert "503" in bus.stats.sinks["hec"].last_error
    assert bus.stats.sinks["file"].sent == 1


def test_buffer_overflow_drops_oldest():
    async def run():
        bus = EventBus([], max_buffer=3)
        for i in range(5):
            bus.emit(EventType.VITALS_RECORDED, {"i": i})
        return bus

    bus = asyncio.run(run())
    assert bus.stats.dropped == 2
    assert [e.data["i"] for e in bus._buffer] == [2, 3, 4]
