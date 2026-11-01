"""Simulated clock that runs faster than wall time and can be paused or
re-speeded live without jumps."""

import time
from datetime import datetime, timedelta


class SimClock:
    def __init__(self, start: datetime, speed: float = 1.0) -> None:
        """``speed`` is simulated minutes per real second."""
        self.start = start
        self._speed = speed
        self._anchor_sim = start
        self._anchor_real = time.monotonic()
        self._paused = False

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def paused(self) -> bool:
        return self._paused

    def now(self) -> datetime:
        if self._paused:
            return self._anchor_sim
        elapsed = time.monotonic() - self._anchor_real
        return self._anchor_sim + timedelta(minutes=elapsed * self._speed)

    def _rebase(self) -> None:
        self._anchor_sim = self.now()
        self._anchor_real = time.monotonic()

    def set_speed(self, speed: float) -> None:
        if speed <= 0:
            raise ValueError("speed must be positive")
        self._rebase()
        self._speed = speed

    def pause(self) -> None:
        self._rebase()
        self._paused = True

    def resume(self) -> None:
        self._anchor_real = time.monotonic()
        self._paused = False
