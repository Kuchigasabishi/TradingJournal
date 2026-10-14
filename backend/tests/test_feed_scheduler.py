"""The feed worker threads, for real: a migrated database file, the system clock, and scripted fetches. The point is
what a person feels: a manual sync returns at once, a slow feed never holds up another, and a crash is survived."""
import threading
import time

import pytest

from app.connectors.base import FetchFailed, FetchResult
from app.core.clock import SystemClock
from app.core.config import Settings
from app.db.migrate import run_migrations
from app.db.repositories import FeedStateRepository
from app.db.session import make_engine, make_session_factory
from app.services.feeds import FeedService
from app.services.scheduler import FeedScheduler
from feed_helpers import calendar_source, fixture, news_source
from test_feeds_service import NEW_YORK


@pytest.fixture
def factory(tmp_path):
    url = f"sqlite:///{(tmp_path / 'journal.db').as_posix()}"
    run_migrations(url)
    engine = make_engine(url)
    yield make_session_factory(engine)
    engine.dispose()


def build(factory, news_fetch, calendar_fetch, **overrides):
    settings = Settings(app_env="test", feeds_mode="live", feed_tick_seconds=0.05, sync_cooldown_seconds=0, _env_file=None, **overrides)
    sources = {"forexfactory": news_source(news_fetch), "gcal": calendar_source(calendar_fetch, NEW_YORK)}
    service = FeedService(factory, settings, SystemClock(), sources)
    return service, FeedScheduler(service)


def status_of(factory, name):
    with factory() as session:
        state = FeedStateRepository(session).get(name)
        return (state.state, state.status) if state else None


def wait_for(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


ok_news = lambda etag, modified: FetchResult(body=fixture("forexfactory", "week_a.json"))  # noqa: E731
ok_calendar = lambda etag, modified: FetchResult(body=fixture("gcal", "personal_a.ics"))  # noqa: E731


def test_both_feeds_are_fetched_at_startup_and_the_threads_stop_cleanly(factory):
    service, scheduler = build(factory, ok_news, ok_calendar)
    scheduler.start()
    try:
        assert wait_for(lambda: status_of(factory, "forexfactory") == ("idle", "ok") and status_of(factory, "gcal") == ("idle", "ok"))
    finally:
        scheduler.stop(timeout=3)
    assert not any(worker.is_alive() for worker in scheduler.workers.values())


def test_a_poke_runs_a_queued_sync_right_away(factory):
    calls = []

    def counting(etag, modified):
        calls.append(time.monotonic())
        return FetchResult(body=fixture("forexfactory", "week_a.json"))

    service, scheduler = build(factory, counting, ok_calendar)
    scheduler.start()
    try:
        assert wait_for(lambda: len(calls) == 1)
        assert wait_for(lambda: status_of(factory, "forexfactory") == ("idle", "ok"))
        with factory() as session:
            assert service.request_sync(session, ["forexfactory"])[0].outcome == "queued"
        scheduler.poke("forexfactory")
        assert wait_for(lambda: len(calls) == 2, timeout=2.0), "a poked worker syncs at once, not at its next tick or its next due time"
    finally:
        scheduler.stop(timeout=3)


def test_a_slow_feed_does_not_hold_up_the_other(factory):
    release = threading.Event()

    def stuck_calendar(etag, modified):
        release.wait(timeout=5)  # a calendar host that is taking its time
        return FetchResult(body=fixture("gcal", "personal_a.ics"))

    service, scheduler = build(factory, ok_news, stuck_calendar)
    scheduler.start()
    try:
        assert wait_for(lambda: status_of(factory, "gcal") == ("running", "never"))  # asking its host, which is not answering
        assert wait_for(lambda: status_of(factory, "forexfactory") == ("idle", "ok"))  # and the news worker finished meanwhile
        assert status_of(factory, "gcal") == ("running", "never")  # the calendar is still waiting
        release.set()
        assert wait_for(lambda: status_of(factory, "gcal") == ("idle", "ok"))
    finally:
        release.set()
        scheduler.stop(timeout=3)


def test_a_crash_in_one_sync_does_not_kill_the_worker(factory):
    attempts = []

    def flaky(etag, modified):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("the fetch blew up")
        return FetchResult(body=fixture("forexfactory", "week_a.json"))

    service, scheduler = build(factory, flaky, ok_calendar)
    scheduler.start()
    try:
        assert wait_for(lambda: status_of(factory, "forexfactory") == ("idle", "error"))
        with factory() as session:
            service.request_sync(session, ["forexfactory"])  # no cooldown in this test
        scheduler.poke("forexfactory")
        assert wait_for(lambda: status_of(factory, "forexfactory") == ("idle", "ok"))
    finally:
        scheduler.stop(timeout=3)


def test_a_failed_startup_fetch_waits_out_its_backoff(factory):
    attempts = []

    def failing(etag, modified):
        attempts.append(1)
        raise FetchFailed("HTTP 503", http_status=503)

    service, scheduler = build(factory, failing, ok_calendar)
    scheduler.start()
    try:
        assert wait_for(lambda: status_of(factory, "forexfactory") == ("idle", "error"))
        time.sleep(0.4)  # many ticks pass; the next attempt is 15 minutes away
        assert len(attempts) == 1
    finally:
        scheduler.stop(timeout=3)


def test_disabled_sources_get_no_worker(factory):
    settings = Settings(app_env="test", feeds_mode="live", _env_file=None)  # live, but no calendar address
    from app.connectors.registry import build_sources

    service = FeedService(factory, settings, SystemClock(), build_sources(settings))
    scheduler = FeedScheduler(service)
    assert sorted(scheduler.workers) == ["forexfactory"]
    assert service.sources["gcal"].disabled_reason == "no calendar address is configured (GCAL_ICAL_URL)"
