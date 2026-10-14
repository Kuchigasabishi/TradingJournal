import logging
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.connectors.base import FetchResult
from app.core.config import Settings
from app.db.models import ExternalEvent
from app.main import create_app
from feed_helpers import NOW, calendar_source, fixture, news_source
from test_feeds_service import FakeClock, Script
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def news(key, title, when, impact="high", currency="USD", **extra) -> ExternalEvent:
    return ExternalEvent(source="forexfactory", external_key=key, title=title, all_day=False, start_at=when, impact=impact, currency=currency, first_seen_at=NOW, updated_at=NOW, **extra)


def personal(key, title, start=None, end=None, first_day=None, last_exclusive=None) -> ExternalEvent:
    if first_day:
        return ExternalEvent(source="gcal", external_key=key, title=title, all_day=True, start_date=first_day, end_date=last_exclusive, first_seen_at=NOW, updated_at=NOW)
    return ExternalEvent(source="gcal", external_key=key, title=title, all_day=False, start_at=start, end_at=end, first_seen_at=NOW, updated_at=NOW)


def seed() -> list[ExternalEvent]:
    """Fresh objects every time: an ORM object that has been stored once would not be inserted into a second database."""
    return [
    news("n1", "CPI m/m", utc(2044, 5, 11, 12, 30)),  # 08:30 in New York, Wednesday the 11th
    news("n2", "Midnight in New York", utc(2044, 5, 11, 4, 0), impact="low", currency="GBP"),  # 00:00 on the 11th
    news("n3", "Just before midnight", utc(2044, 5, 12, 3, 59, 59), impact="medium", currency="EUR"),  # 23:59:59 on the 11th
    news("n4", "Everyone's event", utc(2044, 5, 12, 14, 0), impact="medium", currency="ALL"),
    personal("p1", "Asia session review", start=utc(2044, 5, 13, 2), end=utc(2044, 5, 13, 6)),  # 22:00 on the 12th to 02:00 on the 13th
    personal("p2", "Ends at midnight", start=utc(2044, 5, 14, 2), end=utc(2044, 5, 14, 4)),  # 22:00 to 00:00: only the 13th
    personal("p3", "Trading course", first_day=date(2044, 5, 18), last_exclusive=date(2044, 5, 21)),  # the 18th, 19th and 20th
    personal("p4", "Bank day off", first_day=date(2044, 5, 12), last_exclusive=date(2044, 5, 13)),
    ]


@pytest.fixture
def client(engine, session):
    session.add_all(seed())
    session.commit()
    settings = Settings(app_env="test", feeds_mode="off", database_url="sqlite://", app_timezone="America/New_York", auto_migrate=False, _env_file=None)
    return TestClient(create_app(settings, engine))


