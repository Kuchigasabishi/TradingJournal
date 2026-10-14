"""Phase 3: choosing which events to see.

The filters live in the address bar, like the trade list's, so a view can be linked and reloaded: show (everything, only news or
only the personal calendar), the impact levels of the news, and one currency. They narrow news only: a personal event has neither
an impact nor a currency.
"""
import re

import pytest
from playwright.sync_api import Page, expect

from support.events_ui import expect_grid
from support.feeds import calendar_events, ff_week, month_days
from support.ui import open_app

pytestmark = pytest.mark.usefixtures("leave_the_app_before_cleanup")

MONTH = "2044-05"
DAYS = month_days(MONTH)
NEWS = list(ff_week("week_a").values())
PERSONAL = list(calendar_events("a").values())
PERSONAL_IN_MONTH = len([e for e in PERSONAL if e["end_day"] >= f"{MONTH}-01" and e["start_day"] <= f"{MONTH}-31"])
EVERYTHING = len(NEWS) + PERSONAL_IN_MONTH


def summary(page: Page):
    return page.get_by_test_id("calendar-events-summary")


def count_news(impacts: tuple[str, ...] = (), currency: str | None = None) -> int:
    return len([e for e in NEWS if (not impacts or e["impact"] in impacts) and (not currency or e["currency"] in (currency, "ALL"))])


def test_choosing_impact_levels_narrows_the_news_and_the_address_remembers(page: Page, shot):
    open_app(page, f"/calendar?month={MONTH}")
    high, medium = page.get_by_test_id("filter-impact-high"), page.get_by_test_id("filter-impact-medium")
    expect(high).to_have_attribute("aria-pressed", "false")

    high.click()
    expect(high).to_have_attribute("aria-pressed", "true")
    expect(page).to_have_url(re.compile(r"/calendar\?(month=2044-05&impact=high|impact=high&month=2044-05)$"))  # the month stays in the address
    expect_grid(page, NEWS, PERSONAL, DAYS, impacts=("high",))
    expect(summary(page)).to_have_text(f"Showing {count_news(('high',)) + PERSONAL_IN_MONTH} of {EVERYTHING} events this month.")
    shot("01-high-only")

    medium.click()
    expect(page).to_have_url(re.compile(r"impact=high&impact=medium"))  # levels are always written in the same order
    expect_grid(page, NEWS, PERSONAL, DAYS, impacts=("high", "medium"))
    expect(summary(page)).to_have_text(f"Showing {count_news(('high', 'medium')) + PERSONAL_IN_MONTH} of {EVERYTHING} events this month.")

    # The address is the state: the same view comes back from a fresh load.
    page.reload()
    expect(page.get_by_test_id("filter-impact-high")).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_test_id("filter-impact-low")).to_have_attribute("aria-pressed", "false")
    expect_grid(page, NEWS, PERSONAL, DAYS, impacts=("high", "medium"))

    page.get_by_test_id("filter-impact-high").click()  # choosing a level again takes it off
    expect(page).to_have_url(re.compile(r"impact=medium$"))
    page.get_by_test_id("filter-clear").click()
    expect(page).not_to_have_url(re.compile(r"impact="))
    expect(page.get_by_test_id("filter-clear")).to_have_count(0)
    expect_grid(page, NEWS, PERSONAL, DAYS)
    expect(summary(page)).to_have_text(f"{EVERYTHING} events this month: {len(NEWS)} news, {PERSONAL_IN_MONTH} personal.")


def test_a_currency_narrows_the_news_to_it_and_to_news_for_every_currency(page: Page, shot):
    open_app(page, f"/calendar?month={MONTH}")
    usd = page.get_by_test_id("filter-currency-USD")
    expect(page.get_by_test_id("filter-currency-all")).to_have_attribute("aria-pressed", "true")
    for code in ("AUD", "CAD", "CHF", "CNY", "EUR", "GBP", "JPY", "NZD", "USD"):  # the currencies the month's news mentions, and no more
        expect(page.get_by_test_id(f"filter-currency-{code}")).to_be_visible()
    expect(page.get_by_test_id("filter-currency-ALL")).to_have_count(0)  # "all currencies" is not a currency to choose

    usd.click()
    expect(page).to_have_url(re.compile(r"currency=USD"))
    expect(usd).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_test_id("filter-currency-all")).to_have_attribute("aria-pressed", "false")
    expect_grid(page, NEWS, PERSONAL, DAYS, currency="USD")  # the USD events, and the six that concern every currency
    shot("01-usd")

    page.get_by_test_id("filter-impact-high").click()  # filters combine
    expect(page).to_have_url(re.compile(r"(impact=high&currency=USD|currency=USD&impact=high)"))
    expect_grid(page, NEWS, PERSONAL, DAYS, impacts=("high",), currency="USD")

    page.get_by_test_id("filter-currency-all").click()
    expect(page).not_to_have_url(re.compile(r"currency="))
    expect_grid(page, NEWS, PERSONAL, DAYS, impacts=("high",))


