from datetime import datetime, timezone


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def trade_payload(**overrides) -> dict:
    """A valid closed trade as the API receives it. Pass None to blank a field."""
    payload = {
        "instrument": "EURUSD",
        "side": "long",
        "lot_size": "0.10",
        "entry_price": "1.08543",
        "exit_price": "1.08821",
        "opened_at": "2030-05-06T09:00:00Z",
        "closed_at": "2030-05-06T13:30:00Z",
        "pnl": "27.8",
    }
    payload.update(overrides)
    return payload


def open_payload(**overrides) -> dict:
    return trade_payload(exit_price=None, closed_at=None, pnl=None, **overrides)
