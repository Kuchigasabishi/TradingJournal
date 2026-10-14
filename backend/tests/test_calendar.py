from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.db.models import Trade
from app.services.calendar import CalendarService, month_window, summarize_month
from helpers import utc

NY = ZoneInfo("America/New_York")


def days_of(summary) -> dict[str, str]:
    return {day.date.isoformat(): str(day.pnl) for day in summary.days}


def test_trades_are_bucketed_by_local_day_across_midnight_in_winter():
    rows = [(utc(2031, 1, 16, 4, 59, 59), Decimal("1")), (utc(2031, 1, 16, 5, 0, 0), Decimal("2"))]  # EST is UTC-5
    assert days_of(summarize_month(rows, 2031, 1, NY)) == {"2031-01-15": "1", "2031-01-16": "2"}


def test_the_offset_follows_daylight_saving_in_summer():
    rows = [(utc(2031, 7, 16, 3, 59, 59), Decimal("1")), (utc(2031, 7, 16, 4, 0, 0), Decimal("2"))]  # EDT is UTC-4
    assert days_of(summarize_month(rows, 2031, 7, NY)) == {"2031-07-15": "1", "2031-07-16": "2"}


def test_the_spring_forward_day_is_23_hours_long():
    rows = [  # US clocks jump forward on 2031-03-09 at 07:00 UTC
        (utc(2031, 3, 9, 4, 59, 59), Decimal("1")),
        (utc(2031, 3, 9, 5, 0, 0), Decimal("2")),
        (utc(2031, 3, 10, 3, 59, 59), Decimal("4")),
        (utc(2031, 3, 10, 4, 0, 0), Decimal("8")),
    ]
    assert days_of(summarize_month(rows, 2031, 3, NY)) == {"2031-03-08": "1", "2031-03-09": "6", "2031-03-10": "8"}


def test_the_fall_back_day_is_25_hours_long():
    rows = [  # US clocks fall back on 2031-11-02 at 06:00 UTC
        (utc(2031, 11, 2, 3, 59, 59), Decimal("1")),
        (utc(2031, 11, 2, 4, 0, 0), Decimal("2")),
        (utc(2031, 11, 3, 4, 59, 59), Decimal("4")),
        (utc(2031, 11, 3, 5, 0, 0), Decimal("8")),
    ]
    assert days_of(summarize_month(rows, 2031, 11, NY)) == {"2031-11-01": "1", "2031-11-02": "6", "2031-11-03": "8"}


def test_a_trade_belongs_to_the_month_of_its_local_closing_day():
    rows = [(utc(2031, 2, 1, 4, 59, 59), Decimal("1")), (utc(2031, 2, 1, 5, 0, 0), Decimal("2"))]
    assert days_of(summarize_month(rows, 2031, 1, NY)) == {"2031-01-31": "1"}
    assert days_of(summarize_month(rows, 2031, 2, NY)) == {"2031-02-01": "2"}


def test_day_totals_are_exact():
    rows = [(utc(2031, 1, 10, 15), Decimal("0.1")), (utc(2031, 1, 10, 16), Decimal("0.2"))]
    summary = summarize_month(rows, 2031, 1, NY)
    assert summary.days[0].pnl == Decimal("0.3")
    assert summary.model_dump(mode="json")["totals"]["pnl"] == "0.3"


def test_wins_losses_and_breakeven_are_counted_by_sign():
    rows = [(utc(2031, 1, 10, 15, m), Decimal(v)) for m, v in enumerate(["5", "-3", "0", "0.00000001", "-0.00000001"])]
    day = summarize_month(rows, 2031, 1, NY).days[0]
    assert (day.trade_count, day.wins, day.losses, day.breakeven) == (5, 2, 2, 1)
    assert day.pnl == Decimal("2")


def test_months_without_trades_have_no_days_and_zero_totals():
    summary = summarize_month([], 2031, 5, NY)
    assert summary.days == [] and summary.totals.trade_count == 0 and summary.totals.pnl == 0
    assert summary.timezone == "America/New_York"


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Pacific/Kiritimati", "Pacific/Pago_Pago", "Asia/Kolkata"])
@pytest.mark.parametrize("month", [1, 3, 12])
def test_the_query_window_always_covers_the_month(zone, month):
    tz = ZoneInfo(zone)
    start, end = month_window(2031, month, tz)
    first = datetime(2031, month, 1, tzinfo=tz).astimezone(timezone.utc)
    last = datetime(2031 + (month == 12), month % 12 + 1, 1, tzinfo=tz).astimezone(timezone.utc)
    assert start < first and last < end


def test_the_service_reads_only_closed_trades_of_the_month(session):
    def trade(**kw):
        base = dict(instrument="EURUSD", side="long", lot_size=Decimal("1"), entry_price=Decimal("1"), opened_at=utc(2031, 1, 1))
        return Trade(**{**base, **kw})

    session.add_all(
        [
            trade(exit_price=Decimal("2"), closed_at=utc(2031, 1, 10, 15), pnl=Decimal("0.1")),
            trade(exit_price=Decimal("2"), closed_at=utc(2031, 1, 10, 16), pnl=Decimal("0.2")),
            trade(exit_price=Decimal("2"), closed_at=utc(2031, 2, 10, 16), pnl=Decimal("99")),  # another month
            trade(),  # still open
        ]
    )
    session.commit()
    summary = CalendarService(session, NY).month(2031, 1)
    assert [(d.date.isoformat(), d.pnl, d.trade_count) for d in summary.days] == [("2031-01-10", Decimal("0.3"), 2)]
