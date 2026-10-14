"""Phase 2: the calendar grid shades each day by its P&L on one scale, marks days with notes, and links to the day."""
import re
from datetime import date

import pytest
from playwright.sync_api import Page, expect

from support.ui import day_label, open_app, server_today

MONTH = "2038-08"

# The diverging scale: four steps per arm, lightest first (frontend/src/theme.ts), as the browser reports them.
GAIN = ["rgb(205, 226, 251)", "rgb(134, 182, 239)", "rgb(57, 135, 229)", "rgb(28, 92, 171)"]
LOSS = ["rgb(250, 214, 210)", "rgb(234, 154, 147)", "rgb(215, 88, 83)", "rgb(158, 52, 50)"]
EVEN = "rgb(240, 239, 236)"
INK = "rgb(11, 11, 11)"
WHITE = "rgb(255, 255, 255)"


@pytest.fixture
def august_2038(journal):
    """Six closed trades, the largest day being 100 either way, and notes on three days."""

    def closed(day: str, pnl: str, hour: int = 14) -> None:
        journal.trade(opened_at=f"{day}T{hour - 1:02d}:00:00Z", closed_at=f"{day}T{hour:02d}:00:00Z", pnl=pnl)

    closed("2038-08-03", "40")
    closed("2038-08-05", "-100")
    closed("2038-08-10", "100")
    closed("2038-08-12", "10")
    closed("2038-08-14", "0")
    # 02:30 UTC on the 20th is 22:30 on the 19th in New York: the trade counts on the 19th.
    journal.trade(opened_at="2038-08-20T01:00:00Z", closed_at="2038-08-20T02:30:00Z", pnl="7.5")
    for day in ("2038-08-05", "2038-08-12", "2038-08-25"):
        journal.note(day, f"Note for {day}")
    return journal


def cell(page: Page, day: int):
    return page.get_by_test_id(f"day-{MONTH}-{day:02d}")


def test_each_day_shows_its_pnl_and_is_shaded_on_one_scale(page: Page, august_2038, shot):
    open_app(page, f"/calendar?month={MONTH}")
    expect(page.get_by_test_id("calendar-heading")).to_have_text("August 2038")
    expect(page.get_by_test_id("calendar-summary")).to_have_text("+$57.50 net from 6 trades.")

    # (day, amount shown, background, ink): the largest absolute day (100) takes the darkest step of its colour,
    # smaller days take lighter steps, and a break-even day is the neutral midpoint.
    expected = [
        (3, "+$40.00", GAIN[1], INK),
        (5, "-$100.00", LOSS[3], WHITE),
        (10, "+$100.00", GAIN[3], WHITE),
        (12, "+$10.00", GAIN[0], INK),
        (14, "$0.00", EVEN, INK),
        (19, "+$7.50", GAIN[0], INK),
    ]
    for day, amount, background, ink in expected:
        expect(page.get_by_test_id(f"day-pnl-{MONTH}-{day:02d}")).to_have_text(amount)
        expect(cell(page, day)).to_have_css("background-color", background)
        expect(page.get_by_test_id(f"day-pnl-{MONTH}-{day:02d}")).to_have_css("color", ink)

    # The 20th has no trades of its own: the late trade counted on the 19th.
    expect(page.get_by_test_id(f"day-pnl-{MONTH}-20")).to_have_count(0)
    expect(cell(page, 20)).to_have_css("background-color", "rgb(252, 252, 251)")
    shot("01-heat-map")


def test_the_legend_explains_the_scale(page: Page, august_2038):
    open_app(page, f"/calendar?month={MONTH}")
    for step in range(4):
        expect(page.get_by_test_id(f"legend-gain-{step}")).to_have_css("background-color", GAIN[step])
        expect(page.get_by_test_id(f"legend-loss-{step}")).to_have_css("background-color", LOSS[step])
    expect(page.get_by_test_id("legend-even")).to_have_css("background-color", EVEN)
    expect(page.get_by_test_id("legend-scale")).to_have_text("Darkest shade: $100.00 in a day, the largest this month.")


def test_days_with_notes_carry_a_marker(page: Page, august_2038, shot):
    open_app(page, f"/calendar?month={MONTH}")
    for day in (5, 12, 25):
        expect(page.get_by_test_id(f"note-mark-{MONTH}-{day:02d}")).to_be_visible()
    for day in (3, 10, 14, 19, 20):
        expect(page.get_by_test_id(f"note-mark-{MONTH}-{day:02d}")).to_have_count(0)
    expect(cell(page, 5)).to_have_attribute("aria-label", re.compile(r"1 note$"))
    expect(cell(page, 3)).not_to_have_attribute("aria-label", re.compile(r"note"))


