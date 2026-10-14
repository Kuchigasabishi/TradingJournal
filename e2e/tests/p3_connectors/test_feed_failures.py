"""Phase 3: when a host misbehaves the app says what happened, in a short fixed phrase, and keeps every event it had.

Each case scripts the stub to fail in one way (the same ways a real host does: over-limit pages, errors, maintenance
pages, truncated downloads), syncs that feed, and checks the status the owner would see. The messages are fixed phrases on
purpose: the exceptions of an HTTP library carry the full address, and the calendar address is a secret.
"""
import json
from datetime import timedelta

import pytest

from support.feeds import assert_no_secret, when

FEED_KEY = {"forexfactory": "ff", "gcal": "gcal"}
THROTTLE_429 = "HTTP 429: the host is rate limiting requests"

CASES = [
    # feed, what the stub does, status, HTTP status, message
    ("forexfactory", "http_429", "throttled", 429, THROTTLE_429),
    ("forexfactory", "denied_403", "throttled", 403, "HTTP 403: the host refused the request as over its limit"),
    ("forexfactory", "denied_html", "throttled", None, "the host answered with its request-denied page"),
    ("forexfactory", "http_500", "error", 500, "HTTP 500"),
    ("forexfactory", "http_503", "error", 503, "HTTP 503"),
    ("forexfactory", "http_404", "error", 404, "HTTP 404"),
    ("forexfactory", "html", "bad_content", None, "the feed is HTML, not JSON or XML"),
    ("forexfactory", "malformed", "bad_content", None, "the feed is not valid XML"),
    ("forexfactory", "empty", "bad_content", None, "the feed held no events"),
    ("gcal", "http_404", "error", 404, "HTTP 404"),  # what Google answers for an address that was reset
    ("gcal", "http_429", "throttled", 429, THROTTLE_429),
    ("gcal", "http_503", "error", 503, "HTTP 503"),
    ("gcal", "html", "bad_content", None, "the address returned a web page or other data, not a calendar"),  # Google's sign-in page
    ("gcal", "malformed", "bad_content", None, "the calendar is cut off: it does not end with END:VCALENDAR"),
]


@pytest.mark.parametrize("feed, mode, status, http_status, message", CASES, ids=[f"{feed}-{mode}" for feed, mode, *_ in CASES])
def test_a_failed_sync_is_reported_and_loses_nothing(feeds, feed, mode, status, http_status, message):
    other = "gcal" if feed == "forexfactory" else "forexfactory"
    events, others = feeds.all_events(feed), feeds.all_events(other)
    before = feeds.status()

    feeds.script(**{FEED_KEY[feed]: {"mode": mode}})
    after = feeds.sync(feed)
    row = after[feed]

    assert (row["status"], row["http_status"], row["message"]) == (status, http_status, message)
    assert (row["state"], row["consecutive_failures"]) == ("idle", 1)
    assert row["last_success_at"] == before[feed]["last_success_at"]  # nothing succeeded
    wait = when(row["next_due_at"]) - when(row["last_attempt_at"])
    assert timedelta(minutes=15) <= wait <= timedelta(minutes=15, seconds=10)  # the first step of the backoff
    assert feeds.stub.requests(feed)[-1]["mode"] == mode  # the app really asked, and got this answer

    assert feeds.all_events(feed) == events  # every event, untouched
    assert row["event_count"] == len(events)
    assert after[other]["status"] == "ok" and feeds.all_events(other) == others  # the other feed does not care
    assert_no_secret(json.dumps(after), "the status after a failed sync")


def test_repeated_failures_back_off_15_30_60_then_120_minutes_and_one_success_ends_it(feeds):
    feeds.script(ff={"mode": "http_500"})
    for count, minutes in enumerate([15, 30, 60, 120, 120], start=1):
        row = feeds.sync("forexfactory")["forexfactory"]
        assert (row["status"], row["consecutive_failures"]) == ("error", count)
        wait = when(row["next_due_at"]) - when(row["last_attempt_at"])
        assert timedelta(minutes=minutes) <= wait <= timedelta(minutes=minutes, seconds=10), count

    feeds.stub.script(ff={"mode": "ok"})
    row = feeds.sync("forexfactory")["forexfactory"]
    assert (row["status"], row["message"], row["consecutive_failures"]) == ("ok", None, 0)
    assert row["http_status"] in (200, 304)  # the host may say "unchanged": the events never changed
    assert when(row["next_due_at"]) - when(row["last_success_at"]) == timedelta(minutes=row["poll_minutes"])  # back on the normal schedule


def test_a_failure_does_not_stop_the_next_good_answer_from_being_applied(feeds):
    feeds.script(ff={"mode": "http_503"})
    feeds.sync("forexfactory")
    feeds.stub.script(ff={"mode": "ok", "variant": "b"})
    row = feeds.sync("forexfactory")["forexfactory"]
    titles = {event["title"] for event in feeds.all_events("forexfactory")}
    assert row["status"] == "ok" and "Cash Rate" in titles  # week B arrived, straight after the outage
