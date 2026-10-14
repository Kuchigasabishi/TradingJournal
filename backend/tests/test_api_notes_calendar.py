import pytest

from helpers import open_payload, trade_payload


def make_note(client, day="2030-05-06", body="Choppy session, sat out the afternoon.") -> dict:
    response = client.post("/api/notes", json={"day": day, "body": body})
    assert response.status_code == 201, response.text
    return response.json()


def test_a_note_round_trips(client):
    response = client.post("/api/notes", json={"day": "2030-05-06", "body": "  Choppy session.  "})
    body = response.json()
    assert response.status_code == 201 and response.headers["location"] == f"/api/notes/{body['id']}"
    assert (body["day"], body["body"]) == ("2030-05-06", "Choppy session.")
    assert client.get(f"/api/notes/{body['id']}").json() == body


def test_notes_filter_by_inclusive_day_range_and_page(client):
    for day in ("2030-05-05", "2030-05-06", "2030-05-07"):
        make_note(client, day=day, body=f"note for {day}")
    page = client.get("/api/notes", params={"from": "2030-05-06", "to": "2030-05-07"}).json()
    assert page["total"] == 2 and [n["day"] for n in page["items"]] == ["2030-05-07", "2030-05-06"]
    assert len(client.get("/api/notes", params={"limit": 1}).json()["items"]) == 1


def test_a_note_can_be_edited_and_deleted(client):
    note = make_note(client)
    edited = client.patch(f"/api/notes/{note['id']}", json={"body": "Revised."}).json()
    assert edited["body"] == "Revised." and edited["day"] == note["day"]
    assert client.patch(f"/api/notes/{note['id']}", json={}).json() == edited
    assert client.delete(f"/api/notes/{note['id']}").status_code == 204
    assert client.get(f"/api/notes/{note['id']}").status_code == 404


@pytest.mark.parametrize(
    "payload",
    [{"day": "2030-05-06", "body": "   "}, {"day": "not-a-date", "body": "x"}, {"body": "x"}, {"day": "2030-05-06", "body": "x", "extra": 1}],
)
def test_invalid_notes_are_422(client, payload):
    assert client.post("/api/notes", json=payload).status_code == 422


def test_a_note_cannot_be_patched_to_null(client):
    note = make_note(client)
    assert client.patch(f"/api/notes/{note['id']}", json={"body": None}).status_code == 422


def test_unknown_notes_are_404(client):
    assert client.get("/api/notes/9").status_code == 404
    assert client.delete("/api/notes/9").status_code == 404
    assert client.patch("/api/notes/9", json={"body": "x"}).status_code == 404


def test_the_month_summary_buckets_by_closing_day_in_the_configured_zone(client):
    def close(pnl, closed_at):
        client.post("/api/trades", json=trade_payload(pnl=pnl, opened_at="2031-01-01T00:00:00Z", closed_at=closed_at))

    close("0.1", "2031-01-16T04:59:59Z")  # 23:59:59 on the 15th in New York
    close("0.2", "2031-01-16T05:00:00Z")  # 00:00:00 on the 16th
    close("0.3", "2031-01-16T12:00:00Z")
    close("-1", "2031-02-01T04:59:59Z")  # still January in New York
    close("9", "2031-02-01T05:00:00Z")  # February
    client.post("/api/trades", json=open_payload(opened_at="2031-01-10T00:00:00Z"))  # open trades never count

    body = client.get("/api/calendar/month", params={"year": 2031, "month": 1}).json()
    assert body["timezone"] == "America/New_York" and (body["year"], body["month"]) == (2031, 1)
    assert [(d["date"], d["pnl"], d["trade_count"], d["wins"], d["losses"]) for d in body["days"]] == [
        ("2031-01-15", "0.1", 1, 1, 0),
        ("2031-01-16", "0.5", 2, 2, 0),
        ("2031-01-31", "-1", 1, 0, 1),
    ]
    assert body["totals"] == {"pnl": "-0.4", "trade_count": 4, "wins": 3, "losses": 1, "breakeven": 0}


@pytest.mark.parametrize("params", [{"year": 2031, "month": 13}, {"year": 2031, "month": 0}, {"year": 1969, "month": 1}, {"month": 1}, {"year": 2031}])
def test_the_month_summary_validates_its_parameters(client, params):
    assert client.get("/api/calendar/month", params=params).status_code == 422


def test_a_month_without_trades_is_empty(client):
    body = client.get("/api/calendar/month", params={"year": 2031, "month": 5}).json()
    assert body["days"] == [] and body["totals"]["trade_count"] == 0 and body["totals"]["pnl"] == "0"


def test_ready_reports_unmigrated_databases(client):  # the fixture builds tables with create_all, so there is no alembic_version
    response = client.get("/api/ready")
    assert response.status_code == 503 and "migrations" in response.json()["problems"]
