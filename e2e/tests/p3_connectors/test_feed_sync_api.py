"""Phase 3: asking the app to sync, and what comes back. The feeds are the local stub (fixtures/), never the internet.

The app syncs both feeds as it starts, and again whenever someone asks (POST /api/sync). A request is answered at
once, whatever the host is doing: the fetch runs on the feed's own worker thread.
"""
import time
from datetime import timedelta

from support.feeds import SOURCES, assert_no_secret, calendar_events, cooldown_seconds, ff_week, when

NEWS_EVENTS = len(ff_week("week_a"))
CALENDAR_EVENTS = len(calendar_events("a"))
STATUS_FIELDS = {
    "source", "label", "enabled", "disabled_reason", "state", "status", "message", "http_status", "last_attempt_at",
    "last_success_at", "next_due_at", "next_manual_at", "consecutive_failures", "event_count", "poll_minutes",
}


def test_both_feeds_were_synced_when_the_app_started(feeds):
    status = feeds.status()
    assert list(status) == ["forexfactory", "gcal"]
    assert status["forexfactory"]["label"] == "Economic news (ForexFactory)"
    assert status["gcal"]["label"] == "Google Calendar"
    for name, row in status.items():
        assert row["enabled"] is True and row["disabled_reason"] is None, name
        assert (row["state"], row["status"], row["message"], row["consecutive_failures"]) == ("idle", "ok", None, 0), name
        assert row["http_status"] in (200, 304), name  # 304 when a later sync found the feed unchanged
        assert row["last_attempt_at"] and row["last_success_at"], name  # next_manual_at stays empty until someone asks for a sync
        # the next scheduled sync is one poll interval after the last success
        assert when(row["next_due_at"]) - when(row["last_success_at"]) == timedelta(minutes=row["poll_minutes"]), name
    assert status["forexfactory"]["event_count"] == NEWS_EVENTS
    assert status["gcal"]["event_count"] == CALENDAR_EVENTS


def test_the_status_never_carries_an_address(api):
    response = api.get("/api/sources/status")
    assert response.status == 200
    assert_no_secret(response.text(), "GET /api/sources/status")
    for row in response.json():
        assert set(row) == STATUS_FIELDS


def test_the_app_identifies_itself_and_asks_for_the_right_thing(feeds):
    feeds.sync()
    news, calendar = feeds.stub.requests("forexfactory")[-1], feeds.stub.requests("gcal")[-1]
    assert news["method"] == calendar["method"] == "GET"
    assert news["user_agent"] == calendar["user_agent"] == "TradingJournal/0.3 (personal, single-user)"
    assert news["path"] == "/ff/thisweek.xml"
    assert news["accept"].startswith("application/json") and "text/xml" in news["accept"]
    assert calendar["path"] == "/gcal/ical/me/private-***/basic.ics"  # the stub masks the secret in its own log
    assert calendar["accept"].startswith("text/calendar")


def test_a_manual_sync_is_accepted_at_once_and_runs_in_the_background(feeds, api):
    feeds.wait_idle()
    feeds.cool_down()
    before = feeds.status()
    asked = time.perf_counter()
    response = api.post("/api/sync")
    took = time.perf_counter() - asked
    feeds.mark_requested()
    assert response.status == 202
    assert response.json() == {
        "sources": [
            {"source": "forexfactory", "outcome": "queued", "retry_after_seconds": None},
            {"source": "gcal", "outcome": "queued", "retry_after_seconds": None},
        ]
    }
    assert took < 1.0, f"the request took {took:.2f}s: it must not wait for the fetch"
    after = feeds.wait_finished(before)
    for name in SOURCES:
        assert when(after[name]["last_attempt_at"]) > when(before[name]["last_attempt_at"]), name
        assert when(after[name]["last_success_at"]) > when(before[name]["last_success_at"]), name
        assert (after[name]["state"], after[name]["status"]) == ("idle", "ok"), name


def test_a_second_request_inside_the_cooldown_is_answered_429_with_retry_after(feeds, api):
    feeds.sync("forexfactory")
    response = api.post("/api/sync?source=forexfactory")
    assert response.status == 429
    wait = int(response.headers["retry-after"])
    assert 1 <= wait <= cooldown_seconds()
    assert response.json() == {"sources": [{"source": "forexfactory", "outcome": "cooldown", "retry_after_seconds": wait}]}

    # each feed has a cooldown of its own: the calendar can still be synced
    feeds.wait_idle()
    feeds.cool_down("gcal")
    before = feeds.status()
    assert api.post("/api/sync?source=gcal").status == 202
    feeds.mark_requested("gcal")
    feeds.wait_finished(before, "gcal")

    # and once the wait is over the news feed is accepted again
    time.sleep(wait + 0.3)
    assert api.post("/api/sync?source=forexfactory").status == 202
    feeds.mark_requested("forexfactory")
    feeds.wait_idle()


def test_a_slow_host_never_holds_up_the_app(feeds, api):
    feeds.wait_idle()
    feeds.cool_down()
    events_before = feeds.all_events("forexfactory")
    before = feeds.status()
    feeds.script(ff={"mode": "slow"})  # the stub sits on the request for longer than the app's timeout

    asked = time.perf_counter()
    response = api.post("/api/sync?source=forexfactory")
    assert response.status == 202
    assert time.perf_counter() - asked < 1.0
    feeds.mark_requested("forexfactory")

    # the same feed, asked again while it is busy, says so
    again = api.post("/api/sync?source=forexfactory")
    assert again.status == 409
    assert again.json() == {"sources": [{"source": "forexfactory", "outcome": "running", "retry_after_seconds": None}]}

    # the other feed has its own worker: it syncs while the news feed is still waiting for its host
    feeds.cool_down("gcal")
    calendar_before = feeds.status()
    assert api.post("/api/sync?source=gcal").status == 202
    feeds.mark_requested("gcal")
    calendar_done = feeds.wait_finished(calendar_before, "gcal")
    assert calendar_done["forexfactory"]["state"] in ("queued", "running"), "the news feed finished before the calendar did: the host was not slow"

    # everything else keeps answering quickly while the fetch waits
    for path in ("/api/health", "/api/sources/status", "/api/events?limit=5"):
        asked = time.perf_counter()
        assert api.get(path).status == 200
        assert time.perf_counter() - asked < 1.0, path

    # the app gives up on its own, says why, and keeps what it had
    done = feeds.wait_finished(before, "forexfactory")["forexfactory"]
    assert (done["status"], done["http_status"], done["message"]) == ("error", None, "timed out waiting for the host")
    assert done["consecutive_failures"] == 1
    assert feeds.all_events("forexfactory") == events_before


def test_only_known_feeds_can_be_asked_for(feeds, api):
    assert api.post("/api/sync?source=bogus").status == 422
    feeds.wait_idle()
    feeds.cool_down("gcal")
    before = feeds.status()
    response = api.post("/api/sync?source=gcal&source=gcal")  # the same feed twice is one request
    assert response.status == 202
    assert response.json() == {"sources": [{"source": "gcal", "outcome": "queued", "retry_after_seconds": None}]}
    feeds.mark_requested("gcal")
    feeds.wait_finished(before, "gcal")
