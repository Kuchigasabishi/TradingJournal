"""Phase 3: the Sources card under the calendar, and syncing from the screen.

"Sync now" asks the server to refresh its feeds and gets its answer at once; the fetch runs on the server's own time, so the
card follows the feed status until the feeds are done and the grid reloads its events by itself. The hosts are the local stub
(fixtures/), scripted to fail the ways real hosts fail.
"""
import re

import pytest
from playwright.sync_api import Page, expect

from support.events_ui import expect_grid
from support.feeds import assert_no_secret, calendar_events, ff_week, month_days
from support.ui import expect_api, open_app

pytestmark = pytest.mark.usefixtures("leave_the_app_before_cleanup")

MONTH = "2044-05"
DAYS = month_days(MONTH)
NEWS_A = list(ff_week("week_a").values())
# Week B no longer lists MPC Member Mann, whose speech is in the past, and the app keeps the past (test_news_reconcile.py).
NEWS_B = list(ff_week("week_b").values()) + [e for e in NEWS_A if e["title"] == "MPC Member Mann Speaks"]
PERSONAL_A = list(calendar_events("a").values())
PERSONAL_B = list(calendar_events("b").values())
SOURCES = [("forexfactory", "Economic news (ForexFactory)", 108), ("gcal", "Google Calendar", 70)]


def press_sync(page: Page, feeds) -> None:
    feeds.cool_down()
    page.get_by_test_id("sync-now").click()
    feeds.mark_requested()
    page.mouse.move(0, 0)  # park the pointer: wherever it was left would show a tooltip in the screenshots


def test_the_card_shows_both_feeds_and_never_an_address(page: Page, shot):
    open_app(page, f"/calendar?month={MONTH}")
    for name, label, events in SOURCES:
        expect(page.get_by_test_id(f"source-{name}")).to_contain_text(label)
        expect(page.get_by_test_id(f"source-status-{name}")).to_have_text("Up to date")
        expect(page.get_by_test_id(f"source-count-{name}")).to_have_text(f"{events} events")
        expect(page.get_by_test_id(f"source-last-{name}")).to_have_text(re.compile(r"^Last synced 2044-05-1[12] \d\d:\d\d · next automatic sync 2044-05-1[12] \d\d:\d\d$"))
        expect(page.get_by_test_id(f"source-message-{name}")).to_have_count(0)
    assert_no_secret(page.content(), "the calendar page")  # the page that shows the feeds never contains where they are
    shot("01-sources")


def test_pressing_sync_now_runs_in_the_background_and_says_when_it_is_done(page: Page, feeds, shot):
    feeds.wait_idle()
    feeds.cool_down()
    open_app(page, f"/calendar?month={MONTH}")
    with expect_api(page, "POST", r"^/api/sync$") as call:
        page.get_by_test_id("sync-now").click()
    feeds.mark_requested()
    page.mouse.move(0, 0)
    assert call.status == 202 and call.request_id.startswith("web-")
    assert call.json() == {
        "sources": [
            {"source": "forexfactory", "outcome": "queued", "retry_after_seconds": None},
            {"source": "gcal", "outcome": "queued", "retry_after_seconds": None},
        ]
    }
    expect(page.get_by_test_id("sync-message")).to_have_text("Sync finished.")
    expect(page.get_by_test_id("sync-now")).to_be_enabled()
    for feed in ("forexfactory", "gcal"):
        asked = feeds.stub.requests(feed)[-1]  # each host was asked again, and answered "nothing new"
        assert asked["conditional"] is True and asked["status"] == 304, feed
    shot("01-synced")


@pytest.mark.allow_console_errors(r"status of 429", reason="the test presses Sync now twice inside the server's cooldown")
def test_pressing_again_inside_the_cooldown_is_refused_politely(page: Page, feeds):
    feeds.wait_idle()
    feeds.cool_down()
    open_app(page, f"/calendar?month={MONTH}")
    button = page.get_by_test_id("sync-now")
    with expect_api(page, "POST", r"^/api/sync$") as first:
        button.click()
    feeds.mark_requested()
    assert first.status == 202
    expect(page.get_by_test_id("sync-message")).to_have_text("Sync finished.")

    with expect_api(page, "POST", r"^/api/sync$") as second:
        button.click()
    assert second.status == 429 and second.response.headers["retry-after"] in ("1", "2")
    message = page.get_by_test_id("sync-message")
    expect(message).to_have_text(re.compile(r"^That was synced a moment ago\. You can sync again in [12] s\.$"))
    expect(button).to_be_disabled()  # no point pressing it until the wait is over
    expect(message).to_have_count(0, timeout=6_000)  # and it clears itself when it is
    expect(button).to_be_enabled()


