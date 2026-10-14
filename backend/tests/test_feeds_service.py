"""The sync engine: what a sync does to the stored events, and how it keeps its schedule, with a scripted feed and a
clock the test moves by hand. Runs on a migrated SQLite file, like production."""
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.connectors.base import BadContent, FeedError, FetchFailed, FetchResult, Throttled
from app.core.config import Settings
from app.db.migrate import run_migrations
from app.db.models import ExternalEvent, FeedState
from app.db.repositories import FeedStateRepository
from app.db.session import make_engine, make_session_factory
from app.services import feeds as feeds_module
from app.services.feeds import BACKOFF_MINUTES, FeedService
from feed_helpers import NOW, calendar_source, fixture, news_source

NEW_YORK = ZoneInfo("America/New_York")


class FakeClock:
    def __init__(self, now: datetime = NOW) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, **delta) -> None:
        self._now += timedelta(**delta)


class Script:
    """A fetch function that answers from a list, one answer per call: a FetchResult, or an exception to raise."""

    def __init__(self, *answers) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str | None, str | None]] = []

    def __call__(self, etag, last_modified):
        self.calls.append((etag, last_modified))
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer


def body(*parts: str) -> FetchResult:
    return FetchResult(body=fixture(*parts), etag=f'"{parts[-1]}"')


@pytest.fixture
def factory(tmp_path):
    url = f"sqlite:///{(tmp_path / 'journal.db').as_posix()}"
    run_migrations(url)
    engine = make_engine(url)
    yield make_session_factory(engine)
    engine.dispose()


def settings(**overrides) -> Settings:
    options = dict(app_env="test", feeds_mode="live", app_timezone="America/New_York", sync_cooldown_seconds=300, _env_file=None)
    return Settings(**{**options, **overrides})


def service(factory, clock, news=None, calendar=None, **setting_overrides) -> FeedService:
    sources = {}
    if news is not None:
        sources["forexfactory"] = news_source(news)
    if calendar is not None:
        sources["gcal"] = calendar_source(calendar, NEW_YORK)
    return FeedService(factory, settings(**setting_overrides), clock, sources)


def titles(factory, source: str) -> list[str]:
    with factory() as session:
        return sorted(row.title for row in session.scalars(select(ExternalEvent).where(ExternalEvent.source == source)))


def state_of(factory, source: str) -> FeedState:
    with factory() as session:
        state = FeedStateRepository(session).get(source)
        if state is not None:
            session.expunge(state)
        return state


def feed_records(caplog):
    return [r for r in caplog.records if r.getMessage() == "feed_sync"]


@pytest.fixture(autouse=True)
def log_feeds(caplog):
    caplog.set_level(logging.INFO, logger="app.feeds")


# --- a first sync ------------------------------------------------------------------------------------------------


def test_the_first_sync_stores_the_events_and_records_the_success(factory, caplog):
    clock = FakeClock()
    feed = Script(body("forexfactory", "week_a.xml"))
    svc = service(factory, clock, news=feed)
    assert svc.run_sync("forexfactory", "startup") == "ok"

    assert len(titles(factory, "forexfactory")) == 108
    state = state_of(factory, "forexfactory")
    assert (state.state, state.status, state.message, state.consecutive_failures) == ("idle", "ok", None, 0)
    assert state.last_attempt_at == state.last_success_at == NOW
    assert state.next_due_at == NOW + timedelta(minutes=60)
    assert state.etag == '"week_a.xml"'
    record = feed_records(caplog)[-1]
    assert (record.feed, record.trigger, record.outcome, record.added, record.removed, record.event_count) == ("forexfactory", "startup", "ok", 108, 0, 108)
    assert record.host == "feeds.example.test" and record.levelno == logging.INFO


