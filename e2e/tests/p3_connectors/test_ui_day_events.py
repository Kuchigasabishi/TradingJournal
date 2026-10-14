"""Phase 3: everything outside the journal that happens on one day, on the day's own screen.

The calendar events come first (a handful, and the owner's own), then the economic news in time order. Times are the server's
(America/New_York in verification), whatever zone the feed wrote them in. Rows are found by the id the API gave each event.
"""
import re

import pytest
from playwright.sync_api import Page, expect

from support.feeds import calendar_events, ff_week
from support.ui import expect_api, open_app

pytestmark = pytest.mark.usefixtures("leave_the_app_before_cleanup")

NEWS = list(ff_week("week_a").values())
PERSONAL = list(calendar_events("a").values())


def ids(feeds, source: str) -> dict[tuple[str, str], int]:
    """(title, start) to the id the API gave the event, so a test can address its row."""
    return {(e["title"], e["start_at"] or e["start_day"]): e["id"] for e in feeds.all_events(source)}


def news_id(feeds, title: str, start_at: str) -> int:
    return next(e["id"] for e in feeds.all_events("forexfactory") if e["title"] == title and e["start_at"] == start_at)


def test_a_day_lists_the_calendar_first_then_the_news_in_time_order(page: Page, shot):
    with expect_api(page, "GET", r"^/api/events$", {"from": "2044-05-12", "to": "2044-05-12"}) as call:
        open_app(page, "/day/2044-05-12")
    assert call.status == 200 and call.request_id.startswith("web-")  # the screen asks for its own day, and says it is the app asking
    expect(page.get_by_test_id("day-events-zone")).to_have_text("Times are in America/New_York.")
    expect(page.get_by_test_id("day-events-personal-heading")).to_have_text("Calendar · 3")
    expect(page.get_by_test_id("day-events-news-heading")).to_have_text("Economic news · 35")

    personal = sorted([e for e in PERSONAL if e["start_day"] <= "2044-05-12" <= e["end_day"]], key=lambda e: (not e["all_day"], e["start_at"] or ""))
    news = sorted([e for e in NEWS if e["start_day"] == "2044-05-12"], key=lambda e: (e["start_at"], e["title"]))
    titles = page.locator("[data-testid^='event-title-']")
    expect(titles).to_have_text([e["title"] for e in personal] + [e["title"] for e in news])
    # the card sits between the day's figures and its trades
    assert page.get_by_test_id("day-events").bounding_box()["y"] < page.get_by_test_id("day-trades").bounding_box()["y"]
    shot("01-thursday")


def test_a_news_row_shows_when_how_much_for_whom_and_what(page: Page, feeds):
    core = news_id(feeds, "Core Retail Sales m/m", "2044-05-12T12:30:00Z")
    open_app(page, "/day/2044-05-12")
    expect(page.get_by_test_id(f"event-time-{core}")).to_have_text("08:30")  # 12:30 UTC is 08:30 in New York
    expect(page.get_by_test_id(f"event-impact-{core}")).to_have_text("High")
    expect(page.get_by_test_id(f"event-{core}").get_by_role("img", name="High impact")).to_be_visible()
    expect(page.get_by_test_id(f"event-currency-{core}")).to_have_text("USD")
    expect(page.get_by_test_id(f"event-title-{core}")).to_have_text("Core Retail Sales m/m")
    expect(page.get_by_test_id(f"event-figures-{core}")).to_have_text("Forecast 0.6% · Previous 1.4%")

    storage = news_id(feeds, "Natural Gas Storage", "2044-05-12T14:30:00Z")  # a release with a previous figure and no forecast
    expect(page.get_by_test_id(f"event-figures-{storage}")).to_have_text("Previous 85B")
    expect(page.get_by_test_id(f"event-time-{storage}")).to_have_text("10:30")
    speaks = news_id(feeds, "BOE Gov Bailey Speaks", "2044-05-12T07:30:00Z")  # a speech has neither
    expect(page.get_by_test_id(f"event-impact-{speaks}")).to_have_text("Medium")
    expect(page.get_by_test_id(f"event-figures-{speaks}")).to_have_count(0)
    # news carries a link to the feed's own page for the event; the test looks at it and does not follow it
    link = page.get_by_test_id(f"event-link-{core}")
    expect(link).to_have_attribute("aria-label", "Details of Core Retail Sales m/m")
    expect(link).to_have_attribute("role", "link")


def test_news_for_every_currency_and_a_holiday_read_as_themselves(page: Page, feeds):
    imf = news_id(feeds, "IMF Meetings", "2044-05-09T14:15:00Z")
    holiday = news_id(feeds, "Bank Holiday", "2044-05-09T11:00:00Z")
    open_app(page, "/day/2044-05-09")
    expect(page.get_by_test_id(f"event-currency-{imf}")).to_have_text("ALL")
    expect(page.get_by_test_id(f"event-impact-{holiday}")).to_have_text("Holiday")
    expect(page.get_by_test_id(f"event-{holiday}").get_by_role("img", name="Holiday")).to_be_visible()
    expect(page.get_by_test_id(f"event-figures-{holiday}")).to_have_count(0)  # empty in the feed means nothing to show


