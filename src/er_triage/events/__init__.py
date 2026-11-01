from er_triage.config import Settings
from er_triage.events.bus import EventBus
from er_triage.events.schema import Event, EventType
from er_triage.events.sinks import ConsoleSink, FileSink, HecSink, Sink

__all__ = ["Event", "EventBus", "EventType", "build_bus"]


def build_bus(settings: Settings) -> EventBus:
    sinks: list[Sink] = []
    for name in settings.sink_names:
        match name:
            case "console":
                sinks.append(ConsoleSink())
            case "file":
                sinks.append(FileSink(settings.event_file))
            case "hec":
                if not settings.hec_url:
                    raise ValueError("ER_EVENT_SINKS includes 'hec' but ER_HEC_URL is not set")
                token = settings.hec_token.get_secret_value() if settings.hec_token else None
                sinks.append(HecSink(settings.hec_url, token, settings.hec_verify_tls))
            case _:
                raise ValueError(f"unknown event sink: {name!r}")
    return EventBus(sinks, settings.event_batch_size, settings.event_flush_seconds)