def test_a_second_sync_of_the_same_feed_changes_nothing(factory, caplog):
    clock = FakeClock()
    svc = service(factory, clock, news=Script(body("forexfactory", "week_a.json")))
    svc.run_sync("forexfactory", "startup")
    clock.advance(hours=1)
    svc.run_sync("forexfactory", "schedule")
    record = feed_records(caplog)[-1]
    assert (record.added, record.updated, record.unchanged, record.removed) == (0, 0, 108, 0)


def test_the_stored_validators_go_out_with_the_next_request_and_a_304_changes_nothing(factory, caplog):
    clock = FakeClock()
    feed = Script(FetchResult(body=fixture("forexfactory", "week_a.xml"), etag='W/"1"', last_modified="Tue, 11 May 2044 08:00:00 GMT"), FetchResult(not_modified=True, http_status=304))
    svc = service(factory, clock, news=feed)
    svc.run_sync("forexfactory", "startup")
    clock.advance(hours=1)
    assert svc.run_sync("forexfactory", "schedule") == "unchanged"
    assert feed.calls == [(None, None), ('W/"1"', "Tue, 11 May 2044 08:00:00 GMT")]
    state = state_of(factory, "forexfactory")
    assert state.status == "ok" and state.last_success_at == NOW + timedelta(hours=1) and state.etag == 'W/"1"'
    assert len(titles(factory, "forexfactory")) == 108


# --- reconciling news: add, update, remove what is still to come, never the past ----------------------------------------


def test_week_b_adds_updates_and_removes_only_future_events_inside_the_window(factory, caplog):
    clock = FakeClock()
    svc = service(factory, clock, news=Script(body("forexfactory", "week_a.xml"), body("forexfactory", "week_b.xml")))
    svc.run_sync("forexfactory", "startup")
    clock.advance(hours=1)
    svc.run_sync("forexfactory", "schedule")

    record = feed_records(caplog)[-1]
    assert (record.added, record.updated, record.removed) == (2, 2, 2)
    now_titles = titles(factory, "forexfactory")
    assert "Unemployment Claims" not in now_titles  # future, inside the window, no longer listed: gone
    assert "Cash Rate" in now_titles  # new
    assert "MPC Member Mann Speaks" in now_titles  # past: the feed dropped it, history stays
    assert len(now_titles) == 108  # 108 - 2 removed + 2 added

    with factory() as session:
        rows = {(r.title, r.currency): r for r in session.scalars(select(ExternalEvent))}
    assert rows[("Core Retail Sales m/m", "USD")].forecast == "0.5%"  # a revised forecast overwrites
    with factory() as session:
        bailey = session.scalars(select(ExternalEvent).where(ExternalEvent.start_at == datetime(2044, 5, 12, 7, 30, tzinfo=timezone.utc), ExternalEvent.title == "BOE Gov Bailey Speaks")).one()
    assert bailey.impact == "low"  # was medium in week A
    macklem = sorted(r.start_at for (t, c), r in rows.items() if t == "BOC Gov Macklem Speaks")
    assert macklem == [datetime(2044, 5, 13, 4, 45, tzinfo=timezone.utc)]  # moved 30 minutes: the old row is gone, the new one is there


def test_a_future_event_outside_the_fetched_window_is_left_alone(factory):
    clock = FakeClock()
    svc = service(factory, clock, news=Script(body("forexfactory", "week_a.xml")))
    with factory() as session:
        session.add(ExternalEvent(source="forexfactory", external_key="next-week", title="Next week's event", all_day=False, start_at=datetime(2044, 5, 20, 12, 30, tzinfo=timezone.utc), first_seen_at=NOW, updated_at=NOW))
        session.commit()
    svc.run_sync("forexfactory", "startup")
    assert "Next week's event" in titles(factory, "forexfactory")


# --- reconciling the calendar: mirror ---------------------------------------------------------------------------------


