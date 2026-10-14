"""Phase 2: trades are created, edited and deleted through the UI, and the network traffic is exactly what it should be.

Every write is checked three ways: what the browser sent (the request body, exact strings), what the server
answered, and what the API holds afterwards. Times are typed in the server's zone (America/New_York) while the
browser runs in UTC, so a wrong conversion cannot hide.
"""
import re

import pytest
from playwright.sync_api import Page, expect

from support.journal import unique
from support.ui import expect_api, open_app, trade_id_from_url, utc_to_wall, wall_to_utc


def fill_trade(page: Page, instrument: str, *, opened: str, closed: str | None = None, pnl: str = "14.30") -> None:
    page.get_by_test_id("field-instrument").fill(instrument.lower())  # lower case on purpose: the form upper-cases it
    page.get_by_test_id("side-short").click()
    page.get_by_test_id("field-lot-size").fill("0.10")
    page.get_by_test_id("field-entry-price").fill("1.08543")
    page.get_by_test_id("field-opened-at").fill(opened)
    if closed is not None:
        page.get_by_test_id("field-closed").click()
        page.get_by_test_id("field-exit-price").fill("1.08400")
        page.get_by_test_id("field-closed-at").fill(closed)
        page.get_by_test_id("field-pnl").fill(pnl)


# --- create --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("opened", "closed"),
    [("2039-01-12 09:30", "2039-01-12 11:45"), ("2039-07-12 09:30", "2039-07-12 11:45")],
    ids=["winter-EST", "summer-EDT"],
)
def test_a_trade_is_logged_through_the_form(page: Page, api, journal, shot, opened: str, closed: str):
    instrument = unique("UI")
    open_app(page, "/trades")
    page.get_by_test_id("trades-new").click()
    expect(page).to_have_url(re.compile(r"/trades/new$"))
    shot("01-empty-form")

    fill_trade(page, instrument, opened=opened, closed=closed)
    expect(page.get_by_test_id("field-closed-at")).to_have_value(closed)
    page.get_by_test_id("field-notes").fill("Faded the London high.")
    tags = page.get_by_test_id("field-tags-input")
    for tag in ("ui-e2e", "Second Tag"):
        tags.fill(tag)
        tags.press("Enter")
    expect(page.get_by_test_id("tag-chip-ui-e2e")).to_be_visible()
    expect(page.get_by_test_id("tag-chip-Second Tag")).to_be_visible()
    shot("02-filled-form")

    with expect_api(page, "POST", r"^/api/trades$") as call:
        page.get_by_test_id("form-submit").click()

    # What the browser sent: decimals as the exact strings typed, instants converted from New York to UTC.
    assert call.request_json == {
        "instrument": instrument,
        "side": "short",
        "lot_size": "0.10",
        "entry_price": "1.08543",
        "opened_at": wall_to_utc(opened),
        "exit_price": "1.08400",
        "closed_at": wall_to_utc(closed),
        "pnl": "14.30",
        "notes": "Faded the London high.",
        "tags": ["ui-e2e", "Second Tag"],
    }
    assert call.request_id.startswith("web-"), "requests from the app carry a web- request id"
    assert call.status == 201
    created = call.json()
    journal.track_trade(created["id"])

    # What the server holds afterwards, read back through the API.
    stored = api.get(f"/api/trades/{created['id']}").json()
    assert (stored["lot_size"], stored["pnl"], stored["opened_at"], stored["closed_at"]) == ("0.1", "14.3", wall_to_utc(opened), wall_to_utc(closed))
    assert stored["status"] == "closed" and stored["tags"] == ["Second Tag", "ui-e2e"]

    # What the person sees: the saved trade, with the confirmation.
    expect(page).to_have_url(re.compile(rf"/trades/{created['id']}$"))
    expect(page.get_by_test_id("flash-message")).to_contain_text("Trade saved.")
    expect(page.get_by_test_id("trade-title")).to_have_text(instrument)
    expect(page.get_by_test_id("trade-side")).to_have_text("Short")
    expect(page.get_by_test_id("trade-status")).to_have_text("Closed")
    expect(page.get_by_test_id("detail-pnl")).to_have_text("+$14.30")
    expect(page.get_by_test_id("detail-lot-size")).to_have_text("0.10")
    expect(page.get_by_test_id("detail-entry-price")).to_have_text("1.08543")
    expect(page.get_by_test_id("detail-exit-price")).to_have_text("1.08400")
    expect(page.get_by_test_id("detail-opened")).to_have_text(opened)
    expect(page.get_by_test_id("detail-closed")).to_have_text(closed)
    expect(page.get_by_test_id("detail-notes")).to_have_text("Faded the London high.")
    expect(page.get_by_test_id("detail-tag-ui-e2e")).to_be_visible()
    shot("03-saved")

    # It shows up in the list, found by instrument.
    page.get_by_test_id("back-link").click()
    page.get_by_test_id("filter-instrument").fill(instrument)
    page.get_by_test_id("filters-apply").click()
    row = page.get_by_test_id(f"trade-row-{created['id']}")
    expect(row).to_be_visible()
    expect(page.get_by_test_id(f"trade-pnl-{created['id']}")).to_have_text("+$14.30")
    expect(page.get_by_test_id(f"trade-date-{created['id']}")).to_have_text(closed.split(" ")[0])
    shot("04-in-the-list")


