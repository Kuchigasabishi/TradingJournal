import pytest
from fastapi.testclient import TestClient

from app.db.repositories import TradeRepository
from helpers import open_payload, trade_payload


def create(client, **overrides) -> dict:
    response = client.post("/api/trades", json=trade_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def test_create_returns_201_with_location_and_canonical_values(client):
    response = client.post("/api/trades", json=trade_payload(instrument="eurusd", side="Long", notes="retest"))
    assert response.status_code == 201
    body = response.json()
    assert response.headers["location"] == f"/api/trades/{body['id']}"
    assert (body["instrument"], body["side"], body["status"]) == ("EURUSD", "long", "closed")
    assert (body["lot_size"], body["entry_price"], body["exit_price"], body["pnl"]) == ("0.1", "1.08543", "1.08821", "27.8")
    assert (body["opened_at"], body["closed_at"]) == ("2030-05-06T09:00:00Z", "2030-05-06T13:30:00Z")
    assert body["notes"] == "retest" and body["tags"] == []
    assert body["created_at"].endswith("Z") and body["updated_at"].endswith("Z")


def test_get_returns_exactly_what_create_returned(client):
    created = create(client, tags=["Breakout"], notes="n")
    assert client.get(f"/api/trades/{created['id']}").json() == created


def test_offsets_are_converted_to_utc(client):
    body = create(client, opened_at="2030-05-06T11:00:00+02:00", closed_at="2030-05-06T09:30:00-04:00")
    assert (body["opened_at"], body["closed_at"]) == ("2030-05-06T09:00:00Z", "2030-05-06T13:30:00Z")


def test_an_open_trade_has_no_closing_fields(client):
    response = client.post("/api/trades", json=open_payload())
    body = response.json()
    assert response.status_code == 201 and body["status"] == "open"
    assert (body["exit_price"], body["closed_at"], body["pnl"]) == (None, None, None)


def test_list_is_a_page(client):
    first, second = create(client), create(client, opened_at="2030-05-07T09:00:00Z", closed_at="2030-05-07T10:00:00Z")
    body = client.get("/api/trades").json()
    assert (body["total"], body["limit"], body["offset"]) == (2, 100, 0)
    assert [t["id"] for t in body["items"]] == [second["id"], first["id"]]


def test_patch_changes_only_the_fields_sent(client):
    created = create(client, notes="before", tags=["a"])
    response = client.patch(f"/api/trades/{created['id']}", json={"pnl": "-3.25", "notes": "after", "tags": ["b", "c"]})
    assert response.status_code == 200
    body = response.json()
    assert (body["pnl"], body["notes"], body["tags"]) == ("-3.25", "after", ["b", "c"])
    assert {k: v for k, v in body.items() if k not in ("pnl", "notes", "tags", "updated_at")} == {
        k: v for k, v in created.items() if k not in ("pnl", "notes", "tags", "updated_at")
    }
    assert client.get(f"/api/trades/{created['id']}").json() == body


def test_patch_can_reopen_and_close_a_trade(client):
    created = create(client)
    reopened = client.patch(f"/api/trades/{created['id']}", json={"exit_price": None, "closed_at": None, "pnl": None}).json()
    assert reopened["status"] == "open" and reopened["pnl"] is None
    closed = client.patch(
        f"/api/trades/{created['id']}", json={"exit_price": "1.1", "closed_at": "2030-05-06T15:00:00Z", "pnl": "5"}
    ).json()
    assert (closed["status"], closed["pnl"], closed["exit_price"]) == ("closed", "5", "1.1")


def test_patch_can_clear_notes_with_null(client):
    created = create(client, notes="keep?")
    assert client.patch(f"/api/trades/{created['id']}", json={"notes": None}).json()["notes"] is None


def test_patch_rejects_null_for_required_fields(client):
    created = create(client)
    response = client.patch(f"/api/trades/{created['id']}", json={"instrument": None, "lot_size": None})
    assert response.status_code == 422
    assert {e["loc"][-1] for e in response.json()["detail"]} == {"instrument", "lot_size"}


def test_patch_that_breaks_the_closure_rule_is_rejected_and_changes_nothing(client):
    created = create(client)
    response = client.patch(f"/api/trades/{created['id']}", json={"pnl": None})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "pnl"]
    assert client.get(f"/api/trades/{created['id']}").json() == created


def test_an_empty_patch_changes_nothing(client):
    created = create(client)
    response = client.patch(f"/api/trades/{created['id']}", json={})
    assert response.status_code == 200 and response.json() == created


def test_delete_then_get_is_404(client):
    created = create(client)
    assert client.delete(f"/api/trades/{created['id']}").status_code == 204
    assert client.get(f"/api/trades/{created['id']}").status_code == 404
    assert client.get("/api/trades").json()["total"] == 0


def test_unknown_trades_are_404_with_a_message(client):
    for call in (client.get, client.delete):
        response = call("/api/trades/999")
        assert response.status_code == 404 and response.json() == {"detail": "Trade 999 not found"}
    assert client.patch("/api/trades/999", json={"notes": "x"}).status_code == 404


