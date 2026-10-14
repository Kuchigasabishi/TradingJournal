"""Phase 2: the trades table filters, sorts and pages, with the whole state in the address and exact queries on the wire."""
import re
import uuid

import pytest
from playwright.sync_api import Page, expect

from support.journal import unique
from support.ui import expect_api, open_app

PAGE_SIZE = 25
COUNT = 27  # one more page than fits, so there is a second page to visit


@pytest.fixture
def lot(journal):
    """27 closed trades in January 2040 that share one tag. Trade i closed on day i+1 with P&L i+1, long when i is even."""
    token = uuid.uuid4().hex[:6].upper()
    tag = unique("PG")
    trades = []
    for i in range(COUNT):
        day = i + 1
        trades.append(
            journal.trade(
                instrument=f"PG{i:02d}-{token}",
                side="long" if i % 2 == 0 else "short",
                pnl=str(i + 1),
                opened_at=f"2040-01-{day:02d}T13:00:00Z",
                closed_at=f"2040-01-{day:02d}T15:00:00Z",
                tags=[tag],
            )
        )
    return {"tag": tag, "token": token, "trades": trades}


def rows(page: Page):
    return page.locator("[data-testid^='trade-row-']")


def test_the_table_pages_through_the_results(page: Page, lot, shot):
    open_app(page, f"/trades?tag={lot['tag']}")
    expect(page.get_by_test_id("pager-range")).to_have_text(f"1–{PAGE_SIZE} of {COUNT}")
    expect(page.get_by_test_id("pager-page")).to_have_text("Page 1 of 2")
    expect(rows(page)).to_have_count(PAGE_SIZE)
    expect(page.get_by_test_id("pager-prev")).to_be_disabled()
    # Newest first by default: the trade closed on the 27th leads.
    newest = lot["trades"][-1]
    expect(rows(page).first).to_have_attribute("data-testid", f"trade-row-{newest['id']}")
    expect(page.get_by_test_id(f"trade-date-{newest['id']}")).to_have_text("2040-01-27")
    shot("01-first-page")

    with expect_api(page, "GET", r"^/api/trades$", {"offset": str(PAGE_SIZE)}) as call:
        page.get_by_test_id("pager-next").click()
    assert call.query["offset"] == [str(PAGE_SIZE)] and call.query["limit"] == [str(PAGE_SIZE)]
    assert call.request_id.startswith("web-")
    expect(page).to_have_url(re.compile(r"page=2"))
    expect(page.get_by_test_id("pager-range")).to_have_text(f"{PAGE_SIZE + 1}–{COUNT} of {COUNT}")
    expect(rows(page)).to_have_count(COUNT - PAGE_SIZE)
    expect(page.get_by_test_id("pager-next")).to_be_disabled()
    shot("02-second-page")

    page.get_by_test_id("pager-prev").click()
    expect(page.get_by_test_id("pager-range")).to_have_text(f"1–{PAGE_SIZE} of {COUNT}")
    expect(page).not_to_have_url(re.compile(r"page="))


def test_a_page_past_the_end_offers_the_last_page(page: Page, lot, shot):
    open_app(page, f"/trades?tag={lot['tag']}&page=9")
    expect(page.get_by_test_id("trades-past-end")).to_be_visible()
    shot("01-past-the-end")
    page.get_by_test_id("trades-last-page").click()
    expect(page).to_have_url(re.compile(r"page=2"))
    expect(rows(page)).to_have_count(COUNT - PAGE_SIZE)


def test_sorting_by_pnl_toggles_direction_and_is_sent_to_the_server(page: Page, lot, shot):
    open_app(page, f"/trades?tag={lot['tag']}")
    expect(page.get_by_test_id("sort-journal_at-arrow")).to_have_text("↓")

    with expect_api(page, "GET", r"^/api/trades$", {"sort": "pnl", "order": "desc"}) as call:
        page.get_by_test_id("sort-pnl").click()
    assert call.query["sort"] == ["pnl"] and call.query["order"] == ["desc"]
    expect(page.get_by_test_id("sort-pnl-arrow")).to_have_text("↓")
    expect(page.get_by_test_id(f"trade-pnl-{lot['trades'][-1]['id']}")).to_have_text("+$27.00")
    expect(rows(page).first).to_have_attribute("data-testid", f"trade-row-{lot['trades'][-1]['id']}")
    shot("01-biggest-first")

    with expect_api(page, "GET", r"^/api/trades$", {"sort": "pnl", "order": "asc"}) as call:
        page.get_by_test_id("sort-pnl").click()
    assert call.query["sort"] == ["pnl"] and call.query["order"] == ["asc"]
    expect(page).to_have_url(re.compile(r"sort=pnl&order=asc|order=asc&sort=pnl"))
    expect(page.get_by_test_id("sort-pnl-arrow")).to_have_text("↑")
    expect(rows(page).first).to_have_attribute("data-testid", f"trade-row-{lot['trades'][0]['id']}")
    expect(page.get_by_test_id("sort-journal_at-arrow")).to_have_text("")


