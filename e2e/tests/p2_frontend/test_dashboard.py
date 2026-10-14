"""Phase 2: the dashboard shows the month's figures exactly, draws them to scale, and handles bad networks."""
import re
from datetime import date

import pytest
from playwright.sync_api import Page, expect

from support.journal import unique
from support.ui import day_label, open_app, server_today

MONTH = "2037-04"


def closed(journal, day: str, pnl: str, hour: int = 14, **extra):
    """A closed trade on `day` (UTC; in New York it is the same day for these hours)."""
    return journal.trade(opened_at=f"{day}T{hour - 1:02d}:00:00Z", closed_at=f"{day}T{hour:02d}:00:00Z", pnl=pnl, **extra)


@pytest.fixture
def april_2037(journal):
    """Four closed trades on three days: +27.8, -12.3, then 0 and +5.2 on the same day. Net 20.7."""
    closed(journal, "2037-04-06", "27.8")
    closed(journal, "2037-04-07", "-12.3", hour=15)
    closed(journal, "2037-04-08", "0", hour=15)
    closed(journal, "2037-04-08", "5.2", hour=18)
    return journal.open_trade(opened_at="2037-04-09T12:00:00Z")


def test_the_month_summary_is_exact(page: Page, api, april_2037, shot):
    open_app(page, f"/?month={MONTH}")
    expect(page.get_by_test_id("month-label")).to_have_text("April 2037")

    expect(page.get_by_test_id("stat-net-value")).to_have_text("+$20.70")
    expect(page.get_by_test_id("stat-net-mark")).to_have_attribute("aria-label", "gain")
    expect(page.get_by_test_id("stat-net-caption")).to_have_text("4 trades closed")
    expect(page.get_by_test_id("stat-win-rate-value")).to_have_text("50.0%")
    expect(page.get_by_test_id("stat-win-rate-caption")).to_have_text("2 wins of 4 trades closed")
    expect(page.get_by_test_id("stat-win-rate-meter")).to_have_attribute("aria-valuenow", "50")
    # 20.7 / 4 = 5.175 exactly, which rounds half away from zero to 5.18 (a float would say 5.17).
    expect(page.get_by_test_id("stat-average-value")).to_have_text("+$5.18")
    expect(page.get_by_test_id("stat-closed-value")).to_have_text("4")
    expect(page.get_by_test_id("stat-closed-caption")).to_have_text("2 wins · 1 loss · 1 breakeven")
    expect(page.get_by_test_id("stat-best-day-value")).to_have_text("+$27.80")
    expect(page.get_by_test_id("stat-best-day-caption")).to_have_text(day_label(date(2037, 4, 6)))
    expect(page.get_by_test_id("stat-worst-day-value")).to_have_text("-$12.30")
    expect(page.get_by_test_id("stat-worst-day-caption")).to_have_text(day_label(date(2037, 4, 7)))

    # Open versus closed is counted across the whole journal, so ask the API rather than assume the database is empty.
    open_total = api.get("/api/trades?status=open&limit=1").json()["total"]
    closed_total = api.get("/api/trades?status=closed&limit=1").json()["total"]
    expect(page.get_by_test_id("stat-open-value")).to_have_text(str(open_total))
    expect(page.get_by_test_id("stat-open-caption")).to_have_text(f"{closed_total} closed in total")
    shot("01-april-2037")


def test_the_daily_chart_is_drawn_to_scale(page: Page, april_2037, shot):
    open_app(page, f"/?month={MONTH}")
    expect(page.get_by_test_id("daily-chart")).to_be_visible()

    expect(page.get_by_test_id("axis-max")).to_have_text("+$27.80")
    expect(page.get_by_test_id("axis-min")).to_have_text("-$12.30")

    def box(day: str) -> dict:
        locator = page.get_by_test_id(f"bar-mark-2037-04-{day}")
        expect(locator).to_be_visible()
        return locator.bounding_box()

    big_gain, loss, small_gain = box("06"), box("07"), box("08")
    assert page.get_by_test_id("bar-mark-2037-04-09").count() == 0, "a day without trades has no bar"
    # Gains rise above the zero line and losses hang below it.
    assert big_gain["y"] + big_gain["height"] <= loss["y"] + 1
    assert abs((big_gain["y"] + big_gain["height"]) - (small_gain["y"] + small_gain["height"])) <= 1, "gains share one baseline"
    # One scale for both directions: heights are proportional to the exact amounts.
    assert small_gain["height"] / big_gain["height"] == pytest.approx(5.2 / 27.8, rel=0.1)
    assert loss["height"] / big_gain["height"] == pytest.approx(12.3 / 27.8, rel=0.1)
    # Blue for gains, red for losses (the validated diverging pair), never green.
    expect(page.get_by_test_id("bar-mark-2037-04-06")).to_have_css("background-color", "rgb(57, 135, 229)")
    expect(page.get_by_test_id("bar-mark-2037-04-07")).to_have_css("background-color", "rgb(215, 88, 83)")
    shot("01-chart")