def test_show_only_the_news_or_only_the_personal_calendar(page: Page, shot):
    open_app(page, f"/calendar?month={MONTH}")
    page.get_by_test_id("filter-show-news").click()
    expect(page).to_have_url(re.compile(r"show=news"))
    expect_grid(page, NEWS, PERSONAL, DAYS, show="news")
    expect(page.locator("[data-testid^='personal-badge-']")).to_have_count(0)
    expect(summary(page)).to_have_text(f"Showing {len(NEWS)} of {EVERYTHING} events this month.")

    page.get_by_test_id("filter-show-personal").click()
    expect(page).to_have_url(re.compile(r"show=personal"))
    expect_grid(page, NEWS, PERSONAL, DAYS, show="personal")
    expect(page.locator("[data-testid^='news-badge-']")).to_have_count(0)
    expect(page.get_by_test_id("filter-impact-high")).to_have_count(0)  # nothing to narrow: the news is not shown
    expect(page.get_by_test_id("filter-currency-USD")).to_have_count(0)
    shot("01-personal-only")

    page.get_by_test_id("filter-show-all").click()
    expect(page).not_to_have_url(re.compile(r"show="))
    expect(page.get_by_test_id("filter-impact-high")).to_be_visible()


def test_the_filters_go_with_you_to_a_day_and_back(page: Page, shot):
    open_app(page, f"/calendar?month={MONTH}&impact=high")
    page.get_by_test_id("day-2044-05-12").click()
    expect(page).to_have_url(re.compile(r"/day/2044-05-12\?impact=high$"))
    expect(page.get_by_test_id("filter-impact-high")).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_test_id("day-events-news-heading")).to_have_text("Economic news · 7")
    expect(page.get_by_test_id("day-events-personal-heading")).to_have_text("Calendar · 3")  # personal events have no impact to narrow by
    expect(page.locator("[data-testid^='event-impact-']")).to_have_text(["High"] * 7)
    shot("01-day-high-only")

    page.get_by_test_id("back-link").click()
    expect(page).to_have_url(re.compile(r"/calendar\?month=2044-05&impact=high$"))
    expect(page.get_by_test_id("filter-impact-high")).to_have_attribute("aria-pressed", "true")
    expect_grid(page, NEWS, PERSONAL, DAYS, impacts=("high",))


def test_a_day_where_nothing_matches_says_so_and_clears_in_one_press(page: Page):
    open_app(page, "/day/2044-05-14?impact=holiday")  # Saturday: three low and one medium release, no holiday
    expect(page.get_by_test_id("day-events-none-match")).to_have_text("No events match these filters.")
    expect(page.locator("[data-testid^='event-title-']")).to_have_count(0)
    page.get_by_test_id("filter-clear").click()
    expect(page).to_have_url(re.compile(r"/day/2044-05-14$"))
    expect(page.get_by_test_id("day-events-news-heading")).to_have_text("Economic news · 4")
    expect(page.get_by_test_id("day-events-none-match")).to_have_count(0)


def test_the_table_view_follows_the_filters(page: Page):
    open_app(page, f"/calendar?month={MONTH}&impact=high")
    page.get_by_test_id("view-table").click()
    expect(page.get_by_test_id("daily-news-2044-05-12")).to_have_text("7 high")
    expect(page.get_by_test_id("daily-news-2044-05-11")).to_have_text("6 high")
    expect(page.get_by_test_id("daily-row-2044-05-14")).to_have_count(0)  # that Saturday has no high-impact news, no event and no trade
    expect(page.get_by_test_id("daily-events-2044-05-12")).to_have_text("Bank day off, Floating dinner, Asia session review")  # personal events are not narrowed


def test_a_filter_the_app_does_not_understand_is_ignored(page: Page):
    open_app(page, f"/calendar?month={MONTH}&impact=urgent&show=everything&currency=%24%24")
    expect(summary(page)).to_have_text(f"{EVERYTHING} events this month: {len(NEWS)} news, {PERSONAL_IN_MONTH} personal.")
    expect(page.get_by_test_id("filter-show-all")).to_have_attribute("aria-checked", "true")
    expect(page.get_by_test_id("filter-clear")).to_have_count(0)
