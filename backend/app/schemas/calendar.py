from datetime import date as Date

from pydantic import BaseModel

from app.schemas.common import MoneyOut


class DayTotals(BaseModel):
    pnl: MoneyOut
    trade_count: int
    wins: int
    losses: int
    breakeven: int


class DaySummary(DayTotals):
    date: Date


class MonthSummary(BaseModel):
    """Closed trades only, bucketed by the day they were closed in `timezone`. Days without trades are omitted."""

    year: int
    month: int
    timezone: str
    days: list[DaySummary]
    totals: DayTotals
