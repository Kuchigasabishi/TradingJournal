"""Phase 1: money is exact. Prices, lots and P&L are scaled integers in the database and decimal strings on the wire."""
import pytest
from support.journal import BASE, unique


def test_eight_decimal_places_round_trip_exactly(api, journal):
    created = journal.trade(entry_price="1.12345678", exit_price="1.00000001", lot_size="0.00000001", pnl="-0.00000001")
    stored = api.get(f"/api/trades/{created['id']}").json()
    assert (stored["entry_price"], stored["exit_price"], stored["lot_size"], stored["pnl"]) == (
        "1.12345678",
        "1.00000001",
        "0.00000001",
        "-0.00000001",
    )


def test_the_largest_supported_value_round_trips(api, journal):
    created = journal.trade(entry_price="9999999999.99999999", pnl="-9999999999.99999999")
    stored = api.get(f"/api/trades/{created['id']}").json()
    assert (stored["entry_price"], stored["pnl"]) == ("9999999999.99999999", "-9999999999.99999999")


def test_values_come_back_in_canonical_form(api, journal):
    created = journal.trade(lot_size="0.10", entry_price="1.50000", pnl="100.00")
    assert (created["lot_size"], created["entry_price"], created["pnl"]) == ("0.1", "1.5", "100")
    zero = journal.trade(pnl="0.0")
    assert zero["pnl"] == "0"


@pytest.mark.parametrize("value", ["1.123456789", "10000000000", "1e-9", "NaN", "abc"])
def test_values_that_cannot_be_stored_exactly_are_rejected_not_rounded(api, value):
    response = api.post("/api/trades", data={"instrument": unique("X"), **BASE, "entry_price": value})
    assert response.status == 422
    assert response.json()["detail"][0]["loc"][-1] == "entry_price"


def test_a_floating_point_artifact_is_rejected(api):
    response = api.post("/api/trades", data={"instrument": unique("X"), **BASE, "pnl": 0.1 + 0.2})  # 0.30000000000000004
    assert response.status == 422 and response.json()["detail"][0]["loc"][-1] == "pnl"


def test_numeric_json_input_is_accepted_when_it_is_exact(api, journal):
    created = journal.trade(lot_size=0.25, entry_price=1.5, pnl=-12.5)
    assert (created["lot_size"], created["entry_price"], created["pnl"]) == ("0.25", "1.5", "-12.5")


def test_sorting_by_pnl_is_numeric_not_textual(api, journal):
    group = unique("S")
    for pnl in ("100", "-10", "2", "0.5"):
        journal.trade(pnl=pnl, tags=[group])
    ascending = api.get(f"/api/trades?tag={group}&sort=pnl&order=asc").json()["items"]
    descending = api.get(f"/api/trades?tag={group}&sort=pnl&order=desc").json()["items"]
    assert [t["pnl"] for t in ascending] == ["-10", "0.5", "2", "100"]  # a text sort would put "100" first
    assert [t["pnl"] for t in descending] == ["100", "2", "0.5", "-10"]
