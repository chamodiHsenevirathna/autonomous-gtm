"""Injectable clock (contract C6). All time-dependent code takes a Clock; nothing calls datetime.now() directly."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Protocol

UTC = timezone.utc
DEFAULT_START = datetime(2026, 3, 2, 9, 0, 0, tzinfo=UTC)  # fixed, synthetic "world start"


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class SimClock:
    """Deterministic clock. Time moves only when told to (discrete-event simulation)."""

    def __init__(self, start: datetime = DEFAULT_START):
        if start.tzinfo is None:
            raise ValueError("clock start must be timezone-aware")
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float = 0, **kw) -> datetime:
        self._now = self._now + timedelta(seconds=seconds, **kw)
        return self._now

    def set(self, when: datetime) -> datetime:
        if when < self._now:
            raise ValueError("SimClock cannot move backwards")
        self._now = when
        return self._now
