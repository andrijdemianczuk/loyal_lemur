"""Application settings.

Everything is overridable via environment variables prefixed ``ER_`` (or a
local ``.env`` file). The Anthropic API key is read from the gitignored
``.key`` file unless ``ANTHROPIC_API_KEY`` is already set.
"""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class DemoProfile(StrEnum):
    """Audience the demo is being pitched to; drives narrative panels in the UI."""

    VALUE_PITCH = "value-pitch"  # platform-agnostic "why": better care, lower waits
    PIPELINE_PITCH = "pipeline-pitch"  # value story + the telemetry pipeline behind it


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ER_", env_file=PROJECT_ROOT / ".env", extra="ignore"
    )

    database_url: str = "postgresql+psycopg://er_triage@localhost:5432/er_triage"
    demo_profile: DemoProfile = DemoProfile.VALUE_PITCH

    # Simulation clock: simulated minutes per real second.
    sim_speed: float = Field(default=1.0, gt=0, le=60)

    # Anthropic
    anthropic_key_file: Path = PROJECT_ROOT / ".key"
    anthropic_model: str = "claude-sonnet-5-5"

    # Event output: comma-separated list of sinks ("console", "file", "hec").
    event_sinks: str = "file"
    event_file: Path = PROJECT_ROOT / "var" / "events.jsonl"
    event_batch_size: int = 100
    event_flush_seconds: float = 1.0

    # HTTP Event Collector endpoint (Cribl Stream's HEC source, or Splunk).
    hec_url: str | None = None
    hec_token: SecretStr | None = None
    hec_verify_tls: bool = True

    @property
    def sink_names(self) -> list[str]:
        return [s.strip().lower() for s in self.event_sinks.split(",") if s.strip()]

    def anthropic_api_key(self) -> SecretStr | None:
        """API key from the project key file, else ``ANTHROPIC_API_KEY``.

        The file wins so the demo always bills to the project key, even if the
        shell has a different key exported. Accepts a bare key or a
        ``NAME=value`` line.
        """
        import os

        if self.anthropic_key_file.is_file():
            raw = self.anthropic_key_file.read_text().strip()
            if "=" in raw:
                raw = raw.split("=", 1)[1].strip().strip("'\"")
            if raw:
                return SecretStr(raw)
        if key := os.environ.get("ANTHROPIC_API_KEY"):
            return SecretStr(key.strip())
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()