def test_hovering_a_bar_shows_its_exact_figures(page: Page, april_2037, shot):
    open_app(page, f"/?month={MONTH}")
    tooltip = page.get_by_test_id("bar-tooltip-2037-04-08")
    expect(tooltip).to_have_count(0)
    page.get_by_test_id("bar-2037-04-08").hover()
    expect(tooltip).to_be_visible()
    expect(tooltip).to_contain_text(day_label(date(2037, 4, 8)))
    expect(tooltip).to_contain_text("+$5.20")
    expect(tooltip).to_contain_text("2 trades · 1W 0L 1BE")
    shot("01-tooltip")
    page.mouse.move(0, 0)
    expect(tooltip).to_have_count(0)


def test_the_table_view_lists_every_day_with_exact_amounts(page: Page, april_2037, shot):
    open_app(page, f"/?month={MONTH}")
    page.get_by_test_id("view-table").click()
    expect(page.get_by_test_id("daily-table")).to_be_visible()
    expect(page.get_by_test_id("daily-chart")).to_have_count(0)
    rows = page.locator("[data-testid^='daily-row-']")
    expect(rows).to_have_count(3)
    expect(page.get_by_test_id("daily-pnl-2037-04-06")).to_have_text("+$27.80")
    expect(page.get_by_test_id("daily-pnl-2037-04-07")).to_have_text("-$12.30")
    expect(page.get_by_test_id("daily-pnl-2037-04-08")).to_have_text("+$5.20")
    expect(page.get_by_test_id("daily-row-2037-04-08")).to_contain_text("1 / 0 / 1")
    shot("01-table")

    page.get_by_test_id("daily-link-2037-04-07").click()
    expect(page).to_have_url(re.compile(r"/day/2037-04-07$"))
    page.go_back()
    page.get_by_test_id("view-chart").click()
    expect(page.get_by_test_id("daily-chart")).to_be_visible()


def test_open_trades_are_listed_with_a_link(page: Page, april_2037, journal, shot):
    open_app(page, f"/?month={MONTH}")
    card = page.get_by_test_id("open-trades")
    expect(card).to_be_visible()
    link = page.get_by_test_id(f"open-trade-link-{april_2037['id']}")
    expect(link).to_have_text(april_2037["instrument"])
    expect(page.get_by_test_id(f"open-trade-{april_2037['id']}")).to_contain_text("Long · 0.10 lots at 1.08543")
    link.click()
    expect(page).to_have_url(re.compile(rf"/trades/{april_2037['id']}$"))
    expect(page.get_by_test_id("trade-status")).to_have_text("Open")


def test_month_navigation_changes_the_address_and_the_figures(page: Page, april_2037, shot):
    open_app(page, f"/?month={MONTH}")
    page.get_by_test_id("month-prev").click()
    expect(page).to_have_url(re.compile(r"month=2037-03"))
    expect(page.get_by_test_id("month-label")).to_have_text("March 2037")
    expect(page.get_by_test_id("stat-net-value")).to_have_text("$0.00")
    expect(page.get_by_test_id("stat-net-caption")).to_have_text("No closed trades this month")

    page.get_by_test_id("month-next").click()
    page.get_by_test_id("month-next").click()
    expect(page.get_by_test_id("month-label")).to_have_text("May 2037")

    today = server_today()
    page.get_by_test_id("month-today").click()
    expect(page.get_by_test_id("month-label")).to_have_text(date(today.year, today.month, 1).strftime("%B %Y"))
    expect(page.get_by_test_id("month-today")).to_be_disabled()


