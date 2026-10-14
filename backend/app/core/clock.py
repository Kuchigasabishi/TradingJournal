"""Clocks. `utcnow` stamps journal rows. The feed subsystem takes a `Clock`, so its schedule, its windows and its
cooldowns can be tested without waiting (docs/BLUEPRINT.md, P8)."""
import time
from datetime import datetime, timedelta, timezone
from typing import Protocol


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return utcnow()


class ShiftedClock:
    """Starts at a chosen instant and then runs at the speed of real time.

    Verification uses it so that "this week" in a feed fixture is a fixed week years from now, while time still
    passes: a cooldown of two seconds still takes two seconds.
    """

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("a clock needs an aware start instant")
        self._start = start.astimezone(timezone.utc)
        self._origin = time.monotonic()

    def now(self) -> datetime:
        return self._start + timedelta(seconds=time.monotonic() - self._origin)


def make_clock(override: datetime | None) -> Clock:
    return ShiftedClock(override) if override is not None else SystemClock()