def test_the_first_of_the_month_sits_under_its_weekday(page: Page, august_2038):
    open_app(page, f"/calendar?month={MONTH}")
    first = date(2038, 8, 1)
    box = cell(page, 1).bounding_box()
    headers = page.get_by_test_id("calendar-grid").get_by_role("columnheader")
    expect(headers).to_have_count(7)
    names = [headers.nth(i).inner_text() for i in range(7)]
    assert names == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    under = [name for i, name in enumerate(names) if abs(headers.nth(i).bounding_box()["x"] + headers.nth(i).bounding_box()["width"] / 2 - (box["x"] + box["width"] / 2)) < 4]
    assert under == [first.strftime("%a")]


def test_hovering_a_day_shows_its_figures(page: Page, august_2038, shot):
    open_app(page, f"/calendar?month={MONTH}")
    tooltip = page.get_by_test_id(f"day-tooltip-{MONTH}-05")
    expect(tooltip).to_have_count(0)
    cell(page, 5).hover()
    expect(tooltip).to_be_visible()
    expect(tooltip).to_contain_text(day_label(date(2038, 8, 5)))
    expect(tooltip).to_contain_text("-$100.00")
    expect(tooltip).to_contain_text("1 trade · 0W 1L 0BE")
    expect(tooltip).to_contain_text("1 note")
    shot("01-tooltip")


def test_pressing_a_day_opens_it(page: Page, august_2038):
    open_app(page, f"/calendar?month={MONTH}")
    cell(page, 10).click()
    expect(page).to_have_url(re.compile(rf"/day/{MONTH}-10$"))
    expect(page.get_by_test_id("page-title")).to_have_text(day_label(date(2038, 8, 10)))


def test_the_table_view_lists_trade_days_and_note_only_days(page: Page, august_2038, shot):
    open_app(page, f"/calendar?month={MONTH}")
    page.get_by_test_id("view-table").click()
    rows = page.locator("[data-testid^='daily-row-']")
    expect(rows).to_have_count(7)  # six days with trades, plus the 25th that only has a note
    expect(page.get_by_test_id(f"daily-pnl-{MONTH}-19")).to_have_text("+$7.50")
    expect(page.get_by_test_id(f"daily-note-{MONTH}-25")).to_have_text("Has a note")
    expect(page.get_by_test_id(f"daily-pnl-{MONTH}-25")).to_have_text("–")
    expect(page.get_by_test_id(f"daily-note-{MONTH}-03")).to_have_text("–")
    shot("01-table")


def test_month_navigation_keeps_the_grid_in_step(page: Page, august_2038, shot):
    open_app(page, f"/calendar?month={MONTH}")
    page.get_by_test_id("month-next").click()
    expect(page).to_have_url(re.compile(r"month=2038-09"))
    expect(page.get_by_test_id("calendar-heading")).to_have_text("September 2038")
    expect(page.get_by_test_id("calendar-summary")).to_have_text("No closed trades this month.")
    expect(page.locator("[data-testid^='day-2038-09-']").filter(has_text=re.compile(r"\d")).first).to_be_visible()
    expect(page.get_by_test_id("day-2038-09-30")).to_be_visible()
    expect(page.get_by_test_id("day-2038-09-31")).to_have_count(0)


def test_today_is_outlined_in_the_current_month(page: Page):
    open_app(page, "/calendar")
    today = server_today()
    marked = page.locator("[aria-current='date']")
    expect(marked).to_have_count(1)
    expect(marked).to_have_attribute("data-testid", f"day-{today.isoformat()}")
    expect(marked).to_have_attribute("aria-label", re.compile(r"\(today\)"))


def test_on_a_phone_the_cells_keep_their_meaning_without_the_amounts(page: Page, august_2038, shot):
    page.set_viewport_size({"width": 390, "height": 844})
    open_app(page, f"/calendar?month={MONTH}")
    expect(page.get_by_test_id(f"day-pnl-{MONTH}-05")).to_have_count(0)  # no room for amounts in a narrow cell
    expect(cell(page, 5)).to_have_attribute("aria-label", re.compile(r"-\$100\.00, 1 trade, 1 note"))
    expect(cell(page, 5)).to_have_css("background-color", LOSS[3])
    expect(page.get_by_test_id(f"note-mark-{MONTH}-05")).to_be_visible()
    shot("01-phone")
    page.get_by_test_id("view-table").click()
    expect(page.get_by_test_id(f"daily-pnl-{MONTH}-05")).to_have_text("-$100.00")  # the table has every exact amount
    shot("02-phone-table")