def test_a_sync_changes_the_grid_without_reloading_the_page(page: Page, feeds, shot):
    open_app(page, f"/calendar?month={MONTH}")
    expect_grid(page, NEWS_A, PERSONAL_A, DAYS)
    page.evaluate("window.__sameLoad = true")  # gone if the page reloads

    feeds.script(ff={"variant": "b"}, gcal={"variant": "b"})  # the later week, and the calendar a little later
    press_sync(page, feeds)
    expect(page.get_by_test_id("sync-message")).to_have_text("Sync finished.")
    expect_grid(page, NEWS_B, PERSONAL_B, DAYS)
    assert page.evaluate("window.__sameLoad") is True
    expect(page.get_by_test_id("personal-title-2044-05-18")).to_have_text("Trading course (advanced)")  # renamed in the calendar
    shot("01-after-the-later-week")


FAILURES = [
    # feed, how the host fails, the standing shown, the reason the server gave, how many events the feed keeps
    ("gcal", {"gcal": {"mode": "http_404"}}, "Failed", "HTTP 404", 70),
    ("forexfactory", {"ff": {"mode": "http_429"}}, "Rate limited", "HTTP 429: the host is rate limiting requests", 108),
    ("forexfactory", {"ff": {"mode": "html"}}, "Unusable answer", "the feed is HTML, not JSON or XML", 108),
]


@pytest.mark.parametrize("feed, script, standing, reason, kept", FAILURES, ids=[f"{feed}-{next(iter(script.values()))['mode']}" for feed, script, *_ in FAILURES])
def test_a_failing_feed_says_why_keeps_its_events_and_recovers(page: Page, feeds, shot, feed, script, standing, reason, kept):
    other = "gcal" if feed == "forexfactory" else "forexfactory"
    open_app(page, f"/calendar?month={MONTH}")
    expect(page.get_by_test_id(f"source-status-{feed}")).to_have_text("Up to date")

    feeds.script(**script)
    press_sync(page, feeds)
    expect(page.get_by_test_id("sync-message")).to_have_text("Sync finished.")
    expect(page.get_by_test_id(f"source-status-{feed}")).to_have_text(standing)
    message = page.get_by_test_id(f"source-message-{feed}")
    expect(message).to_contain_text(f"Last attempt failed: {reason}.")
    expect(message).to_contain_text(f"The {kept} events already stored are kept.")
    expect(message).to_have_text(re.compile(r"Trying again 2044-05-11 \d\d:\d\d\.$"))  # the next attempt: the first step of the backoff
    expect(page.get_by_test_id(f"source-status-{other}")).to_have_text("Up to date")  # the other feed does not care
    expect(page.get_by_test_id(f"source-message-{other}")).to_have_count(0)
    # nothing was lost: the grid still shows what it showed
    expect(page.get_by_test_id("news-count-2044-05-12-high")).to_have_text("7")
    expect(page.get_by_test_id("personal-title-2044-05-12")).to_have_text("Bank day off")
    shot("01-failed")

    feeds.stub.script(**{key: {"mode": "ok"} for key in script})  # the host comes back
    press_sync(page, feeds)
    expect(page.get_by_test_id(f"source-status-{feed}")).to_have_text("Up to date")
    expect(page.get_by_test_id(f"source-message-{feed}")).to_have_count(0)
    assert_no_secret(page.content(), "the calendar page after a failure")


def test_a_slow_host_shows_as_syncing_and_then_failed_while_the_other_carries_on(page: Page, feeds, shot):
    open_app(page, f"/calendar?month={MONTH}")
    feeds.script(ff={"mode": "slow"})  # sits on the request for longer than the app is willing to wait
    press_sync(page, feeds)
    status = page.get_by_test_id("source-status-forexfactory")
    expect(status).to_have_text("Syncing…")
    expect(page.get_by_test_id("sync-now")).to_be_disabled()
    expect(page.get_by_test_id("sync-now")).to_have_text("Working…")
    expect(page.get_by_test_id("source-status-gcal")).to_have_text("Up to date")  # its own worker is not held up
    expect(page.get_by_test_id("calendar-grid")).to_be_visible()  # and neither is the screen
    shot("01-syncing")

    expect(status).to_have_text("Failed", timeout=10_000)
    expect(page.get_by_test_id("source-message-forexfactory")).to_contain_text("Last attempt failed: timed out waiting for the host.")
    expect(page.get_by_test_id("sync-message")).to_have_text("Sync finished.")
    expect(page.get_by_test_id("sync-now")).to_be_enabled()
