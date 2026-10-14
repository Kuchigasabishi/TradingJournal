from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.calendar import DaySummary
from app.schemas.trades import TradeCreate, TradeUpdate
from helpers import open_payload, trade_payload


def errors_of(payload: dict) -> list[tuple[str, str]]:
    with pytest.raises(ValidationError) as caught:
        TradeCreate.model_validate(payload)
    return [(".".join(str(part) for part in e["loc"]), e["type"]) for e in caught.value.errors()]


def test_a_valid_closed_trade_is_normalized():
    trade = TradeCreate.model_validate(
        trade_payload(
            instrument=" eur/usd ",
            side=" LONG ",
            opened_at="2030-05-06T11:00:00+02:00",
            tags=["Breakout", "  london   open ", "breakout"],
            notes="  retest of the level \n",
        )
    )
    assert trade.instrument == "EUR/USD"
    assert trade.side == "long"
    assert trade.opened_at == datetime(2030, 5, 6, 9, 0, tzinfo=timezone.utc)
    assert trade.opened_at.utcoffset().total_seconds() == 0
    assert trade.tags == ["Breakout", "london open"]  # whitespace collapsed, case-insensitive duplicate dropped
    assert trade.notes == "retest of the level"


def test_a_blank_note_means_no_note():
    assert TradeCreate.model_validate(trade_payload(notes="   ")).notes is None


def test_an_open_trade_needs_no_closing_fields():
    trade = TradeCreate.model_validate(open_payload())
    assert (trade.exit_price, trade.closed_at, trade.pnl) == (None, None, None)


@pytest.mark.parametrize("value", ["1.12345678", "0.00000001", 5, "9999999999.99999999"])
def test_up_to_eight_decimals_and_ten_whole_digits_are_accepted(value):
    assert TradeCreate.model_validate(trade_payload(entry_price=value)).entry_price == Decimal(str(value))


@pytest.mark.parametrize("value", ["1.123456789", "10000000000", "1e-9", "NaN", "Infinity", "abc"])
def test_too_precise_too_large_or_non_numeric_money_is_rejected(value):
    assert errors_of(trade_payload(entry_price=value))[0][0] == "entry_price"


def test_a_float_artifact_is_rejected_instead_of_silently_rounded():
    raw = '{"instrument": "EURUSD", "side": "long", "lot_size": 0.30000000000000004, "entry_price": 1, "opened_at": "2030-01-01T00:00:00Z"}'
    with pytest.raises(ValidationError) as caught:
        TradeCreate.model_validate_json(raw)
    assert caught.value.errors()[0]["loc"] == ("lot_size",)


@pytest.mark.parametrize("field", ["lot_size", "entry_price", "exit_price"])
@pytest.mark.parametrize("value", ["0", "-1"])
def test_lots_and_prices_must_be_positive(field, value):
    assert errors_of(trade_payload(**{field: value}))[0][0] == field


def test_pnl_may_be_negative_or_zero():
    assert TradeCreate.model_validate(trade_payload(pnl="-12.5")).pnl == Decimal("-12.5")
    assert TradeCreate.model_validate(trade_payload(pnl="0")).pnl == 0


def test_naive_datetimes_are_rejected():
    assert errors_of(trade_payload(opened_at="2030-05-06T09:00:00"))[0][0] == "opened_at"


@pytest.mark.parametrize(
    "overrides",
    [
        {"instrument": "bad name!"},
        {"instrument": ""},
        {"instrument": "X" * 21},
        {"side": "sideways"},
        {"tags": ["ok", "no;semicolons"]},
        {"tags": ["x" * 41]},
        {"tags": [f"t{i}" for i in range(21)]},
        {"notes": "x" * 10_001},
        {"unknown_field": 1},
    ],
)
def test_malformed_input_is_rejected(overrides):
    with pytest.raises(ValidationError):
        TradeCreate.model_validate(trade_payload(**overrides))


def test_an_update_remembers_which_fields_were_sent():
    patch = TradeUpdate.model_validate({"notes": None, "pnl": "3"})
    assert patch.model_fields_set == {"notes", "pnl"}
    assert patch.model_dump(exclude_unset=True) == {"notes": None, "pnl": Decimal("3")}


def test_money_serializes_as_canonical_strings_and_instants_as_utc():
    day = DaySummary(date="2030-01-02", pnl=Decimal("1.10000000"), trade_count=1, wins=1, losses=0, breakeven=0)
    assert day.model_dump(mode="json")["pnl"] == "1.1"
    assert DaySummary(date="2030-01-02", pnl=Decimal("100"), trade_count=1, wins=1, losses=0, breakeven=0).model_dump(mode="json")["pnl"] == "100"
    assert DaySummary(date="2030-01-02", pnl=Decimal("-0.0"), trade_count=1, wins=0, losses=0, breakeven=1).model_dump(mode="json")["pnl"] == "0"
