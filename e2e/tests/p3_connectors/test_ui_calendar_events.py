"""Phase 3: the synced events on the calendar grid.

The month is May 2044, the week the fixtures describe (fixtures/README.md). News shows as bars filled to its impact with
the number of releases, in an amber ramp that is neither the blue of a gain nor the red of a loss; the owner's own events
show as a ring and a title. What each day should show is worked out from the fixture oracles, not read back from the app.
"""
import re
from datetime import date

import pytest
from playwright.sync_api import Page, expect

from support.events_ui import expect_grid
from support.feeds import calendar_events, day_news, day_personal, ff_week, month_days
from support.ui import day_label, open_app

pytestmark = pytest.mark.usefixtures("leave_the_app_before_cleanup")

MONTH = "2044-05"
DAYS = month_days(MONTH)
NEWS = list(ff_week("week_a").values())
PERSONAL = list(calendar_events("a").values())
# The amber ramp (frontend/src/theme.ts), and the colour of a bar that is not filled, as the browser reports them.
AMBER = {"low": "rgb(237, 161, 7)", "medium": "rgb(180, 121, 5)", "high": "rgb(126, 84, 3)"}
EMPTY_BAR = "rgb(225, 224, 217)"
CHIP = "rgb(252, 252, 251)"  # the neutral chip every mark sits on
GAIN_THIRD = "rgb(57, 135, 229)"  # 40 against the month's largest day, 50, is four fifths: the third of four shades
LOSS_DARKEST = "rgb(158, 52, 50)"


def cell(page: Page, day: str):
    return page.get_by_test_id(f"day-{day}")


def month_events() -> tuple[int, int]:
    news = len(NEWS)
    personal = len([e for e in PERSONAL if e["end_day"] >= f"{MONTH}-01" and e["start_day"] <= f"{MONTH}-31"])
    return news, personal


def test_every_day_shows_its_news_by_impact_and_its_personal_events(page: Page, shot):
    open_app(page, f"/calendar?month={MONTH}")
    news, personal = month_events()
    expect(page.get_by_test_id("calendar-events-summary")).to_have_text(f"{news + personal} events this month: {news} news, {personal} personal.")

    expect_grid(page, NEWS, PERSONAL, DAYS)

    # The figures the owner will look at first: Thursday the 12th has every level, and two of its three personal events are hidden behind the first.
    for impact, count in (("high", 7), ("medium", 4), ("low", 24)):
        expect(page.get_by_test_id(f"news-count-2044-05-12-{impact}")).to_have_text(str(count))
    expect(page.get_by_test_id("personal-title-2044-05-12")).to_have_text("Bank day off")
    expect(page.get_by_test_id("personal-title-2044-05-12-more")).to_have_text("+2")
    shot("01-may-2044")


def test_news_is_drawn_as_bars_in_an_amber_ramp_that_is_not_a_gain_or_a_loss(page: Page):
    open_app(page, f"/calendar?month={MONTH}")
    for impact, filled in (("high", 3), ("medium", 2), ("low", 1)):
        for index in range(3):
            bar = page.get_by_test_id(f"news-badge-2044-05-12-{impact}-glyph-bar-{index}")
            expect(bar).to_have_css("background-color", AMBER[impact] if index < filled else EMPTY_BAR)
        # the same glyph in the legend, which says what the bars mean
        for index in range(3):
            expect(page.get_by_test_id(f"legend-impact-{impact}-bar-{index}")).to_have_css("background-color", AMBER[impact] if index < filled else EMPTY_BAR)
    expect(page.get_by_test_id("legend-impact-holiday")).to_have_attribute("aria-label", "Holiday")
    expect(page.get_by_test_id("legend-personal")).to_have_attribute("aria-label", "personal event")
    expect(page.get_by_test_id("news-badge-2044-05-12-high-glyph")).to_have_attribute("aria-label", "High impact")
    expect(page.get_by_test_id("news-badge-2044-05-08-holiday-glyph")).to_have_attribute("aria-label", "Holiday")  # the holiday that opens the week
    expect(page.get_by_test_id("calendar-events-legend")).to_contain_text("The number is how many releases.")