def test_an_empty_month_says_so_instead_of_showing_noise(page: Page, journal, shot):
    # A trade in another month keeps the journal from being empty, which would show the first-run invitation instead.
    # Tests run in whatever order pytest picks (it runs browser tests before API-only ones), so none may assume data from another.
    journal.trade(opened_at="2036-02-03T13:00:00Z", closed_at="2036-02-03T14:00:00Z")
    open_app(page, "/?month=2036-01")
    expect(page.get_by_test_id("stat-net-value")).to_have_text("$0.00")
    expect(page.get_by_test_id("stat-net-mark")).to_have_count(0)  # a zero total points nowhere
    expect(page.get_by_test_id("stat-win-rate-value")).to_have_text("–")
    expect(page.get_by_test_id("stat-average-value")).to_have_text("–")
    expect(page.get_by_test_id("stat-best-day-caption")).to_have_text("No winning days")
    expect(page.get_by_test_id("stat-worst-day-caption")).to_have_text("No losing days")
    expect(page.get_by_test_id("daily-chart-empty")).to_have_text("No closed trades this month")
    shot("01-empty-month")


@pytest.mark.allow_console_errors(r"status of 500", r"^HTTP 500", reason="the test injects a 500 answer to see the error state")
def test_a_failed_request_shows_an_error_and_retry_recovers(page: Page, april_2037, shot):
    page.route(re.compile(r"/api/calendar/month"), lambda route: route.fulfill(status=500, json={"detail": "boom"}))
    open_app(page, f"/?month={MONTH}")
    error = page.get_by_test_id("dashboard-error")
    expect(error).to_be_visible()
    expect(error).to_contain_text("Could not load the month")
    expect(page.get_by_test_id("stat-net")).to_have_count(0)
    shot("01-error")

    page.unroute(re.compile(r"/api/calendar/month"))
    page.get_by_test_id("dashboard-retry").click()
    expect(page.get_by_test_id("stat-net-value")).to_have_text("+$20.70")
    expect(error).to_have_count(0)
    shot("02-recovered")


def test_a_brand_new_journal_invites_the_first_trade(page: Page, shot):
    """The server's lists are replaced by empty ones, as a fresh database would answer."""
    empty = {"items": [], "total": 0, "limit": 5, "offset": 0}
    page.route(re.compile(r"/api/trades\?"), lambda route: route.fulfill(status=200, json=empty))
    open_app(page, "/")
    expect(page.get_by_test_id("dashboard-empty")).to_contain_text("Your journal is empty")
    expect(page.get_by_test_id("stat-net")).to_have_count(0)
    shot("01-first-run")
    page.get_by_test_id("empty-new-trade").click()
    expect(page).to_have_url(re.compile(r"/trades/new$"))


def test_switching_months_dims_the_old_figures_until_the_new_ones_arrive(page: Page, april_2037, shot):
    open_app(page, f"/?month={MONTH}")
    expect(page.get_by_test_id("stat-net-value")).to_have_text("+$20.70")

    held = []
    page.route(re.compile(r"/api/calendar/month\?.*month=3"), lambda route: held.append(route))
    page.get_by_test_id("month-prev").click()
    expect(page.get_by_test_id("month-label")).to_have_text("March 2037")
    content = page.get_by_test_id("dashboard-content")
    expect(content).to_have_attribute("aria-busy", "true")
    expect(page.get_by_test_id("stat-net-value")).to_have_text("+$20.70")  # still the old month, shown dimmed
    shot("01-loading-the-next-month")

    assert len(held) == 1
    held[0].continue_()
    expect(page.get_by_test_id("stat-net-value")).to_have_text("$0.00")
    expect(content).to_have_attribute("aria-busy", "false")


def test_the_figures_stay_exact_beyond_what_a_float_can_hold(page: Page, journal, shot):
    """9,999,999,999.99999999 and -0.00000001 net to 9,999,999,999.99999998, which needs 18 significant digits."""
    journal.trade(instrument=unique("EX"), opened_at="2041-02-03T13:00:00Z", closed_at="2041-02-03T14:00:00Z", pnl="9999999999.99999999")
    journal.trade(instrument=unique("EX"), opened_at="2041-02-04T13:00:00Z", closed_at="2041-02-04T14:00:00Z", pnl="-0.00000001")
    open_app(page, "/?month=2041-02")
    expect(page.get_by_test_id("stat-net-value")).to_have_text("+$9,999,999,999.99999998")
    expect(page.get_by_test_id("stat-best-day-value")).to_have_text("+$9,999,999,999.99999999")
    expect(page.get_by_test_id("stat-worst-day-value")).to_have_text("-$0.00000001")
    expect(page.get_by_test_id("stat-average-value")).to_have_text("+$5,000,000,000.00")  # derived figures round to the cent
    shot("01-beyond-float")