def test_an_open_trade_is_logged_without_closing_fields(page: Page, journal):
    instrument = unique("UI")
    open_app(page, "/trades/new")
    fill_trade(page, instrument, opened="2039-02-03 08:15")
    expect(page.get_by_test_id("field-exit-price")).to_have_count(0)
    with expect_api(page, "POST", r"^/api/trades$") as call:
        page.get_by_test_id("form-submit").click()
    journal.track_trade(call.json()["id"])
    assert call.status == 201
    assert call.request_json["exit_price"] is None and call.request_json["closed_at"] is None and call.request_json["pnl"] is None
    expect(page.get_by_test_id("trade-status")).to_have_text("Open")
    expect(page.get_by_test_id("detail-pnl")).to_have_count(0)
    expect(page.get_by_test_id("detail-exit-price")).to_have_text("–")


def test_a_closed_toggle_left_behind_does_not_leak_closing_values(page: Page, journal):
    """Typing closing values and then turning "closed" off must send a plain open trade."""
    instrument = unique("UI")
    open_app(page, "/trades/new")
    fill_trade(page, instrument, opened="2039-02-04 08:15", closed="2039-02-04 09:15")
    page.get_by_test_id("field-closed").click()
    with expect_api(page, "POST", r"^/api/trades$") as call:
        page.get_by_test_id("form-submit").click()
    journal.track_trade(call.json()["id"])
    assert call.request_json["exit_price"] is None and call.request_json["closed_at"] is None and call.request_json["pnl"] is None


def test_a_day_link_starts_the_form_on_that_day(page: Page):
    open_app(page, "/trades/new?day=2039-05-17")
    expect(page.get_by_test_id("field-opened-at")).to_have_value("2039-05-17 09:00")
    expect(page.get_by_test_id("back-link")).to_have_text("← Back to the day")


# --- validation, before and after the server ------------------------------------------------------


