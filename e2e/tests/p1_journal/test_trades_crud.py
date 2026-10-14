"""Phase 1: trade CRUD through the real server. Every write is read back from the database."""
import pytest
from support.journal import BASE, unique


def test_create_returns_201_with_a_location_header_and_a_request_id(api, journal):
    response = api.post("/api/trades", data={"instrument": unique(), **BASE})
    assert response.status == 201
    body = response.json()
    journal.track_trade(body["id"])
    assert response.headers["location"] == f"/api/trades/{body['id']}"
    assert response.headers["x-request-id"]


def test_a_trade_round_trips_through_the_database_unchanged(api, journal):
    created = journal.trade(notes="Breakout retest", tags=["Breakout", "london"])
    stored = api.get(f"/api/trades/{created['id']}").json()
    assert stored == created
    assert (stored["status"], stored["side"]) == ("closed", "long")
    assert (stored["lot_size"], stored["entry_price"], stored["exit_price"], stored["pnl"]) == ("0.1", "1.08543", "1.08821", "27.8")
    assert (stored["opened_at"], stored["closed_at"]) == ("2030-05-06T09:00:00Z", "2030-05-06T13:30:00Z")
    assert stored["notes"] == "Breakout retest" and stored["tags"] == ["Breakout", "london"]


def test_input_is_normalized_before_it_is_stored(api, journal):
    token = unique("N")
    created = journal.trade(
        instrument=f" {token.lower()} ",
        side="SHORT",
        opened_at="2030-05-06T11:00:00+02:00",
        closed_at="2030-05-06T09:30:00-04:00",
        tags=["Breakout", "  breakout ", "london  open"],
        notes="  padded  ",
    )
    assert (created["instrument"], created["side"]) == (token, "short")
    assert (created["opened_at"], created["closed_at"]) == ("2030-05-06T09:00:00Z", "2030-05-06T13:30:00Z")
    assert created["tags"] == ["Breakout", "london open"] and created["notes"] == "padded"
    assert api.get(f"/api/trades/{created['id']}").json() == created


def test_an_open_trade_is_stored_without_closing_fields(api, journal):
    created = journal.open_trade()
    stored = api.get(f"/api/trades/{created['id']}").json()
    assert stored == created and stored["status"] == "open"
    assert (stored["exit_price"], stored["closed_at"], stored["pnl"]) == (None, None, None)


def test_patch_changes_only_what_was_sent_and_the_change_is_read_back(api, journal):
    created = journal.trade(notes="before", tags=["a"])
    response = api.patch(f"/api/trades/{created['id']}", data={"pnl": "-3.25", "notes": "after", "tags": ["b", "c"]})
    assert response.status == 200
    patched = response.json()
    assert (patched["pnl"], patched["notes"], patched["tags"]) == ("-3.25", "after", ["b", "c"])
    untouched = ("id", "instrument", "side", "lot_size", "entry_price", "exit_price", "opened_at", "closed_at", "status", "created_at")
    assert {k: patched[k] for k in untouched} == {k: created[k] for k in untouched}
    assert api.get(f"/api/trades/{created['id']}").json() == patched


def test_a_trade_can_be_reopened_and_closed_again(api, journal):
    created = journal.trade()
    url = f"/api/trades/{created['id']}"
    reopened = api.patch(url, data={"exit_price": None, "closed_at": None, "pnl": None}).json()
    assert (reopened["status"], reopened["pnl"], reopened["exit_price"], reopened["closed_at"]) == ("open", None, None, None)
    closed = api.patch(url, data={"exit_price": "1.1", "closed_at": "2030-05-06T15:00:00Z", "pnl": "5"}).json()
    assert (closed["status"], closed["pnl"], closed["exit_price"]) == ("closed", "5", "1.1")
    assert api.get(url).json() == closed


def test_null_clears_notes_but_never_a_required_field(api, journal):
    created = journal.trade(notes="remove me")
    url = f"/api/trades/{created['id']}"
    assert api.patch(url, data={"notes": None}).json()["notes"] is None
    rejected = api.patch(url, data={"instrument": None, "lot_size": None})
    assert rejected.status == 422
    assert {e["loc"][-1] for e in rejected.json()["detail"]} == {"instrument", "lot_size"}


def test_a_patch_that_breaks_the_closure_rule_changes_nothing(api, journal):
    created = journal.trade()
    url = f"/api/trades/{created['id']}"
    rejected = api.patch(url, data={"pnl": None})
    assert rejected.status == 422 and rejected.json()["detail"][0]["loc"] == ["body", "pnl"]
    assert api.get(url).json() == created


def test_an_empty_patch_is_a_successful_no_op(api, journal):
    created = journal.trade()
    response = api.patch(f"/api/trades/{created['id']}", data={})
    assert response.status == 200 and response.json() == created


def test_delete_removes_the_trade_for_good(api, journal):
    created = journal.trade()
    assert api.delete(f"/api/trades/{created['id']}").status == 204
    journal.forget_trade(created["id"])
    assert api.get(f"/api/trades/{created['id']}").status == 404
    assert api.get(f"/api/trades?instrument={created['instrument']}").json()["total"] == 0


def test_unknown_ids_return_404_with_a_message(api):
    for call in (api.get, api.delete):
        response = call("/api/trades/999999999")
        assert response.status == 404 and response.json() == {"detail": "Trade 999999999 not found"}
    assert api.patch("/api/trades/999999999", data={"notes": "x"}).status == 404


@pytest.mark.parametrize("trade_id", ["0", "-1", "abc"])
def test_malformed_ids_are_422(api, trade_id):
    assert api.get(f"/api/trades/{trade_id}").status == 422


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"instrument": None}, "instrument"),
        ({"side": "sideways"}, "side"),
        ({"lot_size": "0"}, "lot_size"),
        ({"entry_price": "-1.5"}, "entry_price"),
        ({"opened_at": "2030-05-06T09:00:00"}, "opened_at"),  # no UTC offset
        ({"pnl": None}, "pnl"),  # closed, but no P&L
        ({"closed_at": None}, "exit_price"),  # exit price and P&L without closed_at
        ({"closed_at": "2030-05-06T08:00:00Z"}, "closed_at"),  # before it opened
        ({"tags": ["fine", "not;allowed"]}, "tags"),
        ({"surprise": 1}, "surprise"),
    ],
)
def test_invalid_payloads_are_rejected_naming_the_field_and_store_nothing(api, overrides, field):
    instrument = unique("BAD")
    response = api.post("/api/trades", data={"instrument": instrument, **BASE, **overrides})
    assert response.status == 422
    assert field in {str(part) for error in response.json()["detail"] for part in error["loc"]}
    if "instrument" not in overrides:
        assert api.get(f"/api/trades?instrument={instrument}").json()["total"] == 0