@pytest.mark.parametrize("trade_id", ["0", "-1", "abc"])
def test_malformed_ids_are_422(client, trade_id):
    assert client.get(f"/api/trades/{trade_id}").status_code == 422


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"instrument": None}, "instrument"),
        ({"side": "sideways"}, "side"),
        ({"lot_size": "0"}, "lot_size"),
        ({"entry_price": "1.123456789"}, "entry_price"),
        ({"opened_at": "2030-05-06T09:00:00"}, "opened_at"),
        ({"pnl": None}, "pnl"),  # closed without P&L
        ({"closed_at": None}, "exit_price"),  # exit price and P&L without closed_at: reported per field
        ({"closed_at": "2030-05-06T08:00:00Z"}, "closed_at"),  # before it opened
        ({"surprise": 1}, "surprise"),
    ],
)
def test_invalid_input_is_422_and_names_the_field(client, overrides, field):
    response = client.post("/api/trades", json=trade_payload(**overrides))
    assert response.status_code == 422
    assert field in {e["loc"][-1] for e in response.json()["detail"]}
    assert client.get("/api/trades").json()["total"] == 0


def test_filters_combine(client):
    create(client, instrument="EURUSD", tags=["breakout", "london"])
    create(client, instrument="GBPUSD", side="short", tags=["breakout"], opened_at="2030-05-07T09:00:00Z", closed_at="2030-05-07T10:00:00Z")
    client.post("/api/trades", json=open_payload(instrument="EURUSD", opened_at="2030-05-08T09:00:00Z"))

    def total(**params):
        return client.get("/api/trades", params=params).json()["total"]

    assert total(instrument="eurusd") == 2
    assert total(side="short") == 1
    assert total(status="open") == 1 and total(status="closed") == 2
    assert total(tag=["breakout"]) == 2 and total(tag=["Breakout", "LONDON"]) == 1
    assert total(instrument="EURUSD", status="closed", tag=["breakout"]) == 1


def test_date_filters_use_the_configured_time_zone(client):  # the fixture runs in America/New_York
    create(client, opened_at="2031-01-15T20:00:00Z", closed_at="2031-01-16T04:59:59Z")  # local 23:59:59 on the 15th
    create(client, opened_at="2031-01-15T20:00:00Z", closed_at="2031-01-16T05:00:00Z")  # local 00:00:00 on the 16th

    def count(day):
        return client.get("/api/trades", params={"from": day, "to": day}).json()["total"]

    assert (count("2031-01-15"), count("2031-01-16")) == (1, 1)
    assert client.get("/api/trades", params={"from": "2031-01-15", "to": "2031-01-16"}).json()["total"] == 2
    assert client.get("/api/trades", params={"from": "2031-01-17"}).json()["total"] == 0


def test_an_inverted_date_range_is_422(client):
    response = client.get("/api/trades", params={"from": "2031-02-01", "to": "2031-01-01"})
    assert response.status_code == 422 and response.json()["detail"][0]["loc"] == ["query", "from"]


def test_sorting_by_pnl_is_numeric(client):
    for index, pnl in enumerate(["100", "-10", "2"]):
        create(client, pnl=pnl, opened_at=f"2030-05-0{index + 1}T09:00:00Z", closed_at=f"2030-05-0{index + 1}T10:00:00Z")
    ascending = [t["pnl"] for t in client.get("/api/trades", params={"sort": "pnl", "order": "asc"}).json()["items"]]
    assert ascending == ["-10", "2", "100"]  # a text sort would put "100" before "2"


def test_paging(client):
    for day in range(1, 6):
        create(client, opened_at=f"2030-05-0{day}T09:00:00Z", closed_at=f"2030-05-0{day}T10:00:00Z")
    page = client.get("/api/trades", params={"limit": 2, "offset": 2}).json()
    assert (page["total"], page["limit"], page["offset"], len(page["items"])) == (5, 2, 2, 2)
    assert client.get("/api/trades", params={"limit": 501}).status_code == 422
    assert client.get("/api/trades", params={"offset": -1}).status_code == 422


def test_tags_are_shared_case_insensitively_and_disappear_with_their_last_trade(client):
    first = create(client, tags=["Breakout", "london"])
    second = create(client, tags=["breakout"])
    assert second["tags"] == ["Breakout"]  # the first spelling wins
    assert client.get("/api/tags").json() == [{"name": "Breakout", "count": 2}, {"name": "london", "count": 1}]
    client.delete(f"/api/trades/{first['id']}")
    assert client.get("/api/tags").json() == [{"name": "Breakout", "count": 1}]
    client.patch(f"/api/trades/{second['id']}", json={"tags": []})
    assert client.get("/api/tags").json() == []


def test_a_failed_write_leaves_nothing_behind(client, monkeypatch):
    def explode(self, trade, names):
        raise RuntimeError("tag storage is down")

    monkeypatch.setattr(TradeRepository, "set_tags", explode)
    response = TestClient(client.app, raise_server_exceptions=False).post("/api/trades", json=trade_payload(tags=["a"]))
    assert response.status_code == 500
    assert client.get("/api/trades").json()["total"] == 0  # the half-written trade was rolled back