def test_the_form_explains_mistakes_before_anything_is_sent(page: Page, shot):
    posts: list[str] = []
    page.on("request", lambda request: posts.append(request.url) if request.method == "POST" else None)
    open_app(page, "/trades/new")

    page.get_by_test_id("form-submit").click()
    expect(page.get_by_test_id("field-instrument-error")).to_contain_text("Enter the instrument, for example EURUSD.")
    expect(page.get_by_test_id("field-lot-size-error")).to_contain_text("Enter the lot size.")
    expect(page.get_by_test_id("field-entry-price-error")).to_contain_text("Enter the entry price.")
    expect(page.get_by_test_id("form-summary")).to_contain_text("3 fields need attention.")
    shot("01-empty-submit")

    page.get_by_test_id("field-instrument").fill("EURUSD")
    page.get_by_test_id("field-entry-price").fill("1.1")
    lot_mistakes = [
        ("0.123456789", "At most 8 decimal places."),
        ("12345678901", "At most 10 digits before the decimal point."),
        ("-1", "Enter a positive number."),
        ("0", "Must be greater than zero."),
        ("abc", "Use digits and one decimal point, for example 0.10."),
    ]
    for text, message in lot_mistakes:
        page.get_by_test_id("field-lot-size").fill(text)
        page.get_by_test_id("form-submit").click()
        expect(page.get_by_test_id("field-lot-size-error")).to_contain_text(message)
    page.get_by_test_id("field-lot-size").fill("0.10")

    page.get_by_test_id("field-opened-at").fill("yesterday afternoon")
    page.get_by_test_id("form-submit").click()
    expect(page.get_by_test_id("field-opened-at-error")).to_contain_text("Use YYYY-MM-DD HH:mm (America/New_York), for example 2035-03-10 14:30.")
    # 02:30 on 13 March 2039 never happens in New York: the clocks jump from 02:00 to 03:00.
    page.get_by_test_id("field-opened-at").fill("2039-03-13 02:30")
    page.get_by_test_id("form-submit").click()
    expect(page.get_by_test_id("field-opened-at-error")).to_contain_text("That time does not exist in America/New_York: clocks skip it when they spring forward.")

    page.get_by_test_id("field-opened-at").fill("2039-05-02 10:00")
    page.get_by_test_id("field-closed").click()
    page.get_by_test_id("field-closed-at").fill("2039-05-02 09:00")
    page.get_by_test_id("form-submit").click()
    expect(page.get_by_test_id("field-exit-price-error")).to_contain_text("Enter the exit price.")
    expect(page.get_by_test_id("field-closed-at-error")).to_contain_text("The close must not be before the open.")
    expect(page.get_by_test_id("field-pnl-error")).to_contain_text("Enter the realized P&L.")
    shot("02-closing-mistakes")

    assert posts == [], f"nothing should have been sent, but: {posts}"


@pytest.mark.allow_console_errors(r"status of 422", r"status of 500", r"^HTTP 500", reason="the test makes the server reject the request")
def test_a_server_rejection_lands_on_the_field_it_names(page: Page, journal, shot):
    rejection = {"detail": [{"loc": ["body", "lot_size"], "msg": "Lot size is not acceptable to the broker.", "type": "value_error"}]}
    page.route(re.compile(r"/api/trades$"), lambda route: route.fulfill(status=422, json=rejection) if route.request.method == "POST" else route.fallback())
    open_app(page, "/trades/new")
    fill_trade(page, unique("UI"), opened="2039-06-01 08:00")
    page.get_by_test_id("form-submit").click()
    expect(page.get_by_test_id("field-lot-size-error")).to_contain_text("Lot size is not acceptable to the broker.")
    expect(page).to_have_url(re.compile(r"/trades/new$"))
    shot("01-field-error-from-the-server")

    # A rejection with no field to blame becomes a message above the buttons, and the form keeps what was typed.
    page.unroute(re.compile(r"/api/trades$"))
    page.route(re.compile(r"/api/trades$"), lambda route: route.fulfill(status=500, json={"detail": "The database is busy."}) if route.request.method == "POST" else route.fallback())
    page.get_by_test_id("form-submit").click()
    expect(page.get_by_test_id("form-error")).to_contain_text("The database is busy.")
    expect(page.get_by_test_id("field-lot-size")).to_have_value("0.10")
    shot("02-general-error")

    # The server recovers; the same form saves without retyping.
    page.unroute(re.compile(r"/api/trades$"))
    with expect_api(page, "POST", r"^/api/trades$") as call:
        page.get_by_test_id("form-submit").click()
    assert call.status == 201
    journal.track_trade(call.json()["id"])
    expect(page.get_by_test_id("trade-view")).to_be_visible()


# --- edit ------------------------------------------------------------------------------------------


