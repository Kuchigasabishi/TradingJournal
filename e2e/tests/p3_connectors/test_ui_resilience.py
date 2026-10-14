"""Phase 3: the events and the feed status can fail without taking the calendar with them.

Like the Phase 2 resilience tests, the failures are made from the browser: Playwright answers or holds the app's own requests, so
the app meets an events request that fails or is slow, a feed status that fails, and feeds that are switched off, on demand.
"""
import re

import pytest
from playwright.sync_api import Page, expect

from support.ui import open_app

pytestmark = pytest.mark.usefixtures("leave_the_app_before_cleanup")

EVENTS = re.compile(r"/api/events\?")
STATUS = re.compile(r"/api/sources/status$")
OFF = "feeds are off (FEEDS_MODE=off)"
NO_ADDRESS = "no calendar address is configured (GCAL_ICAL_URL)"


def off_row(source: str, label: str, reason: str) -> dict:
    """A feed that is switched off, as the API reports one."""
    return {
        "source": source, "label": label, "enabled": False, "disabled_reason": reason, "state": "idle", "status": "never", "message": None,
        "http_status": None, "last_attempt_at": None, "last_success_at": None, "next_due_at": None, "next_manual_at": None,
        "consecutive_failures": 0, "event_count": 0, "poll_minutes": 60,
    }


@pytest.mark.allow_console_errors(r"status of 500", r"^HTTP 500", reason="the test makes the events request fail")
def test_when_the_events_cannot_be_loaded_the_calendar_still_shows_the_month(page: Page, shot):
    page.route(EVENTS, lambda route: route.fulfill(status=500, json={"detail": "Events failed."}))
    open_app(page, "/calendar?month=2044-05")
    expect(page.get_by_test_id("calendar-grid")).to_be_visible()
    expect(page.get_by_test_id("calendar-events-error")).to_have_text("Events could not be loaded, so news and calendar events are not shown.")
    expect(page.locator("[data-testid^='news-badge-']")).to_have_count(0)
    expect(page.get_by_test_id("event-filters")).to_have_count(0)  # nothing to narrow
    expect(page.get_by_test_id("sources-card")).to_be_visible()  # and the feeds are still there to look at
    shot("01-events-failed")


@pytest.mark.allow_console_errors(r"status of 500", r"^HTTP 500", reason="the test makes the events request fail")
def test_a_day_whose_events_fail_says_so_and_retry_brings_them(page: Page):
    page.route(EVENTS, lambda route: route.fulfill(status=500, json={"detail": "Events failed."}))
    open_app(page, "/day/2044-05-12")
    expect(page.get_by_test_id("day-events-error")).to_contain_text("Could not load the events")
    expect(page.get_by_test_id("day-trades")).to_be_visible()  # the rest of the day is unaffected
    page.unroute(EVENTS)
    page.get_by_test_id("day-events-retry").click()
    expect(page.get_by_test_id("day-events-news-heading")).to_have_text("Economic news · 35")
    expect(page.get_by_test_id("day-events-error")).to_have_count(0)


def test_a_slow_events_request_shows_a_loading_state_until_it_arrives(page: Page):
    held = []
    page.route(EVENTS, lambda route: held.append(route))
    open_app(page, "/day/2044-05-12")
    expect(page.get_by_test_id("day-events-loading")).to_be_visible()
    expect(page.get_by_test_id("day-trades")).to_be_visible()
    for route in held:
        route.continue_()
    expect(page.get_by_test_id("day-events-news-heading")).to_have_text("Economic news · 35")
    expect(page.get_by_test_id("day-events-loading")).to_have_count(0)


@pytest.mark.allow_console_errors(r"status of 500", r"^HTTP 500", reason="the test makes the feed status request fail")
def test_a_failing_feed_status_does_not_hide_the_calendar_and_retry_recovers(page: Page):
    page.route(STATUS, lambda route: route.fulfill(status=500, json={"detail": "Status failed."}))
    open_app(page, "/calendar?month=2044-05")
    expect(page.get_by_test_id("sources-error")).to_contain_text("Could not load the feeds")
    expect(page.get_by_test_id("sync-now")).to_be_disabled()  # nothing is known about the feeds, so nothing to ask for
    expect(page.get_by_test_id("news-count-2044-05-12-high")).to_have_text("7")  # the events do not depend on it
    page.unroute(STATUS)
    page.get_by_test_id("sources-retry").click()
    expect(page.get_by_test_id("source-status-forexfactory")).to_have_text("Up to date")
    expect(page.get_by_test_id("sync-now")).to_be_enabled()


def test_feeds_that_are_switched_off_say_why_and_cannot_be_synced(page: Page, shot):
    rows = [off_row("forexfactory", "Economic news (ForexFactory)", OFF), off_row("gcal", "Google Calendar", OFF)]
    page.route(STATUS, lambda route: route.fulfill(status=200, json=rows))
    open_app(page, "/calendar?month=2044-05")
    for name in ("forexfactory", "gcal"):
        expect(page.get_by_test_id(f"source-status-{name}")).to_have_text("Off")
        expect(page.get_by_test_id(f"source-off-{name}")).to_have_text(OFF)
        expect(page.get_by_test_id(f"source-last-{name}")).to_have_count(0)  # it never ran, so there is nothing to report
    expect(page.get_by_test_id("sync-now")).to_be_disabled()
    shot("01-feeds-off")


def test_a_calendar_without_an_address_is_off_while_the_news_carries_on(page: Page, feeds):
    news = feeds.status()["forexfactory"]  # the real row, as the server reported it
    page.route(STATUS, lambda route: route.fulfill(status=200, json=[news, off_row("gcal", "Google Calendar", NO_ADDRESS)]))
    open_app(page, "/calendar?month=2044-05")
    expect(page.get_by_test_id("source-status-forexfactory")).to_have_text("Up to date")
    expect(page.get_by_test_id("source-status-gcal")).to_have_text("Off")
    expect(page.get_by_test_id("source-off-gcal")).to_have_text(NO_ADDRESS)
    expect(page.get_by_test_id("sync-now")).to_be_enabled()  # one feed can still be asked
