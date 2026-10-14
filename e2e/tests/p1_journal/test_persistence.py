"""Phase 1: data survives a server restart.

scripts/verify.py runs this module in two passes. The first pass (everything except `after_restart`)
writes the canary. The server is then stopped, which checkpoints the SQLite WAL, and started again on
the same database file. The second pass runs only the `after_restart` tests.
"""
import pytest

CANARY = {
    "instrument": "RESTART-CANARY",
    "side": "short",
    "lot_size": "0.01",
    "entry_price": "190.12345678",
    "exit_price": "189.87654321",
    "opened_at": "2033-02-03T04:05:06Z",
    "closed_at": "2033-02-03T07:08:09Z",
    "pnl": "-0.00000001",
    "notes": "Written before the restart.",
    "tags": ["restart-canary", "Persistence"],
}


def test_write_the_canary_before_the_restart(api):
    # Tidy up first, so the test can be re-run against a database that already holds a canary.
    for old in api.get("/api/trades?instrument=RESTART-CANARY").json()["items"]:
        api.delete(f"/api/trades/{old['id']}")
    response = api.post("/api/trades", data=CANARY)
    assert response.status == 201, response.text()
    stored = api.get(f"/api/trades/{response.json()['id']}").json()
    assert stored["pnl"] == "-0.00000001" and stored["entry_price"] == "190.12345678"


@pytest.mark.after_restart
def test_the_canary_survived_the_restart_unchanged(api):
    ready = api.get("/api/ready")
    assert ready.status == 200 and ready.json()["status"] == "ready"

    page = api.get("/api/trades?instrument=RESTART-CANARY").json()
    assert page["total"] == 1, "the canary written before the restart is missing"
    trade = page["items"][0]
    for field, expected in CANARY.items():
        if field == "tags":
            assert trade["tags"] == ["Persistence", "restart-canary"]
        else:
            assert trade[field] == expected, field
    assert trade["status"] == "closed"
    assert api.get(f"/api/trades/{trade['id']}").json() == trade


@pytest.mark.after_restart
def test_derived_data_survived_the_restart_too(api):
    # 07:08:09Z is 02:08:09 on 3 February in New York, so the canary lands on that day.
    summary = api.get("/api/calendar/month?year=2033&month=2").json()
    assert [(d["date"], d["pnl"], d["trade_count"]) for d in summary["days"]] == [("2033-02-03", "-0.00000001", 1)]
    tags = {tag["name"] for tag in api.get("/api/tags").json()}
    assert {"restart-canary", "Persistence"} <= tags