def test_the_calendar_is_mirrored_and_changed_events_keep_their_rows(factory, caplog):
    clock = FakeClock()
    svc = service(factory, clock, calendar=Script(body("gcal", "personal_a.ics"), body("gcal", "personal_b.ics")))
    svc.run_sync("gcal", "startup")
    before = titles(factory, "gcal")
    assert len(before) == 70 and "Broker call" in before
    with factory() as session:
        ids = {r.title: r.id for r in session.scalars(select(ExternalEvent))}

    clock.advance(minutes=30)
    svc.run_sync("gcal", "schedule")
    record = feed_records(caplog)[-1]
    assert (record.added, record.removed) == (1, 1)  # FOMC watch party in, Broker call out
    after = titles(factory, "gcal")
    assert "Broker call" not in after and "FOMC watch party" in after and "Trading course (advanced)" in after
    with factory() as session:
        rows = {r.title: r for r in session.scalars(select(ExternalEvent))}
    assert rows["Trading course (advanced)"].id == ids["Trading course"], "a renamed event is updated in place"
    assert rows["Call with the prop firm"].id == ids["Call with the prop firm"], "so is a one-off event that moved"
    assert rows["Call with the prop firm"].start_at == datetime(2044, 5, 10, 15, tzinfo=timezone.utc)


def test_an_empty_calendar_empties_the_mirror(factory):
    clock = FakeClock()
    empty = FetchResult(body=b"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//t//EN\nEND:VCALENDAR\n")
    svc = service(factory, clock, calendar=Script(body("gcal", "personal_a.ics"), empty))
    svc.run_sync("gcal", "startup")
    svc.run_sync("gcal", "schedule")
    assert titles(factory, "gcal") == []
    assert state_of(factory, "gcal").status == "ok"


def test_all_day_and_timed_events_are_stored_in_their_own_shape(factory):
    svc = service(factory, FakeClock(), calendar=Script(body("gcal", "personal_a.ics")))
    svc.run_sync("gcal", "startup")
    with factory() as session:
        rows = {r.title: r for r in session.scalars(select(ExternalEvent))}
    course, review = rows["Trading course"], rows["Asia session review"]
    assert (course.all_day, course.start_at, str(course.start_date), str(course.end_date)) == (True, None, "2044-05-18", "2044-05-21")
    assert (review.all_day, review.start_date, review.end_at - review.start_at) == (False, None, timedelta(hours=4))


# --- failures never lose events -------------------------------------------------------------------------------------------


def test_a_failed_fetch_leaves_every_stored_event_as_it_was(factory, caplog):
    clock = FakeClock()
    feed = Script(body("forexfactory", "week_a.xml"), Throttled("HTTP 429: the host is rate limiting requests", http_status=429))
    svc = service(factory, clock, news=feed)
    svc.run_sync("forexfactory", "startup")
    before = titles(factory, "forexfactory")
    clock.advance(hours=1)
    assert svc.run_sync("forexfactory", "schedule") == "throttled"

    assert titles(factory, "forexfactory") == before
    state = state_of(factory, "forexfactory")
    assert (state.status, state.http_status, state.consecutive_failures, state.state) == ("throttled", 429, 1, "idle")
    assert state.message == "HTTP 429: the host is rate limiting requests"
    assert state.last_success_at == NOW  # the earlier success is still the last one
    record = feed_records(caplog)[-1]
    assert (record.outcome, record.levelno, record.backoff_minutes) == ("throttled", logging.WARNING, 15)