def test_editing_sends_only_what_changed(page: Page, api, journal, shot):
    trade = journal.trade(notes="First draft", tags=["edit-me"])
    open_app(page, f"/trades/{trade['id']}")
    page.get_by_test_id("detail-edit").click()
    expect(page).to_have_url(re.compile(r"\?edit=1$"))

    # The form starts from the stored trade: padded for reading (0.10), converted to New York time.
    expect(page.get_by_test_id("field-lot-size")).to_have_value("0.10")
    expect(page.get_by_test_id("field-entry-price")).to_have_value("1.08543")
    expect(page.get_by_test_id("field-exit-price")).to_have_value("1.08821")
    expect(page.get_by_test_id("field-pnl")).to_have_value("27.80")
    expect(page.get_by_test_id("field-opened-at")).to_have_value(utc_to_wall(trade["opened_at"]))
    expect(page.get_by_test_id("field-closed-at")).to_have_value(utc_to_wall(trade["closed_at"]))
    expect(page.get_by_test_id("field-notes")).to_have_value("First draft")
    expect(page.get_by_test_id("tag-chip-edit-me")).to_be_visible()
    shot("01-edit-form")

    page.get_by_test_id("field-exit-price").fill("1.09000")
    page.get_by_test_id("field-pnl").fill("45.5")
    with expect_api(page, "PATCH", rf"^/api/trades/{trade['id']}$") as call:
        page.get_by_test_id("form-submit").click()
    assert call.request_json == {"exit_price": "1.09000", "pnl": "45.5"}, "only the two changed fields are sent"
    assert call.status == 200 and call.request_id.startswith("web-")

    expect(page.get_by_test_id("flash-message")).to_contain_text("Trade updated.")
    expect(page.get_by_test_id("detail-pnl")).to_have_text("+$45.50")
    expect(page.get_by_test_id("detail-exit-price")).to_have_text("1.09000")
    expect(page.get_by_test_id("detail-notes")).to_have_text("First draft")  # untouched fields survive
    stored = api.get(f"/api/trades/{trade['id']}").json()
    assert (stored["exit_price"], stored["pnl"], stored["notes"], stored["tags"]) == ("1.09", "45.5", "First draft", ["edit-me"])
    shot("02-updated")


def test_saving_without_changes_sends_nothing(page: Page, journal):
    trade = journal.trade()
    patches: list[str] = []
    page.on("request", lambda request: patches.append(request.url) if request.method == "PATCH" else None)
    open_app(page, f"/trades/{trade['id']}?edit=1")
    expect(page.get_by_test_id("field-pnl")).to_have_value("27.80")
    page.get_by_test_id("form-submit").click()
    expect(page.get_by_test_id("flash-message")).to_contain_text("Nothing was changed.")
    expect(page).to_have_url(re.compile(rf"/trades/{trade['id']}$"))
    assert patches == []


def test_a_closed_trade_can_be_reopened_and_closed_again(page: Page, api, journal, shot):
    trade = journal.trade()
    open_app(page, f"/trades/{trade['id']}?edit=1")

    page.get_by_test_id("field-closed").click()  # off
    with expect_api(page, "PATCH", rf"^/api/trades/{trade['id']}$") as call:
        page.get_by_test_id("form-submit").click()
    assert call.request_json == {"exit_price": None, "closed_at": None, "pnl": None}, "clearing is an explicit null"
    expect(page.get_by_test_id("trade-status")).to_have_text("Open")
    expect(page.get_by_test_id("detail-pnl")).to_have_count(0)
    assert api.get(f"/api/trades/{trade['id']}").json()["status"] == "open"
    shot("01-reopened")

    page.get_by_test_id("detail-edit").click()
    page.get_by_test_id("field-closed").click()  # on
    page.get_by_test_id("field-exit-price").fill("1.0777")
    page.get_by_test_id("field-closed-at").fill("2030-05-06 11:00")
    page.get_by_test_id("field-pnl").fill("-3.25")
    with expect_api(page, "PATCH", rf"^/api/trades/{trade['id']}$") as call:
        page.get_by_test_id("form-submit").click()
    assert call.request_json == {"exit_price": "1.0777", "closed_at": wall_to_utc("2030-05-06 11:00"), "pnl": "-3.25"}
    expect(page.get_by_test_id("trade-status")).to_have_text("Closed")
    expect(page.get_by_test_id("detail-pnl")).to_have_text("-$3.25")
    shot("02-closed-again")


