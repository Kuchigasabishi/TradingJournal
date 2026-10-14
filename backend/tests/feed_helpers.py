"""Shared by the Phase 3 tests: where the fixtures are, the fixed instant the suite lives at, and an in-memory source."""
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from app.connectors import forexfactory, gcal
from app.connectors.base import FetchResult
from app.connectors.registry import Source

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
# The verification server's clock starts here (see fixtures/README.md): a Wednesday in the middle of the fixture week.
NOW = datetime(2044, 5, 11, 12, 0, tzinfo=timezone.utc)


def fixture(*parts: str) -> bytes:
    return FIXTURES.joinpath(*parts).read_bytes()


def news_source(fetch: Callable[[str | None, str | None], FetchResult], poll_minutes: int = 60) -> Source:
    return Source(
        name="forexfactory", label="Economic news (ForexFactory)", enabled=True, disabled_reason=None,
        poll_minutes=poll_minutes, host="feeds.example.test", reconcile="upsert_window",
        fetch=fetch, parse=lambda body, now: forexfactory.parse(body),
    )


def calendar_source(fetch: Callable[[str | None, str | None], FetchResult], tz, poll_minutes: int = 30) -> Source:
    return Source(
        name="gcal", label="Google Calendar", enabled=True, disabled_reason=None,
        poll_minutes=poll_minutes, host="calendar.example.test", reconcile="mirror",
        fetch=fetch, parse=lambda body, now: gcal.parse(body, now=now, default_tz=tz),
    )
