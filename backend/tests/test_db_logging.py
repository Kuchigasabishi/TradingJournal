import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.core.logging import JsonFormatter
from app.db.repositories import TradeRepository
from helpers import trade_payload


class Capture(logging.Handler):
    """Collects records exactly as the JSONL formatter would write them."""

    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(JsonFormatter())
        self.lines: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(json.loads(self.format(record)))

    def of(self, msg: str) -> list[dict]:
        return [line for line in self.lines if line["msg"] == msg]


@pytest.fixture
def captured():
    handler, logger = Capture(), logging.getLogger("app")
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    yield handler
    logger.removeHandler(handler)
    logger.setLevel(previous)


def test_a_committed_write_is_logged_and_tied_to_its_request(client, captured):
    response = client.post("/api/trades", json=trade_payload(tags=["a"]), headers={"X-Request-ID": "req-123"})
    assert response.status_code == 201
    (transaction,) = captured.of("db_transaction")
    assert (transaction["outcome"], transaction["request_id"]) == ("commit", "req-123")
    assert transaction["writes"] >= 3 and transaction["statements"] >= transaction["writes"]  # trade, tag and link
    for msg in ("request", "trade_created"):
        assert [line["request_id"] for line in captured.of(msg)] == ["req-123"]
    assert captured.of("trade_created")[0]["instrument"] == "EURUSD"


def test_domain_records_carry_ids_not_amounts_or_notes(client, captured):
    client.post("/api/trades", json=trade_payload(notes="private thoughts", pnl="1234.5"))
    text = json.dumps(captured.lines)
    assert "private thoughts" not in text and "1234.5" not in text


def test_an_update_logs_which_fields_changed(client, captured):
    created = client.post("/api/trades", json=trade_payload()).json()
    client.patch(f"/api/trades/{created['id']}", json={"notes": "x", "pnl": "3"})
    assert captured.of("trade_updated")[0]["changed_fields"] == ["notes", "pnl"]


def test_an_empty_patch_still_logs_a_commit(client, captured):
    created = client.post("/api/trades", json=trade_payload()).json()
    before = len(captured.of("db_transaction"))
    client.patch(f"/api/trades/{created['id']}", json={}, headers={"X-Request-ID": "noop-1"})
    commits = [line for line in captured.of("db_transaction")[before:] if line["request_id"] == "noop-1"]
    assert [(c["outcome"], c["writes"]) for c in commits] == [("commit", 0)]


def test_reads_write_no_transaction_record(client, captured):
    client.get("/api/trades")
    client.get("/api/tags")
    client.get("/api/calendar/month", params={"year": 2031, "month": 1})
    assert captured.of("db_transaction") == []


def test_a_rolled_back_write_is_logged_as_a_warning(client, captured, monkeypatch):
    def explode(self, trade, names):
        raise RuntimeError("tag storage is down")

    monkeypatch.setattr(TradeRepository, "set_tags", explode)
    response = TestClient(client.app, raise_server_exceptions=False).post("/api/trades", json=trade_payload(tags=["a"]))
    assert response.status_code == 500
    (transaction,) = captured.of("db_transaction")
    assert (transaction["outcome"], transaction["level"]) == ("rollback", "warning")
    assert transaction["writes"] >= 1
    assert captured.of("request")[0]["status"] == 500 and captured.of("request")[0]["level"] == "error"
