"""Phase 3: the feeds survive a server restart.

scripts/verify.py runs this module in the second pass, after it has stopped the app and started it again on the same
database. The schedule of each feed (when it last synced, when it is next due) and the validators of its last answer
live in the database, so a restart neither refetches early (the hosts are asked politely) nor forgets what it had.
"""
from datetime import timedelta

import pytest

from support.feeds import SOURCES, calendar_events, calendar_key, calendar_view, env, ff_week, news_key, news_view, when


@pytest.mark.after_restart
def test_a_restart_neither_refetches_early_nor_forgets_the_events(feeds):
    restarted = when(env("SERVER_RESTARTED_AT"))
    asked_since = [(r["feed"], r["status"]) for r in feeds.stub.requests() if when(r["ts"]) >= restarted]
    assert asked_since == [], "the restarted app asked a feed for its events although both were fresh"

    status = feeds.status()
    for name in SOURCES:
        row = status[name]
        assert (row["state"], row["status"], row["consecutive_failures"]) == ("idle", "ok", 0), name
        assert when(row["next_due_at"]) - when(row["last_success_at"]) == timedelta(minutes=row["poll_minutes"]), name  # the schedule came back as it was

    news = {news_key(event): event for event in feeds.all_events("forexfactory")}
    assert {key: news_view(event) for key, event in news.items()} == ff_week("week_a")
    calendar = {calendar_key(event): event for event in feeds.all_events("gcal")}
    assert {key: calendar_view(event) for key, event in calendar.items()} == calendar_events("a")


@pytest.mark.after_restart
def test_the_validators_of_the_last_answer_survived_too(feeds):
    feeds.sync()
    for name in SOURCES:
        request = feeds.stub.requests(name)[-1]
        assert request["conditional"] is True and request["status"] == 304, name  # the app still holds the ETag it was given before the restart
    assert all(row["http_status"] == 304 and row["status"] == "ok" for row in feeds.status().values())
