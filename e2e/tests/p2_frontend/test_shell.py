"""Phase 2: the Expo web app boots, shows the API's state, and moves between screens without reloading."""
import re

import pytest
from playwright.sync_api import Page, expect

from support.ui import open_app


def test_the_app_boots_and_reports_the_api_online(page: Page, shot):
    open_app(page, "/")
    expect(page).to_have_title("Dashboard · Trading Journal")
    expect(page.get_by_test_id("api-status-label")).to_have_text("API online")
    expect(page.get_by_test_id("nav-dashboard")).to_have_attribute("aria-current", "page")
    shot("01-first-load")


def test_navigation_moves_between_the_screens_without_a_reload(page: Page, shot):
    open_app(page, "/")
    page.evaluate("window.__spa_marker = 'same document'")  # a full page load would wipe this

    page.get_by_test_id("nav-calendar").click()
    expect(page).to_have_url(re.compile(r"/calendar$"))
    expect(page.get_by_test_id("page-title")).to_have_text("Calendar")
    expect(page).to_have_title("Calendar · Trading Journal")
    expect(page.get_by_test_id("nav-calendar")).to_have_attribute("aria-current", "page")
    shot("02-calendar")

    page.get_by_test_id("nav-trades").click()
    expect(page).to_have_url(re.compile(r"/trades$"))
    expect(page.get_by_test_id("page-title")).to_have_text("Trades")
    shot("03-trades")

    page.get_by_test_id("nav-new-trade").click()
    expect(page).to_have_url(re.compile(r"/trades/new$"))
    expect(page.get_by_test_id("page-title")).to_have_text("New trade")

    page.get_by_test_id("nav-brand").click()
    expect(page).to_have_url(re.compile(r"/$"))
    expect(page.get_by_test_id("page-title")).to_have_text("Dashboard")

    assert page.evaluate("window.__spa_marker") == "same document"


@pytest.mark.parametrize("path", ["/calendar", "/trades?status=open", "/trades/new", "/day/2037-04-06"])
def test_a_deep_link_loads_directly(page: Page, path: str):
    """The server falls back to index.html for any route the app owns, so a reload or a shared link works."""
    open_app(page, path)
    expect(page.get_by_test_id("page-title")).to_be_visible()


def test_an_unknown_address_shows_the_not_found_page(page: Page, shot):
    open_app(page, "/this/does/not/exist")
    expect(page.get_by_test_id("not-found-page")).to_be_visible()
    expect(page).to_have_title("Page not found · Trading Journal")
    shot("01-not-found")
    page.get_by_test_id("not-found-link").click()
    expect(page.get_by_test_id("page-title")).to_have_text("Dashboard")


@pytest.mark.allow_console_errors(r"status of 404", reason="the test asks for a trade that does not exist")
def test_a_missing_trade_says_so_instead_of_failing(page: Page, shot):
    open_app(page, "/trades/987654321")
    expect(page.get_by_test_id("not-found")).to_contain_text("Trade not found")
    shot("01-missing-trade")
    page.get_by_test_id("not-found-link").click()
    expect(page.get_by_test_id("page-title")).to_have_text("Trades")


@pytest.mark.parametrize(
    ("path", "message"),
    [("/trades/abc", "Trade not found"), ("/notes/abc", "Note not found"), ("/day/2037-13-45", "That is not a day")],
)
def test_a_malformed_address_never_reaches_the_server(page: Page, path: str, message: str):
    requested: list[str] = []
    page.on("request", lambda request: requested.append(request.url) if "/api/trades/" in request.url or "/api/notes/" in request.url else None)
    open_app(page, path)
    expect(page.get_by_test_id("not-found")).to_contain_text(message)
    assert requested == [], f"the app asked the API about a malformed address: {requested}"