def test_filters_narrow_the_table_and_each_is_sent_as_a_query_parameter(page: Page, lot, shot):
    open_app(page, f"/trades?tag={lot['tag']}")

    with expect_api(page, "GET", r"^/api/trades$", {"side": "short"}) as call:
        page.get_by_test_id("filter-side-short").click()
    assert call.query["side"] == ["short"] and call.query["tag"] == [lot["tag"]]
    expect(page.get_by_test_id("pager-range")).to_have_text("1–13 of 13")  # odd i are short: 13 of 27
    expect(page).to_have_url(re.compile(r"side=short"))

    page.get_by_test_id("filter-side-long").click()
    expect(page.get_by_test_id("pager-range")).to_have_text("1–14 of 14")
    page.get_by_test_id("filter-side-any").click()
    expect(page.get_by_test_id("pager-range")).to_have_text(f"1–{PAGE_SIZE} of {COUNT}")

    # From and to are inclusive days: the 10th, 11th and 12th hold three trades.
    page.get_by_test_id("filter-from").fill("2040-01-10")
    page.get_by_test_id("filter-to").fill("2040-01-12")
    with expect_api(page, "GET", r"^/api/trades$", {"from": "2040-01-10", "to": "2040-01-12"}) as call:
        page.get_by_test_id("filters-apply").click()
    assert call.query["from"] == ["2040-01-10"] and call.query["to"] == ["2040-01-12"]
    expect(page.get_by_test_id("pager-range")).to_have_text("1–3 of 3")
    shot("01-date-range")

    page.get_by_test_id("filter-from").fill("")
    page.get_by_test_id("filter-to").fill("")
    page.get_by_test_id("filter-instrument").fill(f"pg05-{lot['token']}".lower())  # matching ignores case
    page.get_by_test_id("filters-apply").click()
    expect(rows(page)).to_have_count(1)
    expect(page.get_by_test_id(f"trade-link-{lot['trades'][5]['id']}")).to_have_text(f"PG05-{lot['token']}")
    expect(page).to_have_url(re.compile(r"instrument="))


def test_a_filter_with_no_matches_says_so_and_clearing_recovers(page: Page, lot, shot):
    open_app(page, f"/trades?tag={lot['tag']}")
    page.get_by_test_id("filter-status-open").click()  # every trade in the lot is closed
    expect(page.get_by_test_id("trades-empty")).to_contain_text("No trades match these filters")
    shot("01-no-matches")
    page.get_by_test_id("trades-empty-clear").click()
    expect(page).not_to_have_url(re.compile(r"status=|tag="))
    expect(rows(page).first).to_be_visible()
    expect(page.get_by_test_id("filters-clear")).to_be_disabled()


def test_a_bad_date_is_explained_and_nothing_is_requested(page: Page, lot):
    requests: list[str] = []
    open_app(page, "/trades")
    page.on("request", lambda request: requests.append(request.url) if "/api/trades?" in request.url else None)
    page.get_by_test_id("filter-from").fill("2040-13-45")
    page.get_by_test_id("filters-apply").click()
    expect(page.get_by_test_id("filter-from-error")).to_contain_text("Use YYYY-MM-DD.")
    page.get_by_test_id("filter-from").fill("2040-01-20")
    page.get_by_test_id("filter-to").fill("2040-01-10")
    page.get_by_test_id("filters-apply").click()
    expect(page.get_by_test_id("filter-to-error")).to_contain_text("Must not be before the first day.")
    assert requests == [], "a filter the form knows is wrong is never sent"
    expect(page).not_to_have_url(re.compile(r"from="))


def test_tag_chips_filter_and_a_deep_link_restores_every_control(page: Page, lot, shot):
    open_app(page, "/trades")
    chip = page.get_by_test_id(f"filter-tag-{lot['tag']}")
    expect(chip).to_have_attribute("aria-pressed", "false")
    chip.click()
    expect(chip).to_have_attribute("aria-pressed", "true")
    expect(page).to_have_url(re.compile(rf"tag={lot['tag']}"))
    expect(page.get_by_test_id("pager-range")).to_have_text(f"1–{PAGE_SIZE} of {COUNT}")

    open_app(page, f"/trades?status=closed&side=long&tag={lot['tag']}&sort=pnl&order=asc")
    expect(page.get_by_test_id("filter-status-closed")).to_have_attribute("aria-checked", "true")
    expect(page.get_by_test_id("filter-status-all")).to_have_attribute("aria-checked", "false")
    expect(page.get_by_test_id("filter-side-long")).to_have_attribute("aria-checked", "true")
    expect(page.get_by_test_id(f"filter-tag-{lot['tag']}")).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_test_id("sort-pnl-arrow")).to_have_text("↑")
    expect(page.get_by_test_id("pager-range")).to_have_text("1–14 of 14")
    expect(page.get_by_test_id(f"trade-pnl-{lot['trades'][0]['id']}")).to_have_text("+$1.00")
    shot("01-restored-from-the-address")


def test_two_tags_narrow_to_the_trades_that_carry_both_and_the_address_keeps_them(page: Page, journal, shot):
    """The router writes a list parameter as one comma-joined value (tag=a%2Cb). Found in Phase 3, which filters its events the
    same way: the page must read that back as two tags, not as one tag with a comma in it."""
    first, second = unique("PG"), unique("PG")
    times = {"opened_at": "2040-02-01T13:00:00Z", "closed_at": "2040-02-01T15:00:00Z"}
    journal.trade(tags=[first], **times)
    both = journal.trade(tags=[first, second], **times)
    journal.trade(tags=[second], **times)

    open_app(page, "/trades")
    page.get_by_test_id(f"filter-tag-{first}").click()
    expect(rows(page)).to_have_count(2)  # the trades with the first tag
    page.get_by_test_id(f"filter-tag-{second}").click()
    expect(page).to_have_url(re.compile(rf"tag={first}(%2C|,){second}|tag={second}(%2C|,){first}"))
    expect(rows(page)).to_have_count(1)  # a trade must carry all of them
    expect(rows(page).first).to_have_attribute("data-testid", f"trade-row-{both['id']}")
    shot("01-two-tags")

    page.reload()
    expect(page.get_by_test_id(f"filter-tag-{first}")).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_test_id(f"filter-tag-{second}")).to_have_attribute("aria-pressed", "true")
    expect(rows(page)).to_have_count(1)
