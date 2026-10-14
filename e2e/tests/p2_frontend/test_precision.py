"""Phase 2: money, prices and lot sizes stay exact in the browser, from the keyboard to the screen and back.

The values here are chosen to break floating point: a double holds about 16 significant digits, and the journal
accepts 18 (ten before the decimal point, eight after). Nothing in the app may round them on the way.
"""
import re

from playwright.sync_api import Page, expect

from support.journal import unique
from support.ui import expect_api, open_app, wall_to_utc

EXTREME = {"lot_size": "0.00000001", "entry_price": "9999999999.99999999", "exit_price": "0.00000001", "pnl": "-9999999999.99999999"}


def create_extreme_trade(page: Page, instrument: str):
    open_app(page, "/trades/new")
    page.get_by_test_id("field-instrument").fill(instrument)
    page.get_by_test_id("field-lot-size").fill(EXTREME["lot_size"])
    page.get_by_test_id("field-entry-price").fill(EXTREME["entry_price"])
    page.get_by_test_id("field-opened-at").fill("2041-03-03 09:00")
    page.get_by_test_id("field-closed").click()
    page.get_by_test_id("field-exit-price").fill(EXTREME["exit_price"])
    page.get_by_test_id("field-closed-at").fill("2041-03-03 10:00")
    page.get_by_test_id("field-pnl").fill(EXTREME["pnl"])
    with expect_api(page, "POST", r"^/api/trades$") as call:
        page.get_by_test_id("form-submit").click()
    return call


def test_extreme_decimals_survive_the_form_the_wire_and_the_database(page: Page, api, journal, shot):
    call = create_extreme_trade(page, unique("PX"))
    journal.track_trade(call.json()["id"])

    # Sent as the exact strings typed ...
    for field, value in EXTREME.items():
        assert call.request_json[field] == value, field
    assert call.request_json["opened_at"] == wall_to_utc("2041-03-03 09:00")
    # ... stored exactly (the server writes the shortest exact form, which these already are) ...
    stored = api.get(f"/api/trades/{call.json()['id']}").json()
    for field, value in EXTREME.items():
        assert stored[field] == value, field
    # ... and shown exactly, with grouping and a currency symbol added but no digit changed.
    expect(page.get_by_test_id("detail-lot-size")).to_have_text("0.00000001")
    expect(page.get_by_test_id("detail-entry-price")).to_have_text("9,999,999,999.99999999")
    expect(page.get_by_test_id("detail-exit-price")).to_have_text("0.00000001")
    expect(page.get_by_test_id("detail-pnl")).to_have_text("-$9,999,999,999.99999999")
    shot("01-detail")


def test_the_table_and_the_edit_form_show_the_same_exact_values(page: Page, api, journal, shot):
    call = create_extreme_trade(page, unique("PX"))
    trade_id = call.json()["id"]
    journal.track_trade(trade_id)

    open_app(page, f"/trades?instrument={call.json()['instrument']}")
    expect(page.get_by_test_id(f"trade-lots-{trade_id}")).to_have_text("0.00000001")
    expect(page.get_by_test_id(f"trade-entry-{trade_id}")).to_have_text("9,999,999,999.99999999")
    expect(page.get_by_test_id(f"trade-pnl-{trade_id}")).to_have_text("-$9,999,999,999.99999999")
    shot("01-table")

    open_app(page, f"/trades/{trade_id}?edit=1")
    expect(page.get_by_test_id("field-lot-size")).to_have_value("0.00000001")
    expect(page.get_by_test_id("field-entry-price")).to_have_value("9999999999.99999999")
    expect(page.get_by_test_id("field-exit-price")).to_have_value("0.00000001")
    expect(page.get_by_test_id("field-pnl")).to_have_value("-9999999999.99999999")


def test_a_change_in_the_last_decimal_place_is_a_change(page: Page, api, journal):
    """A double cannot tell -9999999999.99999999 from -9999999999.99999998, so a float-based diff would send nothing."""
    call = create_extreme_trade(page, unique("PX"))
    trade_id = call.json()["id"]
    journal.track_trade(trade_id)
    open_app(page, f"/trades/{trade_id}?edit=1")

    patches: list[str] = []
    page.on("request", lambda request: patches.append(request.url) if request.method == "PATCH" else None)
    page.get_by_test_id("form-submit").click()  # nothing changed: nothing is sent
    expect(page.get_by_test_id("flash-message")).to_contain_text("Nothing was changed.")
    assert patches == []

    open_app(page, f"/trades/{trade_id}?edit=1")
    page.get_by_test_id("field-pnl").fill("-9999999999.99999998")
    with expect_api(page, "PATCH", rf"^/api/trades/{trade_id}$") as patch:
        page.get_by_test_id("form-submit").click()
    assert patch.request_json == {"pnl": "-9999999999.99999998"}
    assert api.get(f"/api/trades/{trade_id}").json()["pnl"] == "-9999999999.99999998"
    expect(page.get_by_test_id("detail-pnl")).to_have_text("-$9,999,999,999.99999998")


def test_trailing_zeros_the_server_drops_are_put_back_for_reading(page: Page, journal):
    trade = journal.trade(lot_size="0.50", entry_price="1.27400", exit_price="1.2728", pnl="-12.00")
    open_app(page, f"/trades?instrument={trade['instrument']}")
    # The server keeps 0.5, 1.274 and -12 (the shortest exact forms). A trader reads 0.50 lots and pip precision.
    expect(page.get_by_test_id(f"trade-lots-{trade['id']}")).to_have_text("0.50")
    expect(page.get_by_test_id(f"trade-entry-{trade['id']}")).to_have_text("1.2740")
    expect(page.get_by_test_id(f"trade-exit-{trade['id']}")).to_have_text("1.2728")
    expect(page.get_by_test_id(f"trade-pnl-{trade['id']}")).to_have_text("-$12.00")


def test_sums_of_float_unfriendly_amounts_come_out_exactly(page: Page, journal, shot):
    """0.1 + 0.2 - 0.3 is 5.55e-17 in floating point and exactly 0 here."""
    for index, pnl in enumerate(("0.1", "0.2", "-0.3")):
        journal.trade(instrument=unique("FL"), opened_at="2041-01-15T13:00:00Z", closed_at=f"2041-01-15T{14 + index}:00:00Z", pnl=pnl)
    open_app(page, "/day/2041-01-15")
    expect(page.get_by_test_id("day-net-value")).to_have_text("$0.00")
    expect(page.get_by_test_id("day-net-mark")).to_have_count(0)
    expect(page.get_by_test_id("day-net-caption")).to_have_text("3 trades closed")
    expect(page.get_by_test_id("day-closed-caption")).to_have_text("2 wins · 1 loss · 0 breakeven")
    shot("01-day-net-zero")

    open_app(page, "/calendar?month=2041-01")
    expect(page.get_by_test_id("day-pnl-2041-01-15")).to_have_text("$0.00")
    expect(page.get_by_test_id("day-2041-01-15").get_by_role("img", name="break-even")).to_be_visible()
    open_app(page, "/?month=2041-01")
    expect(page.get_by_test_id("stat-net-value")).to_have_text("$0.00")
    expect(page).to_have_url(re.compile(r"month=2041-01"))
