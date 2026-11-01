from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FakeClock:
    def __init__(self, now: datetime):
        self.set(now)

    def now(self) -> datetime:
        return self._now

    def set(self, now: datetime) -> None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("タイムゾーン付きの時刻が必要です")
        self._now = now.astimezone(UTC)

    def advance(self, delta: timedelta) -> None:
        self._now += delta