def test_a_day_with_trades_keeps_its_pnl_shade_and_its_events_sit_on_a_neutral_chip(page: Page, journal, shot):
    # 11:00 in New York on the 11th and the 12th, the two busiest news days of the week
    journal.trade(opened_at="2044-05-11T13:00:00Z", closed_at="2044-05-11T15:00:00Z", pnl="40")
    journal.trade(opened_at="2044-05-12T13:00:00Z", closed_at="2044-05-12T15:00:00Z", pnl="-50")
    open_app(page, f"/calendar?month={MONTH}")
    expect(page.get_by_test_id("day-pnl-2044-05-12")).to_have_text("-$50.00")
    expect(page.get_by_test_id("day-pnl-2044-05-11")).to_have_text("+$40.00")
    expect(cell(page, "2044-05-12")).to_have_css("background-color", LOSS_DARKEST)  # the shade still belongs to the money
    expect(cell(page, "2044-05-11")).to_have_css("background-color", GAIN_THIRD)
    for day, impact in (("2044-05-12", "high"), ("2044-05-11", "high")):
        expect(page.get_by_test_id(f"news-badge-{day}-{impact}")).to_have_css("background-color", CHIP)  # ...and the news does not borrow it
        expect(page.get_by_test_id(f"personal-badge-{day}")).to_have_css("background-color", CHIP)
    expect(cell(page, "2044-05-12")).to_have_attribute("aria-label", re.compile(r"-\$50\.00, 1 trade, 35 news events \(7 high, 4 medium, 24 low\), 3 personal events$"))
    shot("01-trades-and-events")


def test_each_cell_names_its_events_for_a_screen_reader(page: Page):
    open_app(page, f"/calendar?month={MONTH}")
    label = lambda day: day_label(date.fromisoformat(day))  # noqa: E731
    expect(cell(page, "2044-05-11")).to_have_attribute("aria-label", f"{label('2044-05-11')}, no closed trades, 22 news events (6 high, 3 medium, 13 low), 1 personal event")
    expect(cell(page, "2044-05-09")).to_have_attribute("aria-label", f"{label('2044-05-09')}, no closed trades, 12 news events (10 low, 2 holidays), 1 personal event")
    expect(cell(page, "2044-05-08")).to_have_attribute("aria-label", f"{label('2044-05-08')}, no closed trades, 1 news event (1 holiday)")
    expect(cell(page, "2044-05-17")).to_have_attribute("aria-label", f"{label('2044-05-17')}, no closed trades, 1 personal event")
    expect(cell(page, "2044-05-24")).to_have_attribute("aria-label", f"{label('2044-05-24')}, no closed trades")  # nothing from outside: nothing added


def test_a_multi_day_event_is_on_every_day_it_covers(page: Page):
    open_app(page, f"/calendar?month={MONTH}")
    for day in ("2044-05-18", "2044-05-19", "2044-05-20"):
        expect(page.get_by_test_id(f"personal-title-{day}")).to_have_text("Trading course")
    expect(page.get_by_test_id("personal-title-2044-05-17")).to_have_text("Weekly review (moved)")  # the day before it starts
    expect(page.get_by_test_id("personal-badge-2044-05-21")).to_have_count(0)  # the day after it ends
    # 22:00 to 02:00 in New York is the 12th and the 13th
    expect(cell(page, "2044-05-13")).to_have_attribute("aria-label", f"{day_label(date(2044, 5, 13))}, no closed trades, 14 news events (1 medium, 13 low), 2 personal events")
    expect(page.get_by_test_id("personal-title-2044-05-13")).to_have_text("Asia session review")
    expect(page.get_by_test_id("personal-title-2044-05-13-more")).to_have_text("+1")  # the broker call is the other


