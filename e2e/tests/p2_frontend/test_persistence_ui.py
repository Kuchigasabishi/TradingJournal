"""Phase 2: what was logged in the UI is still there, in the UI, after the server restarts.

scripts/verify.py runs this module in two passes, like the Phase 1 persistence tests: the first test writes
through the browser, the server is stopped and started again on the same database file, and the
`after_restart` test then reads it back through a fresh browser.
"""
import re

import pytest
from playwright.sync_api import Page, expect

from support.ui import expect_api, open_app, wall_to_utc

INSTRUMENT = "UI-RESTART-CANARY"
NOTE_DAY = "2043-03-03"
NOTE_TEXT = "Written in the browser before the restart."


def test_log_a_trade_and_a_note_in_the_browser_before_the_restart(page: Page, api, shot):
    # Tidy up first, so the test can be re-run against a database that already holds a canary.
    for old in api.get(f"/api/trades?instrument={INSTRUMENT}").json()["items"]:
        api.delete(f"/api/trades/{old['id']}")
    for old in api.get(f"/api/notes?from={NOTE_DAY}&to={NOTE_DAY}").json()["items"]:
        api.delete(f"/api/notes/{old['id']}")

    open_app(page, "/trades/new")
    page.get_by_test_id("field-instrument").fill(INSTRUMENT)
    page.get_by_test_id("field-lot-size").fill("0.01")
    page.get_by_test_id("field-entry-price").fill("190.12345678")
    page.get_by_test_id("field-opened-at").fill("2043-03-03 08:00")
    page.get_by_test_id("field-closed").click()
    page.get_by_test_id("field-exit-price").fill("189.87654321")
    page.get_by_test_id("field-closed-at").fill("2043-03-03 10:30")
    page.get_by_test_id("field-pnl").fill("-0.00000001")
    page.get_by_test_id("field-notes").fill("Written in the browser.")
    with expect_api(page, "POST", r"^/api/trades$") as call:
        page.get_by_test_id("form-submit").click()
    assert call.status == 201
    expect(page.get_by_test_id("detail-pnl")).to_have_text("-$0.00000001")
    shot("01-trade-saved")

    open_app(page, f"/day/{NOTE_DAY}")
    page.get_by_test_id("field-day-note").fill(NOTE_TEXT)
    with expect_api(page, "POST", r"^/api/notes$") as note_call:
        page.get_by_test_id("note-save").click()
    assert note_call.status == 201
    expect(page.get_by_test_id(f"note-body-{note_call.json()['id']}")).to_have_text(NOTE_TEXT)
    shot("02-note-saved")


@pytest.mark.after_restart
def test_the_browser_shows_the_trade_and_the_note_after_the_restart(page: Page, api, shot):
    open_app(page, f"/trades?instrument={INSTRUMENT}")
    rows = page.locator("[data-testid^='trade-row-']")
    expect(rows).to_have_count(1)
    trade_id = int(re.sub(r"\D", "", rows.first.get_attribute("data-testid")))
    expect(page.get_by_test_id(f"trade-lots-{trade_id}")).to_have_text("0.01")
    expect(page.get_by_test_id(f"trade-entry-{trade_id}")).to_have_text("190.12345678")
    expect(page.get_by_test_id(f"trade-exit-{trade_id}")).to_have_text("189.87654321")
    expect(page.get_by_test_id(f"trade-pnl-{trade_id}")).to_have_text("-$0.00000001")
    expect(page.get_by_test_id(f"trade-date-{trade_id}")).to_have_text("2043-03-03")
    shot("01-trade-after-restart")

    page.get_by_test_id(f"trade-link-{trade_id}").click()
    expect(page.get_by_test_id("detail-notes")).to_have_text("Written in the browser.")
    stored = api.get(f"/api/trades/{trade_id}").json()
    assert stored["opened_at"] == wall_to_utc("2043-03-03 08:00") and stored["closed_at"] == wall_to_utc("2043-03-03 10:30")

    open_app(page, "/calendar?month=2043-03")
    expect(page.get_by_test_id("day-pnl-2043-03-03")).to_have_text("-$0.00000001")
    expect(page.get_by_test_id("note-mark-2043-03-03")).to_be_visible()
    page.get_by_test_id("day-2043-03-03").click()
    expect(page.get_by_test_id("day-notes")).to_contain_text(NOTE_TEXT)
    shot("02-calendar-and-note-after-restart")