def test_the_backoff_is_15_30_60_then_120_minutes_and_a_success_resets_it(factory):
    clock = FakeClock()
    feed = Script(*[FetchFailed("HTTP 503", http_status=503)] * 6, body("forexfactory", "week_a.json"))
    svc = service(factory, clock, news=feed)
    waits = []
    for _ in range(6):
        svc.run_sync("forexfactory", "schedule")
        state = state_of(factory, "forexfactory")
        waits.append(state.next_due_at - clock.now())
        clock.advance(hours=3)
    assert [w // timedelta(minutes=1) for w in waits] == [15, 30, 60, 120, 120, 120]
    assert BACKOFF_MINUTES == (15, 30, 60, 120)
    svc.run_sync("forexfactory", "schedule")
    state = state_of(factory, "forexfactory")
    assert (state.status, state.consecutive_failures, state.message) == ("ok", 0, None)
    assert state.next_due_at == clock.now() + timedelta(minutes=60)  # back to the normal schedule


@pytest.mark.parametrize(
    ("error", "status"),
    [(Throttled("rate limited"), "throttled"), (BadContent("not a feed"), "bad_content"), (FetchFailed("timed out"), "error")],
)
def test_each_kind_of_trouble_has_its_own_status(factory, error, status):
    svc = service(factory, FakeClock(), news=Script(error))
    assert svc.run_sync("forexfactory", "startup") == status
    assert state_of(factory, "forexfactory").status == status


def test_a_feed_the_parser_rejects_is_bad_content_and_keeps_the_events(factory):
    svc = service(factory, FakeClock(), news=Script(body("forexfactory", "week_a.json"), FetchResult(body=b"<html>maintenance</html>")))
    svc.run_sync("forexfactory", "startup")
    assert svc.run_sync("forexfactory", "schedule") == "bad_content"
    assert len(titles(factory, "forexfactory")) == 108
    assert state_of(factory, "forexfactory").message == "the feed is HTML, not JSON or XML"


def test_a_bug_in_a_parser_is_an_error_not_a_dead_worker(factory, caplog):
    def explode(body, now):
        raise RuntimeError("parser bug")

    source = news_source(Script(FetchResult(body=b"[]")))
    svc = FeedService(factory, settings(), FakeClock(), {"forexfactory": source.__class__(**{**source.__dict__, "parse": explode})})
    assert svc.run_sync("forexfactory", "startup") == "error"
    state = state_of(factory, "forexfactory")
    assert (state.state, state.status) == ("idle", "error")
    assert "internal error" in state.message
    assert any(r.getMessage() == "feed_sync_crashed" and r.levelno == logging.ERROR for r in caplog.records)


def test_a_failure_while_storing_rolls_back_and_marks_the_feed_failed(factory, monkeypatch, caplog):
    svc = service(factory, FakeClock(), news=Script(body("forexfactory", "week_a.json")))

    def broken(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(feeds_module, "reconcile", broken)
    assert svc.run_sync("forexfactory", "startup") == "error"
    assert titles(factory, "forexfactory") == []
    state = state_of(factory, "forexfactory")
    assert (state.state, state.status, state.consecutive_failures) == ("idle", "error", 1)
    assert state.message == "the events could not be stored; see the server log"


# --- manual syncs, the schedule and restarts ---------------------------------------------------------------------------


def test_a_manual_sync_is_queued_then_refused_until_the_cooldown_ends(factory):
    clock = FakeClock()
    svc = service(factory, clock, news=Script(body("forexfactory", "week_a.json")), calendar=Script(body("gcal", "personal_a.ics")))
    with factory() as session:
        first = svc.request_sync(session, [])
    assert [(r.source, r.outcome) for r in first] == [("forexfactory", "queued"), ("gcal", "queued")]
    assert state_of(factory, "forexfactory").state == "queued"
    assert state_of(factory, "forexfactory").next_manual_at == NOW + timedelta(seconds=300)

    with factory() as session:
        again = svc.request_sync(session, ["forexfactory"])
    assert [(r.outcome, r.retry_after_seconds) for r in again] == [("running", None)]  # already queued

    assert svc.next_work("forexfactory") == ("manual", 0.0)
    svc.run_sync("forexfactory", "manual")
    clock.advance(seconds=100)
    with factory() as session:
        cooling = svc.request_sync(session, ["forexfactory"])
    assert [(r.outcome, r.retry_after_seconds) for r in cooling] == [("cooldown", 200)]
    clock.advance(seconds=201)
    with factory() as session:
        later = svc.request_sync(session, ["forexfactory"])
    assert [r.outcome for r in later] == ["queued"]


def test_a_disabled_source_cannot_be_synced(factory):
    source = news_source(Script(body("forexfactory", "week_a.json")))
    off = source.__class__(**{**source.__dict__, "enabled": False, "disabled_reason": "feeds are off (FEEDS_MODE=off)"})
    svc = FeedService(factory, settings(), FakeClock(), {"forexfactory": off})
    with factory() as session:
        results = svc.request_sync(session, [])
        status = svc.status(session)
    assert [(r.outcome) for r in results] == ["disabled"]
    assert (status[0].enabled, status[0].disabled_reason, status[0].status, status[0].next_due_at) == (False, "feeds are off (FEEDS_MODE=off)", "never", None)
    assert state_of(factory, "forexfactory") is None


def test_the_schedule_says_when_there_is_work(factory):
    clock = FakeClock()
    svc = service(factory, clock, news=Script(body("forexfactory", "week_a.json")))
    svc.prepare()
    assert svc.next_work("forexfactory") == ("startup", 0.0)  # a new feed is fetched straight away
    svc.run_sync("forexfactory", "startup")
    trigger, wait = svc.next_work("forexfactory")
    assert trigger is None and wait == 3600.0
    clock.advance(minutes=61)
    assert svc.next_work("forexfactory") == ("schedule", 0.0)


def test_a_restart_does_not_refetch_early(factory):
    clock = FakeClock()
    feed = Script(body("forexfactory", "week_a.json"))
    service(factory, clock, news=feed).run_sync("forexfactory", "startup")

    clock.advance(minutes=5)  # the process restarts five minutes later: a new service on the same database
    restarted = service(factory, clock, news=feed)
    restarted.prepare()
    trigger, wait = restarted.next_work("forexfactory")
    assert trigger is None and wait == 55 * 60.0
    assert len(feed.calls) == 1


def test_prepare_clears_a_running_mark_left_by_a_crash(factory):
    clock = FakeClock()
    svc = service(factory, clock, news=Script(body("forexfactory", "week_a.json")))
    svc.prepare()
    with factory() as session:
        state = FeedStateRepository(session).get("forexfactory")
        state.state = "running"
        state.next_due_at = NOW + timedelta(hours=1)
        session.commit()
    svc.prepare()
    state = state_of(factory, "forexfactory")
    assert (state.state, state.next_due_at) == ("idle", NOW)  # due now: the interrupted sync is simply done again


def test_status_reports_counts_and_never_an_address(factory):
    secret = "https://calendar.example.test/ical/me/private-0123456789abcdef0123456789abcdef/basic.ics"
    svc = service(factory, FakeClock(), news=Script(body("forexfactory", "week_a.json")), calendar=Script(FetchFailed("HTTP 404", http_status=404)), gcal_ical_url=secret)
    svc.run_sync("forexfactory", "startup")
    svc.run_sync("gcal", "startup")
    with factory() as session:
        news, calendar = svc.status(session)
    assert (news.source, news.event_count, news.status, news.poll_minutes) == ("forexfactory", 108, "ok", 60)
    assert (calendar.status, calendar.message, calendar.http_status, calendar.event_count) == ("error", "HTTP 404", 404, 0)
    dumped = news.model_dump_json() + calendar.model_dump_json()
    assert "private-" not in dumped and "calendar.example.test" not in dumped


def test_every_status_the_service_writes_is_one_the_database_allows(factory):
    """The CHECK constraints would reject anything else; this fails loudly if a new outcome is added without a migration."""
    for answer, expected in ((Throttled("t"), "throttled"), (BadContent("b"), "bad_content"), (FetchFailed("f"), "error"), (body("forexfactory", "week_a.json"), "ok")):
        svc = service(factory, FakeClock(), news=Script(answer))
        assert svc.run_sync("forexfactory", "schedule") == expected
    assert isinstance(FeedError("x").status, str)
