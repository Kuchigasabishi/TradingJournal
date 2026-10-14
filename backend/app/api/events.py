from datetime import date

from fastapi import APIRouter, Depends, Query

from app.api.deps import event_service
from app.schemas.common import Page
from app.schemas.events import EventRead, Impact, SourceName
from app.services.events import EventService

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("", response_model=Page[EventRead], openapi_extra={"x-phase": 3})
def list_events(
    from_day: date | None = Query(None, alias="from", description="First day, inclusive, in the server's APP_TIMEZONE"),
    to_day: date | None = Query(None, alias="to", description="Last day, inclusive, in the server's APP_TIMEZONE"),
    source: SourceName | None = Query(None, description="forexfactory (economic news) or gcal (the owner's Google Calendar)"),
    impact: list[Impact] = Query(default_factory=list, description="Repeat for several levels. Only news has an impact"),
    currency: str | None = Query(None, description="A currency code such as USD. News for every currency (ALL) is included"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    service: EventService = Depends(event_service),
) -> Page[EventRead]:
    """Events that cover any day of the range, ordered by day, with all-day events first and then by time.

    A multi-day event is listed once. `start_day` and `end_day` say which local days it covers.
    """
    items, total = service.list(
        from_day=from_day,
        to_day=to_day,
        source=source,
        impacts=impact,
        currency=currency.strip().upper() if currency else None,
        limit=limit,
        offset=offset,
    )
    return Page[EventRead](items=items, total=total, limit=limit, offset=offset)