def test_the_edit_link_in_the_list_opens_the_form(page: Page, journal):
    trade = journal.trade()
    open_app(page, f"/trades?instrument={trade['instrument']}")
    page.get_by_test_id(f"trade-edit-{trade['id']}").click()
    expect(page).to_have_url(re.compile(rf"/trades/{trade['id']}\?edit=1$"))
    expect(page.get_by_test_id("form-submit")).to_have_text("Save changes")


# --- delete ----------------------------------------------------------------------------------------


def test_a_trade_is_deleted_from_the_list_only_after_confirming(page: Page, api, journal, shot):
    trade = journal.trade()
    open_app(page, f"/trades?instrument={trade['instrument']}")
    row = page.get_by_test_id(f"trade-row-{trade['id']}")
    expect(row).to_be_visible()

    page.get_by_test_id(f"trade-delete-{trade['id']}").click()
    dialog = page.get_by_test_id("delete-trade-dialog")
    expect(dialog).to_contain_text(trade["instrument"])
    shot("01-confirm")
    page.get_by_test_id("delete-trade-dialog-cancel").click()
    expect(dialog).to_have_count(0)
    expect(row).to_be_visible()
    assert api.get(f"/api/trades/{trade['id']}").status == 200, "cancelling deletes nothing"

    page.get_by_test_id(f"trade-delete-{trade['id']}").click()
    with expect_api(page, "DELETE", rf"^/api/trades/{trade['id']}$") as call:
        page.get_by_test_id("delete-trade-dialog-confirm").click()
    assert call.status == 204 and call.request_id.startswith("web-")
    expect(page.get_by_test_id("flash-message")).to_contain_text(f"Deleted the {trade['instrument']} trade.")
    expect(row).to_have_count(0)
    expect(page.get_by_test_id("trades-empty")).to_contain_text("No trades match these filters")
    assert api.get(f"/api/trades/{trade['id']}").status == 404
    journal.forget_trade(trade["id"])
    shot("02-deleted")


def test_a_trade_is_deleted_from_its_own_page(page: Page, api, journal):
    trade = journal.trade()
    open_app(page, f"/trades/{trade['id']}")
    page.get_by_test_id("detail-delete").click()
    with expect_api(page, "DELETE", rf"^/api/trades/{trade['id']}$") as call:
        page.get_by_test_id("delete-trade-dialog-confirm").click()
    assert call.status == 204
    expect(page).to_have_url(re.compile(r"/trades$"))
    expect(page.get_by_test_id("flash-message")).to_contain_text("Deleted")
    assert api.get(f"/api/trades/{trade['id']}").status == 404
    journal.forget_trade(trade["id"])


@pytest.mark.allow_console_errors(r"status of 500", r"^HTTP 500", reason="the test makes the delete request fail")
def test_a_failed_delete_keeps_the_row_and_says_why(page: Page, api, journal, shot):
    trade = journal.trade()
    open_app(page, f"/trades?instrument={trade['instrument']}")
    page.route(re.compile(rf"/api/trades/{trade['id']}$"), lambda route: route.fulfill(status=500, json={"detail": "Disk is full."}) if route.request.method == "DELETE" else route.fallback())
    page.get_by_test_id(f"trade-delete-{trade['id']}").click()
    page.get_by_test_id("delete-trade-dialog-confirm").click()
    expect(page.get_by_test_id("flash-message")).to_contain_text("Disk is full.")
    expect(page.get_by_test_id(f"trade-row-{trade['id']}")).to_be_visible()
    assert api.get(f"/api/trades/{trade['id']}").status == 200
    shot("01-delete-failed")
    page.get_by_test_id("flash-message-dismiss").click()
    expect(page.get_by_test_id("flash-message")).to_have_count(0)


def test_the_trade_id_in_the_address_matches_the_saved_trade(page: Page, journal):
    """A guard for the helper the other tests lean on."""
    trade = journal.trade()
    open_app(page, f"/trades/{trade['id']}")
    assert trade_id_from_url(page) == trade["id"]
