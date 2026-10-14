"""Month summary for the calendar view.

Closed trades only, bucketed by the day they were closed in the configured time zone. The bucketing
is plain Python on exact Decimals, so a day's total is exact (0.1 + 0.2 is 0.3).
"""
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Trade
from app.schemas.calendar import DaySummary, DayTotals, MonthSummary


def month_window(year: int, month: int, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """A UTC range that certainly holds every instant of the month in `tz`: one day of slack on each side."""
    first = datetime(year, month, 1, tzinfo=tz)
    following = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=tz)
    return first.astimezone(timezone.utc) - timedelta(days=1), following.astimezone(timezone.utc) + timedelta(days=1)


def _totals(values: list[Decimal]) -> dict:
    return {
        "pnl": sum(values, Decimal(0)),
        "trade_count": len(values),
        "wins": sum(1 for value in values if value > 0),
        "losses": sum(1 for value in values if value < 0),
        "breakeven": sum(1 for value in values if value == 0),
    }


def summarize_month(rows: Iterable[tuple[datetime, Decimal]], year: int, month: int, tz: ZoneInfo) -> MonthSummary:
    by_day: dict[date, list[Decimal]] = defaultdict(list)
    for closed_at, pnl in rows:
        local = closed_at.astimezone(tz)
        if (local.year, local.month) == (year, month):
            by_day[local.date()].append(pnl)
    days = [DaySummary(date=day, **_totals(values)) for day, values in sorted(by_day.items())]
    everything = [value for values in by_day.values() for value in values]
    return MonthSummary(year=year, month=month, timezone=str(tz), days=days, totals=DayTotals(**_totals(everything)))


class CalendarService:
    def __init__(self, session: Session, tz: ZoneInfo) -> None:
        self.session = session
        self.tz = tz

    def month(self, year: int, month: int) -> MonthSummary:
        start, end = month_window(year, month, self.tz)
        rows = self.session.execute(
            select(Trade.closed_at, Trade.pnl).where(Trade.closed_at >= start, Trade.closed_at < end)
        ).all()
        return summarize_month(((r.closed_at, r.pnl) for r in rows if r.pnl is not None), year, month, self.tz)
