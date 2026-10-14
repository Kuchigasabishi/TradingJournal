"""Helpers for the Phase 3 tests: scripting the feed stub, running syncs, and the fixtures as an oracle.

scripts/verify.py starts the stub and the app and passes the rest through the environment:

    FEED_STUB_URL   where the stub listens (its control API is under /__)
    FEEDS_NOW       where the app's feed clock started: Wednesday 2044-05-11 12:00 UTC
    FEED_COOLDOWN   the app's SYNC_COOLDOWN_SECONDS, so a test can wait it out instead of guessing
    GCAL_ICAL_URL   the calendar address the app was given, a secret, so tests can check it never surfaces
    SERVER_RESTARTED_AT   (second pass only) when the app was restarted

The expected events are read from the fixture files here, with plain json and by writing out what
personal_<x>.ics holds, independently of the app's parsers: a test compares the app against the files, not against itself.
"""
import json
import os
import re
import time
import urllib.request
import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from support.ui import wall_to_utc

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
SOURCES = ("forexfactory", "gcal")
TOKEN = re.compile(r"private-[0-9a-fA-F]{16,}")
STAMP = "%Y-%m-%dT%H:%M:%SZ"
NEW_YORK = "America/New_York"
LONDON = "Europe/London"

# Remembers, per feed, when this process last asked for a sync, so a test can wait out the app's cooldown.
_last_request: dict[str, float] = {}


def poll_id() -> str:
    """A request id for traffic whose amount depends on timing (waiting for a background sync takes however many polls it takes).
    scripts/verify.py leaves "poll-" requests out of its counts, so metrics.json stays the same from one run to the next."""
    return f"poll-{uuid.uuid4().hex[:10]}"


def env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        pytest.exit(f"{name} is not set. The Phase 3 tests run through scripts/verify.py 3, which starts the feed stub and the app", returncode=2)
    return value


def cooldown_seconds() -> float:
    return float(env("FEED_COOLDOWN"))


def secret_url() -> str:
    return env("GCAL_ICAL_URL")


def when(text: str) -> datetime:
    """An instant as the API writes it ("2044-05-11T12:00:00Z", maybe with fractions of a second)."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def assert_no_secret(text: str, where: str = "the response") -> None:
    """The calendar address is a secret: neither it, nor its token, nor the host it lives on may appear."""
    assert secret_url() not in text, f"the secret calendar address is in {where}"
    assert not TOKEN.search(text), f"a calendar token is in {where}"
    assert env("FEED_STUB_URL") not in text, f"a feed address is in {where}"


# --- the stub ---------------------------------------------------------------------------------------------------------------


class FeedStub:
    """The stub's control API. Plain urllib: these calls are the test talking to its own fake, not traffic worth logging."""

    def __init__(self, base_url: str) -> None:
        self.base = base_url.rstrip("/")

    def _call(self, method: str, path: str, body: dict | None = None) -> Any:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read() or b"null")

    def script(self, ff: dict | None = None, gcal: dict | None = None) -> None:
        """Change how the next answers look, for example script(ff={"variant": "b"}) or script(gcal={"mode": "http_404"})."""
        changes = {name: values for name, values in (("ff", ff), ("gcal", gcal)) if values}
        self._call("POST", "/__control", changes)

    def reset(self) -> None:
        self._call("POST", "/__reset")

    def state(self) -> dict:
        return self._call("GET", "/__state")

    def requests(self, feed: str | None = None) -> list[dict]:
        """What the app asked the stub for since the last reset, oldest first."""
        rows = [r for r in self._call("GET", "/__requests") if r.get("msg") == "stub_request"]
        return [r for r in rows if feed is None or r.get("feed") == feed]


def stub() -> FeedStub:
    return FeedStub(env("FEED_STUB_URL"))


# --- the news fixtures, as an oracle ------------------------------------------------------------------------------------------


def ff_week(name: str) -> dict[tuple[str, str, str], dict]:
    """A fixture week from its JSON form (explicit offsets), keyed by (title, currency, UTC instant).

    Each value is what the API should return for that event, apart from `id` and `updated_at`."""
    events = {}
    for item in json.loads((FIXTURES / "forexfactory" / f"{name}.json").read_text(encoding="utf-8")):
        local = datetime.fromisoformat(item["date"])  # New York wall clock with its offset
        when = local.astimezone(timezone.utc).strftime(STAMP)
        currency = item["country"].upper()
        events[(item["title"], currency, when)] = {
            "source": "forexfactory",
            "title": item["title"],
            "currency": currency,
            "impact": item["impact"].lower(),
            "forecast": item["forecast"] or None,
            "previous": item["previous"] or None,
            "all_day": False,
            "start_at": when,
            "end_at": None,
            "start_day": local.date().isoformat(),
            "end_day": local.date().isoformat(),
        }
    return events


