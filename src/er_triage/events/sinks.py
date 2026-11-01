"""Event sinks. Each receives batches of events and must not raise on
transient downstream failures in a way that stops the simulator; the bus
records failures."""

import asyncio
import json
import sys
from pathlib import Path
from typing import Protocol

import httpx

from er_triage.events.schema import Event


class Sink(Protocol):
    name: str

    async def write(self, batch: list[Event]) -> None: ...

    async def close(self) -> None: ...


class ConsoleSink:
    name = "console"

    async def write(self, batch: list[Event]) -> None:
        for event in batch:
            print(json.dumps(event.to_json_dict()), file=sys.stdout)

    async def close(self) -> None:
        pass


class FileSink:
    """Append-only JSON Lines file; handy as a Cribl file/directory source too."""

    name = "file"

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def write(self, batch: list[Event]) -> None:
        lines = "".join(json.dumps(e.to_json_dict()) + "\n" for e in batch)
        await asyncio.to_thread(self._append, lines)

    def _append(self, lines: str) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(lines)

    async def close(self) -> None:
        pass


class HecSink:
    """HTTP Event Collector sink (Splunk HEC protocol).

    Cribl Stream's "Splunk HEC" source accepts this format, so pointing
    ``hec_url`` at a Cribl worker (default port 8088) is all that's needed.
    """

    name = "hec"

    def __init__(
        self,
        url: str,
        token: str | None,
        verify_tls: bool = True,
        sourcetype: str = "er_triage:event",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not url.rstrip("/").endswith("/services/collector/event"):
            url = url.rstrip("/") + "/services/collector/event"
        headers = {"Authorization": f"Splunk {token}"} if token else {}
        self.sourcetype = sourcetype
        self._client = httpx.AsyncClient(
            headers=headers,
            verify=verify_tls,
            timeout=5.0,
            transport=transport,
        )
        self.url = url

    def _encode(self, batch: list[Event]) -> str:
        # HEC batches are concatenated JSON objects, one per event.
        return "\n".join(
            json.dumps(
                {
                    "time": e.emitted_at.timestamp(),
                    "source": e.source,
                    "sourcetype": self.sourcetype,
                    "event": e.to_json_dict(),
                }
            )
            for e in batch
        )

    async def write(self, batch: list[Event]) -> None:
        body = self._encode(batch)
        for attempt in range(2):
            try:
                resp = await self._client.post(self.url, content=body)
                resp.raise_for_status()
                return
            except httpx.HTTPError:
                if attempt == 1:
                    raise
                await asyncio.sleep(0.5)

    async def close(self) -> None:
        await self._client.aclose()
