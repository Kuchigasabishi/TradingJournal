"""The feeds this installation can read, built from the settings (docs/BLUEPRINT.md, section 4.3).

A `Source` is a name, a schedule and two functions: `fetch` (HTTP, conditional) and `parse` (bytes to events).
Nothing here touches the database. The two feeds differ in how a fetch is reconciled with what is stored, and
that policy is named here and applied by the feed service.
"""
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.connectors import forexfactory, gcal, http
from app.connectors.base import FetchResult, ParseResult
from app.core.config import Settings, url_host

USER_AGENT = "TradingJournal/0.3 (personal, single-user)"
FF_ACCEPT = "application/json, text/xml;q=0.9, */*;q=0.1"
ICAL_ACCEPT = "text/calendar, */*;q=0.1"

# upsert_window: add and update what the feed holds, remove only future events inside the fetched window that it no
#   longer lists, and never delete the past (ForexFactory publishes a week at a time, so history must accumulate).
# mirror: the stored events become exactly what the calendar holds now (Google Calendar is the source of truth).
Reconcile = Literal["upsert_window", "mirror"]


@dataclass(frozen=True)
class Source:
    name: str
    label: str
    enabled: bool
    disabled_reason: str | None
    poll_minutes: int
    host: str  # the only part of the address that is ever logged
    reconcile: Reconcile
    fetch: Callable[[str | None, str | None], FetchResult]  # (etag, last_modified) -> result
    parse: Callable[[bytes, datetime], ParseResult]  # (body, now) -> events


def _unavailable(*_args) -> FetchResult:
    raise RuntimeError("a disabled source was asked to fetch")


def build_sources(settings: Settings) -> dict[str, Source]:
    on = settings.feeds_mode in ("live", "fixture")
    off_reason = None if on else "feeds are off (FEEDS_MODE=off)"
    common = dict(
        user_agent=USER_AGENT,
        timeout=settings.feed_timeout_seconds,
        max_bytes=settings.feed_max_bytes,
        trust_env=settings.feeds_mode == "live",  # fixture mode talks to loopback, which a proxy setting must not intercept
    )
    ff_url = settings.ff_feed_url
    news = Source(
        name="forexfactory",
        label="Economic news (ForexFactory)",
        enabled=on,
        disabled_reason=off_reason,
        poll_minutes=settings.ff_poll_minutes,
        host=url_host(ff_url),
        reconcile="upsert_window",
        fetch=lambda etag, modified: http.fetch(ff_url, accept=FF_ACCEPT, etag=etag, last_modified=modified, **common),
        parse=lambda body, now: forexfactory.parse(body),
    )

    ical_url = settings.gcal_url
    configured = on and ical_url is not None
    calendar = Source(
        name="gcal",
        label="Google Calendar",
        enabled=configured,
        disabled_reason=off_reason or (None if ical_url else "no calendar address is configured (GCAL_ICAL_URL)"),
        poll_minutes=settings.gcal_poll_minutes,
        host=url_host(ical_url) if ical_url else "",
        reconcile="mirror",
        fetch=(lambda etag, modified: http.fetch(ical_url, accept=ICAL_ACCEPT, etag=etag, last_modified=modified, **common)) if ical_url else _unavailable,
        parse=lambda body, now: gcal.parse(body, now=now, default_tz=settings.tz),
    )
    return {news.name: news, calendar.name: calendar}
