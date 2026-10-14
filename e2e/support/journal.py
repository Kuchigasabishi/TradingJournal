"""Helpers for the Phase 1 tests: unique names, a valid base trade, and cleanup through the public API."""
import uuid
from typing import Any

# A valid closed trade on a fixed date. Tests never depend on today's date.
BASE: dict[str, Any] = {
    "side": "long",
    "lot_size": "0.10",
    "entry_price": "1.08543",
    "exit_price": "1.08821",
    "opened_at": "2030-05-06T09:00:00Z",
    "closed_at": "2030-05-06T13:30:00Z",
    "pnl": "27.8",
}


def unique(prefix: str = "T") -> str:
    """A short upper-case token. The database is shared by the whole run, so each test works on its own rows."""
    return f"{prefix}{uuid.uuid4().hex[:10].upper()}"


class Journal:
    """Creates records through the public API and deletes them again when the test ends."""

    def __init__(self, api) -> None:
        self.api = api
        self.trades: list[int] = []
        self.notes: list[int] = []

    def trade(self, **overrides: Any) -> dict:
        payload = {"instrument": unique(), **BASE, **overrides}
        response = self.api.post("/api/trades", data=payload)
        assert response.status == 201, response.text()
        body = response.json()
        self.trades.append(body["id"])
        return body

    def open_trade(self, **overrides: Any) -> dict:
        return self.trade(**{"exit_price": None, "closed_at": None, "pnl": None, **overrides})

    def note(self, day: str, body: str = "Quiet session.") -> dict:
        response = self.api.post("/api/notes", data={"day": day, "body": body})
        assert response.status == 201, response.text()
        created = response.json()
        self.notes.append(created["id"])
        return created

    def track_trade(self, trade_id: int) -> None:
        """Adopts a trade that a UI test created, so it is deleted when the test ends."""
        self.trades.append(trade_id)

    def track_note(self, note_id: int) -> None:
        self.notes.append(note_id)

    def forget_trade(self, trade_id: int) -> None:
        self.trades.remove(trade_id)

    def forget_note(self, note_id: int) -> None:
        self.notes.remove(note_id)

    def cleanup(self) -> None:
        for trade_id in reversed(self.trades):
            self.api.delete(f"/api/trades/{trade_id}")
        for note_id in reversed(self.notes):
            self.api.delete(f"/api/notes/{note_id}")