def news_key(event: dict) -> tuple[str, str, str]:
    return (event["title"], event["currency"] or "", event["start_at"])


def news_view(event: dict) -> dict:
    """The fields of a stored news event a fixture can speak for."""
    names = ("source", "title", "currency", "impact", "forecast", "previous", "all_day", "start_at", "end_at", "start_day", "end_day")
    return {name: event[name] for name in names}


# --- the calendar fixtures, as an oracle ----------------------------------------------------------------------------------------


def _new_york_day(stamp: str) -> date:
    return datetime.strptime(stamp, STAMP).replace(tzinfo=timezone.utc).astimezone(ZoneInfo(NEW_YORK)).date()


def _timed(title: str, start: str, end: str, zone: str = NEW_YORK, **extra: Any) -> dict:
    """A timed event written as wall-clock text in `zone` ("2044-05-10 10:00"); the API shows UTC instants and New York days."""
    first, last = wall_to_utc(start, zone), wall_to_utc(end, zone)
    return {
        "title": title, "all_day": False, "start_at": first, "end_at": last,
        "start_day": _new_york_day(first).isoformat(), "end_day": _new_york_day(last).isoformat(),
        "description": None, "location": None, **extra,
    }


def _all_day(title: str, first: str, last: str, **extra: Any) -> dict:
    """An all-day event from `first` to `last`, both inclusive."""
    return {"title": title, "all_day": True, "start_at": None, "end_at": None, "start_day": first, "end_day": last, "description": None, "location": None, **extra}


def calendar_key(event: dict) -> tuple[str, str]:
    return (event["title"], event["start_at"] or event["start_day"])


def calendar_view(event: dict) -> dict:
    """The fields of a stored calendar event a fixture can speak for."""
    names = ("title", "all_day", "start_at", "end_at", "start_day", "end_day", "description", "location")
    return {name: event[name] for name in names}


def calendar_events(variant: str) -> dict[tuple[str, str], dict]:
    """What fixtures/gcal/personal_<variant>.ics holds inside the sync window (60 days back and 400 ahead of 2044-05-11),
    written out by hand from the file, keyed by (title, start)."""
    events: list[dict] = []
    review = "Review the week, check the journal.\nBring the charts."
    slot = date(2044, 4, 4)  # a Monday: the series starts here and repeats weekly with no end
    while slot <= date(2045, 6, 15):  # the window ends 400 days after 2044-05-11
        if slot not in (date(2044, 5, 16), date(2044, 5, 23), date(2044, 5, 30)):  # moved, EXDATE, cancelled
            events.append(_timed("Weekly review", f"{slot} 10:00", f"{slot} 10:30", description=review))
        slot += timedelta(days=7)
    events += [
        _timed("Weekly review (moved)", "2044-05-17 15:00", "2044-05-17 15:30"),
        # written in UTC; calendar B moves it an hour later
        _timed("Call with the prop firm", "2044-05-10 15:00" if variant == "b" else "2044-05-10 14:00", "2044-05-10 16:00" if variant == "b" else "2044-05-10 15:00", zone="UTC"),
        _timed("Café – résumé review", "2044-05-10 16:00", "2044-05-10 16:30"),
        # written in London time (summer time, one hour ahead of UTC)
        _timed(
            "London open briefing", "2044-05-11 09:00", "2044-05-11 10:00", zone=LONDON, location="Zoom, London desk",
            description="Walk through the overnight Asian range and the London open plan, including the levels from last week, the news calendar and the risk limits for the session.",
        ),
        _all_day("Bank day off", "2044-05-12", "2044-05-12"),
        _timed("Floating dinner", "2044-05-12 18:00", "2044-05-12 19:00"),  # no zone: read in the calendar's own, New York
        _timed("Asia session review", "2044-05-12 22:00", "2044-05-13 02:00"),  # crosses midnight
        _all_day("Trading course (advanced)" if variant == "b" else "Trading course", "2044-05-18", "2044-05-20"),  # DTEND is exclusive: the 21st
        _all_day("Quarter-end planning", "2044-06-30", "2044-06-30"),
    ]
    if variant == "a":
        events.append(
            # the file holds HTML: line breaks, a link and a non-breaking space
            _timed("Broker call", "2044-05-13 11:00", "2044-05-13 11:30", description="Agenda:\n1. Margin rules\n2. Platform update and fees\n\nBring questions."),
        )
    else:
        events.append(_timed("FOMC watch party", "2044-05-12 14:00", "2044-05-12 16:00", description="Watch the statement together.", location="Discord"))
    return {calendar_key(event): event for event in events}


# --- what a screen should show, from the oracles ---------------------------------------------------------------------------------