def test_hovering_a_day_lists_its_events(page: Page, shot):
    open_app(page, f"/calendar?month={MONTH}")
    cell(page, "2044-05-12").hover()
    tooltip = page.get_by_test_id("day-tooltip-2044-05-12")
    expect(tooltip).to_be_visible()
    expect(tooltip).to_contain_text("35 news events: 7 high, 4 medium, 24 low")
    for title in ("Bank day off", "Floating dinner", "Asia session review"):
        expect(tooltip).to_contain_text(title)
    shot("01-tooltip")


def test_pressing_a_day_opens_it_with_its_events(page: Page):
    open_app(page, f"/calendar?month={MONTH}")
    cell(page, "2044-05-12").click()
    expect(page).to_have_url(re.compile(r"/day/2044-05-12$"))
    expect(page.get_by_test_id("day-events-news-heading")).to_have_text("Economic news · 35")
    expect(page.get_by_test_id("day-events-personal-heading")).to_have_text("Calendar · 3")


def test_the_table_view_lists_every_day_with_events(page: Page, shot):
    open_app(page, f"/calendar?month={MONTH}")
    page.get_by_test_id("view-table").click()
    expect(page.get_by_test_id("daily-news-2044-05-12")).to_have_text("7 high, 4 medium, 24 low")
    expect(page.get_by_test_id("daily-events-2044-05-12")).to_have_text("Bank day off, Floating dinner, Asia session review")
    expect(page.get_by_test_id("daily-news-2044-05-09")).to_have_text("10 low, 2 holidays")
    expect(page.get_by_test_id("daily-news-2044-05-17")).to_have_text("–")  # a day with only a calendar event
    expect(page.get_by_test_id("daily-events-2044-05-17")).to_have_text("Weekly review (moved)")
    expect(page.get_by_test_id("daily-row-2044-05-24")).to_have_count(0)  # nothing on it, and no trades
    # a row for every day that has news or an event, though none has trades
    days_with_something = [day for day in DAYS if day_news(NEWS, day) or day_personal(PERSONAL, day)]
    expect(page.locator("[data-testid^='daily-row-']")).to_have_count(len(days_with_something))
    shot("01-table")


def test_on_a_phone_each_cell_keeps_its_news_level_and_its_marker_without_the_numbers(page: Page, shot):
    page.set_viewport_size({"width": 390, "height": 844})
    open_app(page, f"/calendar?month={MONTH}")
    expect(page.get_by_test_id("news-badge-2044-05-12-high")).to_be_visible()  # the top level only
    for level in ("medium", "low"):
        expect(page.get_by_test_id(f"news-badge-2044-05-12-{level}")).to_have_count(0)
    expect(page.get_by_test_id("news-count-2044-05-12-high")).to_have_count(0)  # no room for the numbers
    expect(page.get_by_test_id("personal-badge-2044-05-12")).to_be_visible()
    expect(page.get_by_test_id("personal-title-2044-05-12")).to_have_count(0)
    expect(cell(page, "2044-05-12")).to_have_attribute("aria-label", re.compile(r"35 news events \(7 high, 4 medium, 24 low\), 3 personal events$"))  # the words are all still there
    shot("01-phone")
    page.get_by_test_id("view-table").click()
    expect(page.get_by_test_id("daily-news-2044-05-12")).to_have_text("7 high, 4 medium, 24 low")  # the table has every number the cells left out
    expect(page.get_by_test_id("daily-events-2044-05-12")).to_have_text("Bank day off, Floating dinner, Asia session review")
    shot("02-phone-table")


def test_a_month_with_no_events_looks_as_it_did_before(page: Page):
    open_app(page, "/calendar?month=2043-01")
    expect(page.get_by_test_id("calendar-heading")).to_have_text("January 2043")
    for hidden in ("calendar-events-summary", "event-filters", "calendar-events-legend"):
        expect(page.get_by_test_id(hidden)).to_have_count(0)
    expect(page.locator("[data-testid^='news-badge-']")).to_have_count(0)
    expect(page.locator("[data-testid^='personal-badge-']")).to_have_count(0)
    expect(cell(page, "2043-01-05")).to_have_attribute("aria-label", re.compile(r"no closed trades$"))
