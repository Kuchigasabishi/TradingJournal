from fastapi import APIRouter, Depends, Query

from app.api.deps import calendar_service
from app.schemas.calendar import MonthSummary
from app.services.calendar import CalendarService

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


@router.get("/month", response_model=MonthSummary)
def month_summary(
    year: int = Query(ge=1970, le=2200),
    month: int = Query(ge=1, le=12),
    service: CalendarService = Depends(calendar_service),
) -> MonthSummary:
    """Per-day realized P&L and win/loss counts for one month. Closed trades only, bucketed by closing day in the server's APP_TIMEZONE."""
    return service.month(year, month)
