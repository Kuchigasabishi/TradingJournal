"""Phase 2: bad networks and slow servers, simulated by answering or holding the app's requests from the test.

Nothing here touches the real server's behaviour: Playwright intercepts the browser's requests, so the app
meets a dead network, a failing server or a slow one on demand, and the test checks what a person would see.
"""
import re

import pytest
from playwright.sync_api import Page, expect

from support.ui import open_app

API = re.compile(r"/api/")


@pytest.mark.allow_console_errors(r"net::ERR_FAILED", reason="the test cuts the network to see the offline screen")
def test_when_the_api_is_unreachable_the_app_says_so_and_retry_recovers(page: Page, shot):
    page.route(API, lambda route: route.abort())
    page.goto("/")
    error = page.get_by_test_id("boot-error")
    expect(error).to_contain_text("Cannot reach the journal server")
    expect(error).to_contain_text("Start the API server, then retry.")
    expect(page.get_by_test_id("app-shell")).to_have_count(0)
    shot("01-offline")

    page.unroute(API)
    page.get_by_test_id("boot-retry").click()
    expect(page.get_by_test_id("app-ready")).to_be_visible()
    expect(page.get_by_test_id("api-status-label")).to_have_text("API online")
    shot("02-back-online")


@pytest.mark.allow_console_errors(r"status of 503", r"^HTTP 503", reason="the test makes the server report that it is not ready")
def test_a_server_that_is_up_but_not_ready_gets_its_own_message(page: Page, shot):
    page.route(re.compile(r"/api/ready$"), lambda route: route.fulfill(status=503, json={"detail": "migrations pending"}))
    page.goto("/")
    expect(page.get_by_test_id("boot-error")).to_contain_text("The server is up but not ready. Check its logs.")
    shot("01-not-ready")


@pytest.mark.allow_console_errors(r"net::ERR_FAILED", reason="the test cuts the health check")
def test_the_status_chip_follows_the_apis_health(page: Page, shot):
    open_app(page, "/")
    label = page.get_by_test_id("api-status-label")
    expect(label).to_have_text("API online")

    page.route(re.compile(r"/api/health$"), lambda route: route.abort())
    page.get_by_test_id("api-status").click()  # pressing the chip checks right now
    expect(label).to_have_text("API offline")
    shot("01-chip-offline")

    page.unroute(re.compile(r"/api/health$"))
    page.get_by_test_id("api-status").click()
    expect(label).to_have_text("API online")


def test_a_slow_list_shows_a_loading_state_until_it_arrives(page: Page, journal, shot):
    trade = journal.trade()
    held = []
    page.route(re.compile(r"/api/trades\?"), lambda route: held.append(route))
    open_app(page, f"/trades?instrument={trade['instrument']}")
    expect(page.get_by_test_id("trades-loading")).to_be_visible()
    expect(page.get_by_test_id("trades-table")).to_have_count(0)
    shot("01-loading")

    assert len(held) >= 1
    for route in held:
        route.continue_()
    expect(page.get_by_test_id(f"trade-row-{trade['id']}")).to_be_visible()
    expect(page.get_by_test_id("trades-loading")).to_have_count(0)


@pytest.mark.allow_console_errors(r"net::ERR_FAILED", reason="the test drops the network in the middle of a session")
def test_losing_the_network_mid_session_offers_a_retry_that_works(page: Page, journal, shot):
    trade = journal.trade()
    open_app(page, f"/trades?instrument={trade['instrument']}")
    expect(page.get_by_test_id(f"trade-row-{trade['id']}")).to_be_visible()

    page.route(re.compile(r"/api/trades\?"), lambda route: route.abort())
    page.get_by_test_id("filter-side-short").click()  # a new query that is not cached, so it needs the network
    # The app retries a dropped connection once by itself, then gives up and says so.
    error = page.get_by_test_id("trades-error")
    expect(error).to_contain_text("Could not load trades", timeout=15_000)
    expect(error).to_contain_text("Cannot reach the server.")
    shot("01-network-lost")

    page.unroute(re.compile(r"/api/trades\?"))
    page.get_by_test_id("trades-retry").click()
    expect(page.get_by_test_id("trades-empty")).to_contain_text("No trades match these filters")  # a long trade, filtered to short
    expect(error).to_have_count(0)


@pytest.mark.allow_console_errors(r"status of 500", r"^HTTP 500", reason="the test makes the calendar request fail")
def test_the_calendar_reports_a_failed_month_and_recovers(page: Page, shot):
    page.route(re.compile(r"/api/calendar/month"), lambda route: route.fulfill(status=500, json={"detail": "Month failed."}))
    open_app(page, "/calendar?month=2038-08")
    expect(page.get_by_test_id("calendar-error")).to_contain_text("Month failed.")
    shot("01-calendar-error")
    page.unroute(re.compile(r"/api/calendar/month"))
    page.get_by_test_id("calendar-retry").click()
    expect(page.get_by_test_id("calendar-grid")).to_be_visible()


@pytest.mark.allow_console_errors(r"status of 500", r"^HTTP 500", reason="the test makes the notes request fail")
def test_a_failed_notes_request_degrades_the_calendar_gracefully(page: Page, shot):
    """Notes are decoration on the calendar: when they fail the grid still shows, and says what is missing."""
    page.route(re.compile(r"/api/notes\?"), lambda route: route.fulfill(status=500, json={"detail": "Notes failed."}))
    open_app(page, "/calendar?month=2038-08")
    expect(page.get_by_test_id("calendar-grid")).to_be_visible()
    expect(page.get_by_test_id("calendar-notes-error")).to_contain_text("days with notes are not marked")
    shot("01-calendar-without-notes")
