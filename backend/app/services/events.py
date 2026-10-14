"""Reading events from outside calendars.

Events are stored as UTC instants (timed) or dates (all-day), and the calendar days they cover in the server's
APP_TIMEZONE are worked out when they are read, the same way trade days are. An event that crosses local midnight
covers both days; one that ends exactly at midnight does not spill into the next.
"""
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.errors import InvalidStateError, field_error
from app.db.models import ExternalEvent
from app.db.repositories import EventRepository
from app.schemas.events import EventRead


def event_days(row: ExternalEvent, tz: ZoneInfo) -> tuple[date, date]:
    """The first and last (inclusive) local day an event covers."""
    if row.all_day:
        return row.start_date, row.end_date - timedelta(days=1)  # type: ignore[operator]
    first = row.start_at.astimezone(tz).date()  # type: ignore[union-attr]
    if row.end_at is None or row.end_at <= row.start_at:
        return first, first
    end = row.end_at.astimezone(tz)
    last = end.date() - timedelta(days=1) if end.time() == time.min else end.date()
    return first, max(first, last)


def to_read(row: ExternalEvent, tz: ZoneInfo) -> EventRead:
    first, last = event_days(row, tz)
    return EventRead(
        id=row.id,
        source=row.source,  # type: ignore[arg-type]
        title=row.title,
        description=row.description,
        location=row.location,
        url=row.url,
        currency=row.currency,
        impact=row.impact,  # type: ignore[arg-type]
        forecast=row.forecast,
        previous=row.previous,
        all_day=row.all_day,
        start_at=row.start_at,
        end_at=row.end_at,
        start_day=first,
        end_day=last,
        updated_at=row.updated_at,
    )


def _local_midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=tz).astimezone(timezone.utc)


class EventService:
    def __init__(self, session: Session, tz: ZoneInfo) -> None:
        self.session = session
        self.tz = tz
        self.repo = EventRepository(session)

    def list(
        self,
        *,
        from_day: date | None,
        to_day: date | None,
        source: str | None,
        impacts: Sequence[str],
        currency: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[EventRead], int]:
        if from_day and to_day and from_day > to_day:
            raise InvalidStateError([field_error("from", "from must not be later than to", "range", where="query")])
        # One day of slack on each side keeps the SQL window honest across daylight saving; the exact test is below.
        start = _local_midnight(from_day, self.tz) - timedelta(days=1) if from_day else None
        end = _local_midnight(to_day + timedelta(days=1), self.tz) + timedelta(days=1) if to_day else None
        rows = self.repo.candidates(
            start=start, end=end, first_day=from_day, last_day=to_day, source=source, impacts=impacts, currency=currency
        )
        matches = []
        for row in rows:
            first, last = event_days(row, self.tz)
            if (from_day is None or last >= from_day) and (to_day is None or first <= to_day):
                matches.append((first, row))
        # All-day events lead their first day, then by time, then by source and id so the order is always the same.
        matches.sort(key=lambda m: (m[0], not m[1].all_day, m[1].start_at or datetime.min.replace(tzinfo=timezone.utc), m[1].source, m[1].id))
        page = matches[offset : offset + limit]
        return [to_read(row, self.tz) for _, row in page], len(matches)