def listing(client, **params):
    response = client.get("/api/events", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def titles(page):
    return [item["title"] for item in page["items"]]


def test_events_are_ordered_by_day_with_all_day_first_then_by_time(client):
    page = listing(client, **{"from": "2044-05-11", "to": "2044-05-13"})
    assert titles(page) == [
        "Midnight in New York", "CPI m/m", "Just before midnight",  # the 11th: 00:00, 08:30 and 23:59:59 in New York
        "Bank day off", "Everyone's event", "Asia session review",  # the 12th: all-day first, then 10:00, then the overnight event (22:00)
        "Ends at midnight",  # the 13th. The overnight event runs into it but is listed once, on the day it starts
    ]
    assert page["total"] == len(page["items"]) == 7


def test_the_day_an_event_falls_on_is_its_day_in_the_servers_zone_not_utc(client):
    items = {item["title"]: item for item in listing(client)["items"]}
    assert (items["Just before midnight"]["start_day"], items["Just before midnight"]["end_day"]) == ("2044-05-11", "2044-05-11")  # 03:59:59Z is still the 11th in New York
    assert (items["Midnight in New York"]["start_day"]) == "2044-05-11"
    assert (items["Asia session review"]["start_day"], items["Asia session review"]["end_day"]) == ("2044-05-12", "2044-05-13")  # crosses midnight: two days
    assert (items["Ends at midnight"]["start_day"], items["Ends at midnight"]["end_day"]) == ("2044-05-13", "2044-05-13")  # ending exactly at midnight does not spill over
    assert (items["Trading course"]["start_day"], items["Trading course"]["end_day"]) == ("2044-05-18", "2044-05-20")  # the exclusive end date minus one
    assert items["Trading course"]["all_day"] and items["Trading course"]["start_at"] is None


def test_a_range_returns_every_event_that_covers_any_of_its_days(client):
    assert titles(listing(client, **{"from": "2044-05-19", "to": "2044-05-19"})) == ["Trading course"]  # the middle of a three-day event
    assert titles(listing(client, **{"from": "2044-05-21", "to": "2044-05-30"})) == []  # the day after its exclusive end
    assert titles(listing(client, **{"from": "2044-05-14", "to": "2044-05-14"})) == []  # the event that ended at midnight is not on the 14th
    assert titles(listing(client, **{"from": "2044-05-13", "to": "2044-05-13"})) == ["Asia session review", "Ends at midnight"]


def test_filters_by_source_impact_and_currency(client):
    assert titles(listing(client, source="gcal")) == ["Bank day off", "Asia session review", "Ends at midnight", "Trading course"]
    assert titles(listing(client, impact="high")) == ["CPI m/m"]
    assert titles(listing(client, impact=["high", "medium"])) == ["CPI m/m", "Just before midnight", "Everyone's event"]
    # A currency filter keeps events for every currency (ALL) too, ignores case, and drops events that have no currency at all.
    assert titles(listing(client, currency="eur")) == ["Just before midnight", "Everyone's event"]
    assert titles(listing(client, currency="USD", source="gcal")) == []


def test_paging_reports_the_total(client):
    page = listing(client, limit=3, offset=2)
    assert (len(page["items"]), page["total"], page["limit"], page["offset"]) == (3, 8, 3, 2)


@pytest.mark.parametrize("params", [{"from": "2044-05-13", "to": "2044-05-12"}, {"source": "outlook"}, {"impact": "extreme"}, {"limit": 0}, {"limit": 501}, {"from": "May 13"}])
def test_bad_queries_are_422(client, params):
    assert client.get("/api/events", params=params).status_code == 422


def test_the_end_of_daylight_saving_time_does_not_shift_days(engine, session):
    # 02:00 clocks go back at 06:00 UTC on Sunday 6 November 2044; 00:30 and 23:30 New York that day are on the 6th, not the 5th or 7th.
    session.add_all([news("d1", "Early", utc(2044, 11, 6, 4, 30)), news("d2", "Late", utc(2044, 11, 7, 4, 30))])
    session.commit()
    settings = Settings(app_env="test", database_url="sqlite://", app_timezone="America/New_York", auto_migrate=False, _env_file=None)
    page = TestClient(create_app(settings, engine)).get("/api/events", params={"from": "2044-11-06", "to": "2044-11-06"}).json()
    assert [item["title"] for item in page["items"]] == ["Early", "Late"]  # 04:30Z is 00:30 EDT; 04:30Z the next day is 23:30 EST on the same local day


def test_the_new_operations_are_marked_as_phase_3_in_the_api_description(client):
    paths = client.get("/api/openapi.json").json()["paths"]
    assert paths["/api/events"]["get"]["x-phase"] == 3
    assert paths["/api/sync"]["post"]["x-phase"] == 3
    assert paths["/api/sources/status"]["get"]["x-phase"] == 3
    assert "x-phase" not in paths["/api/trades"]["get"]  # everything older is phase 1 by default


# --- sources and manual sync ----------------------------------------------------------------------------------------------


class FakeScheduler:
    def __init__(self) -> None:
        self.poked: list[str] = []

    def poke(self, name: str) -> None:
        self.poked.append(name)


@pytest.fixture
def synced(engine):
    """An app whose feeds are on, with scripted sources and a scheduler that only records pokes."""
    settings = Settings(app_env="test", feeds_mode="live", database_url="sqlite://", app_timezone="America/New_York", sync_cooldown_seconds=120, auto_migrate=False, _env_file=None)
    app = create_app(settings, engine)
    clock = FakeClock()
    app.state.clock = clock
    app.state.feeds.clock = clock
    app.state.feeds.sources = {
        "forexfactory": news_source(Script(FetchResult(body=fixture("forexfactory", "week_a.xml")))),
        "gcal": calendar_source(Script(FetchResult(body=fixture("gcal", "personal_a.ics"))), NEW_YORK),
    }
    app.state.scheduler = FakeScheduler()
    return TestClient(app), app, clock


def test_sources_status_lists_both_feeds_and_what_is_disabled(client):
    sources = client.get("/api/sources/status").json()
    assert [(s["source"], s["enabled"], s["status"], s["state"]) for s in sources] == [("forexfactory", False, "never", "idle"), ("gcal", False, "never", "idle")]
    assert sources[0]["disabled_reason"] == "feeds are off (FEEDS_MODE=off)" and sources[0]["event_count"] == 4 and sources[1]["event_count"] == 4


def test_a_sync_request_is_accepted_at_once_and_wakes_the_worker(synced, caplog):
    client, app, _ = synced
    caplog.set_level(logging.INFO, logger="app.db")
    response = client.post("/api/sync", headers={"X-Request-ID": "web-sync-1"})
    assert response.status_code == 202
    assert response.json() == {"sources": [{"source": "forexfactory", "outcome": "queued", "retry_after_seconds": None}, {"source": "gcal", "outcome": "queued", "retry_after_seconds": None}]}
    assert app.state.scheduler.poked == ["forexfactory", "gcal"]
    # The request's own transaction recorded the queue, so the accepted request is backed by a commit with its request id.
    assert any(r.getMessage() == "db_transaction" and r.outcome == "commit" and r.writes > 0 for r in caplog.records)


def test_a_source_can_be_picked_and_a_second_request_while_queued_is_409(synced):
    client, app, _ = synced
    assert client.post("/api/sync", params={"source": "gcal"}).status_code == 202
    assert app.state.scheduler.poked == ["gcal"]
    again = client.post("/api/sync", params={"source": "gcal"})
    assert again.status_code == 409 and again.json()["sources"] == [{"source": "gcal", "outcome": "running", "retry_after_seconds": None}]
    assert "retry-after" not in again.headers


def test_inside_the_cooldown_the_answer_is_429_with_retry_after(synced):
    client, app, clock = synced
    client.post("/api/sync", params={"source": "forexfactory"})
    app.state.feeds.run_sync("forexfactory", "manual")  # the worker finishes it
    clock.advance(seconds=30)
    response = client.post("/api/sync", params={"source": "forexfactory"})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "90"
    assert response.json()["sources"] == [{"source": "forexfactory", "outcome": "cooldown", "retry_after_seconds": 90}]
    clock.advance(seconds=91)
    assert client.post("/api/sync", params={"source": "forexfactory"}).status_code == 202


def test_syncing_with_feeds_off_is_409_disabled(client):
    response = client.post("/api/sync")
    assert response.status_code == 409
    assert [(s["source"], s["outcome"]) for s in response.json()["sources"]] == [("forexfactory", "disabled"), ("gcal", "disabled")]


def test_an_unknown_source_is_422(synced):
    assert synced[0].post("/api/sync", params={"source": "outlook"}).status_code == 422


def test_after_a_sync_the_events_and_the_status_show_up_in_the_api(synced):
    client, app, _ = synced
    client.post("/api/sync")
    for name in ("forexfactory", "gcal"):
        app.state.feeds.run_sync(name, "manual")
    sources = {s["source"]: s for s in client.get("/api/sources/status").json()}
    assert (sources["forexfactory"]["status"], sources["forexfactory"]["event_count"], sources["gcal"]["status"], sources["gcal"]["event_count"]) == ("ok", 108, "ok", 70)
    page = client.get("/api/events", params={"from": "2044-05-11", "to": "2044-05-11", "impact": "high", "currency": "USD", "limit": 50}).json()
    assert {i["title"] for i in page["items"]} >= {"Core CPI m/m", "CPI m/m", "Core CPI y/y", "CPI y/y"}
    assert all(i["impact"] == "high" and i["currency"] in ("USD", "ALL") for i in page["items"])
    sync_again = client.post("/api/sync")
    assert sync_again.status_code == 429  # both feeds are inside their cooldown