def day_news(events, day: str, impacts: tuple[str, ...] = (), currency: str | None = None) -> Counter:
    """How many news events of each impact fall on a New York day, narrowed the way the screens' filters narrow them."""
    counts: Counter = Counter()
    for event in events:
        if event["start_day"] != day:
            continue
        if impacts and event["impact"] not in impacts:
            continue
        if currency and event["currency"] not in (currency, "ALL"):  # news for every currency concerns each currency
            continue
        counts[event["impact"]] += 1
    return counts


def day_personal(events, day: str) -> list[dict]:
    """The calendar events that cover a day, in the order the screens list them: all-day first, then by start."""
    covering = [event for event in events if event["start_day"] <= day <= event["end_day"]]
    return sorted(covering, key=lambda event: (not event["all_day"], event["start_at"] or "", event["title"]))


def month_days(month: str) -> list[str]:
    """Every day of a month ("2044-05") as text."""
    first = date.fromisoformat(f"{month}-01")
    days = []
    while first.month == int(month[5:7]):
        days.append(first.isoformat())
        first += timedelta(days=1)
    return days


# --- running syncs ------------------------------------------------------------------------------------------------------------


class Feeds:
    """Drives syncs through the public API and waits for them, the way a person pressing "Sync now" would."""

    def __init__(self, api: Any, feed_stub: FeedStub) -> None:
        self.api = api
        self.stub = feed_stub
        self.dirty = False

    def status(self) -> dict[str, dict]:
        response = self.api.get("/api/sources/status", headers={"X-Request-ID": poll_id()})
        assert response.status == 200, response.text()
        return {row["source"]: row for row in response.json()}

    def events(self, **params: Any) -> dict:
        query = "&".join(f"{name}={value}" for name, value in params.items())
        response = self.api.get("/api/events" + (f"?{query}" if query else ""))
        assert response.status == 200, response.text()
        return response.json()

    def all_events(self, source: str) -> list[dict]:
        page = self.events(source=source, limit=500)
        assert page["total"] == len(page["items"]), "a source holds more events than one page"
        return page["items"]

    def script(self, ff: dict | None = None, gcal: dict | None = None) -> None:
        self.dirty = True
        self.stub.script(ff=ff, gcal=gcal)

    def mark_requested(self, *sources: str) -> None:
        """Note that something other than this helper (a button in the browser) asked for a sync just now."""
        for name in sources or SOURCES:
            _last_request[name] = time.monotonic()

    def cool_down(self, *sources: str) -> None:
        """Wait until the app would accept another manual sync of each source."""
        for name in sources or SOURCES:
            ready = _last_request.get(name, 0.0) + cooldown_seconds() + 0.25
            time.sleep(max(0.0, ready - time.monotonic()))

    def wait_idle(self, *sources: str, timeout: float = 20.0) -> dict[str, dict]:
        names = sources or SOURCES
        deadline = time.monotonic() + timeout
        while True:
            status = self.status()
            if all(status[name]["state"] == "idle" for name in names):
                return status
            assert time.monotonic() < deadline, f"still syncing after {timeout}s: { {n: status[n]['state'] for n in names} }"
            time.sleep(0.2)

    def request(self, *sources: str, timeout: float = 15.0):
        """POST /api/sync once the feeds are out of their cooldown (it waits that out first, so one request is the usual number),
        and again only if the app still says it is busy or too soon, until one is accepted (202)."""
        query = "&".join(f"source={name}" for name in sources)
        self.cool_down(*sources)
        deadline = time.monotonic() + timeout
        while True:
            response = self.api.post("/api/sync" + (f"?{query}" if query else ""), headers={"X-Request-ID": poll_id()})
            if response.status == 202:
                self.mark_requested(*[r["source"] for r in response.json()["sources"] if r["outcome"] == "queued"])
                return response
            assert response.status in (409, 429) and time.monotonic() < deadline, f"/api/sync answered {response.status}: {response.text()}"
            time.sleep(0.3)

    def wait_finished(self, before: dict[str, dict], *sources: str, timeout: float = 25.0) -> dict[str, dict]:
        """Wait until each source is idle again and has made an attempt since `before` (an earlier `status()`)."""
        names = sources or SOURCES
        deadline = time.monotonic() + timeout
        while True:
            status = self.status()
            if all(status[name]["state"] == "idle" and status[name]["last_attempt_at"] != before[name]["last_attempt_at"] for name in names):
                return status
            assert time.monotonic() < deadline, f"the sync of {names} did not finish: { {n: status[n]['state'] for n in names} }"
            time.sleep(0.2)

    def sync(self, *sources: str) -> dict[str, dict]:
        """Sync each source (both by default) and wait until every one has finished. Returns the status of all sources."""
        names = sources or SOURCES
        self.wait_idle(*names)
        before = self.status()
        for name in names:
            self.request(name)
        return self.wait_finished(before, *names)

    def restore(self) -> None:
        """Back to the baseline every test starts from: the stub on its defaults, both feeds synced from week A and calendar A."""
        self.stub.reset()
        self.sync()
        self.dirty = False