def test_a_calendar_row_shows_its_time_in_the_servers_zone_its_place_and_its_text(page: Page, feeds):
    open_app(page, "/day/2044-05-11")
    london = ids(feeds, "gcal")[("London open briefing", "2044-05-11T08:00:00Z")]
    expect(page.get_by_test_id(f"event-time-{london}")).to_have_text("04:00–05:00")  # written as 09:00 to 10:00 in London
    expect(page.get_by_test_id(f"event-kind-{london}")).to_have_text("Calendar")
    expect(page.get_by_test_id(f"event-location-{london}")).to_have_text("Zoom, London desk")
    expect(page.get_by_test_id(f"event-description-{london}")).to_contain_text("Walk through the overnight Asian range and the London open plan, including the levels from last week")
    expect(page.get_by_test_id(f"event-link-{london}")).to_have_count(0)  # the calendar gave it no address

    open_app(page, "/day/2044-05-13")
    broker = ids(feeds, "gcal")[("Broker call", "2044-05-13T15:00:00Z")]
    description = page.get_by_test_id(f"event-description-{broker}")
    expect(description).to_contain_text("Platform update and fees")
    expect(description).not_to_contain_text("<")  # Google wrote it as HTML; the screen shows the text
    expect(description).not_to_contain_text("&nbsp;")


def test_all_day_and_multi_day_events_read_as_such(page: Page, feeds):
    open_app(page, "/day/2044-05-19")
    course = ids(feeds, "gcal")[("Trading course", "2044-05-18")]
    expect(page.get_by_test_id(f"event-time-{course}")).to_have_text("All day · May 18 to May 20")
    open_app(page, "/day/2044-05-13")
    asia = ids(feeds, "gcal")[("Asia session review", "2044-05-13T02:00:00Z")]
    expect(page.get_by_test_id(f"event-time-{asia}")).to_have_text("May 12 22:00 → May 13 02:00")  # the same words on both days
    open_app(page, "/day/2044-05-12")
    expect(page.get_by_test_id(f"event-time-{asia}")).to_have_text("May 12 22:00 → May 13 02:00")
    day_off = ids(feeds, "gcal")[("Bank day off", "2044-05-12")]
    expect(page.get_by_test_id(f"event-time-{day_off}")).to_have_text("All day")


def test_the_impact_and_currency_chips_narrow_the_rows(page: Page, shot):
    open_app(page, "/day/2044-05-12")
    page.get_by_test_id("filter-impact-high").click()
    expect(page.get_by_test_id("day-events-news-heading")).to_have_text("Economic news · 7")
    page.get_by_test_id("filter-impact-medium").click()
    expect(page.get_by_test_id("day-events-news-heading")).to_have_text("Economic news · 11")
    page.get_by_test_id("filter-currency-USD").click()
    wanted = [e for e in NEWS if e["start_day"] == "2044-05-12" and e["impact"] in ("high", "medium") and e["currency"] in ("USD", "ALL")]
    expect(page.get_by_test_id("day-events-news-heading")).to_have_text(f"Economic news · {len(wanted)}")
    in_order = sorted(wanted, key=lambda e: (e["start_at"], e["title"]))
    expect(page.get_by_test_id("day-events-news").locator("[data-testid^='event-currency-']")).to_have_text([e["currency"] for e in in_order])
    assert {e["currency"] for e in in_order} <= {"USD", "ALL"}
    expect(page.get_by_test_id("day-events-personal").locator("[data-testid^='event-currency-']")).to_have_count(0)  # a calendar event has no currency
    shot("01-high-and-medium-usd")


def test_a_day_with_nothing_says_so(page: Page):
    open_app(page, "/day/2043-01-05")
    expect(page.get_by_test_id("day-events-empty")).to_have_text("No events on this day.")
    expect(page.get_by_test_id("event-filters")).to_have_count(0)


def test_moving_to_the_next_day_shows_that_days_events(page: Page):
    open_app(page, "/day/2044-05-12")
    expect(page.get_by_test_id("day-events-news-heading")).to_have_text("Economic news · 35")
    page.get_by_test_id("day-next").click()
    expect(page).to_have_url(re.compile(r"/day/2044-05-13$"))
    expect(page.get_by_test_id("day-events-news-heading")).to_have_text("Economic news · 14")
    expect(page.get_by_test_id("day-events-personal-heading")).to_have_text("Calendar · 2")  # the review that began the night before, and the broker call
