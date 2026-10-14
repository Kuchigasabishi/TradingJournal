"""Database access for the journal.

Repositories flush but never commit: the service layer owns the transaction. Money columns are exact
integers in SQL, so filtering, sorting and summing them in the database is numerically correct.
"""
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from sqlalchemy import and_, asc, delete, desc, exists, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import ExternalEvent, FeedState, Note, Tag, Trade, trade_tags
from app.db.types import UtcDateTime

# A trade belongs to the day it was closed, or the day it was opened while it is still open.
JOURNAL_AT = func.coalesce(Trade.closed_at, Trade.opened_at, type_=UtcDateTime())
SORT_COLUMNS = {
    "journal_at": JOURNAL_AT,
    "opened_at": Trade.opened_at,
    "closed_at": Trade.closed_at,
    "pnl": Trade.pnl,
}


@dataclass(frozen=True)
class TradeCriteria:
    instrument: str | None = None
    side: str | None = None
    status: Literal["open", "closed"] | None = None
    tags: tuple[str, ...] = ()  # a trade must carry all of them
    start: datetime | None = None  # inclusive, UTC
    end: datetime | None = None  # exclusive, UTC
    sort: str = "journal_at"
    descending: bool = True
    limit: int = 100
    offset: int = 0


class TradeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, trade: Trade) -> Trade:
        self.session.add(trade)
        self.session.flush()
        return trade

    def get(self, trade_id: int) -> Trade | None:
        return self.session.get(Trade, trade_id)

    def delete(self, trade: Trade) -> None:
        self.session.delete(trade)
        self.session.flush()

    def list(self, criteria: TradeCriteria) -> tuple[Sequence[Trade], int]:
        filters = []
        if criteria.instrument:
            filters.append(Trade.instrument == criteria.instrument)
        if criteria.side:
            filters.append(Trade.side == criteria.side)
        if criteria.status == "open":
            filters.append(Trade.closed_at.is_(None))
        elif criteria.status == "closed":
            filters.append(Trade.closed_at.is_not(None))
        if criteria.start is not None:
            filters.append(JOURNAL_AT >= criteria.start)
        if criteria.end is not None:
            filters.append(JOURNAL_AT < criteria.end)
        for name in criteria.tags:
            filters.append(Trade.tags.any(Tag.name == name))

        total = self.session.scalar(select(func.count()).select_from(Trade).where(*filters)) or 0
        direction = desc if criteria.descending else asc
        order = [direction(SORT_COLUMNS[criteria.sort]).nulls_last(), direction(Trade.id)]
        rows = self.session.scalars(
            select(Trade).where(*filters).order_by(*order).limit(criteria.limit).offset(criteria.offset)
        ).all()
        return rows, total

    def set_tags(self, trade: Trade, names: Sequence[str]) -> None:
        """Replace the trade's tags, creating missing ones. `names` are already normalized."""
        if not names:
            trade.tags = []
            return
        existing = {tag.name.casefold(): tag for tag in self.session.scalars(select(Tag).where(Tag.name.in_(names)))}
        tags = []
        for name in names:
            tag = existing.get(name.casefold())
            if tag is None:
                tag = existing[name.casefold()] = Tag(name=name)
                self.session.add(tag)
            tags.append(tag)
        trade.tags = tags

    def collect_orphan_tags(self) -> None:
        """Delete tags no trade uses any more."""
        self.session.flush()
        unused = ~exists().where(trade_tags.c.tag_id == Tag.id)
        self.session.execute(delete(Tag).where(unused).execution_options(synchronize_session=False))


class TagRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def usage(self) -> list[tuple[str, int]]:
        count = func.count(trade_tags.c.trade_id)
        rows = self.session.execute(
            select(Tag.name, count)
            .join(trade_tags, trade_tags.c.tag_id == Tag.id)
            .group_by(Tag.id)
            .order_by(desc(count), Tag.name)
        ).all()
        return [(name, used) for name, used in rows]


class NoteRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, note: Note) -> Note:
        self.session.add(note)
        self.session.flush()
        return note

    def get(self, note_id: int) -> Note | None:
        return self.session.get(Note, note_id)

    def delete(self, note: Note) -> None:
        self.session.delete(note)
        self.session.flush()

    def list(self, start: date | None, end: date | None, limit: int, offset: int) -> tuple[Sequence[Note], int]:
        filters = []
        if start is not None:
            filters.append(Note.day >= start)
        if end is not None:
            filters.append(Note.day <= end)
        total = self.session.scalar(select(func.count()).select_from(Note).where(*filters)) or 0
        rows = self.session.scalars(
            select(Note).where(*filters).order_by(Note.day.desc(), Note.id.desc()).limit(limit).offset(offset)
        ).all()
        return rows, total


class EventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def by_source(self, source: str) -> dict[str, ExternalEvent]:
        return {row.external_key: row for row in self.session.scalars(select(ExternalEvent).where(ExternalEvent.source == source))}

    def add(self, event: ExternalEvent) -> None:
        self.session.add(event)

    def delete(self, event: ExternalEvent) -> None:
        self.session.delete(event)

    def count(self, source: str) -> int:
        return self.session.scalar(select(func.count()).select_from(ExternalEvent).where(ExternalEvent.source == source)) or 0

    def candidates(
        self,
        *,
        start: datetime | None,
        end: datetime | None,
        first_day: date | None,
        last_day: date | None,
        source: str | None,
        impacts: Sequence[str],
        currency: str | None,
    ) -> Sequence[ExternalEvent]:
        """Rows that may overlap the window. `start` and `end` (UTC) are generous: the caller decides exactly which
        local days an event covers. All-day events are compared by date, timed ones by instant."""
        filters = []
        if source:
            filters.append(ExternalEvent.source == source)
        if impacts:
            filters.append(ExternalEvent.impact.in_(impacts))
        if currency:
            filters.append(ExternalEvent.currency.in_([currency, "ALL"]))  # an event for every currency concerns this one too
        timed = [ExternalEvent.all_day.is_(False)]
        all_day = [ExternalEvent.all_day.is_(True)]
        if start is not None:
            timed.append(func.coalesce(ExternalEvent.end_at, ExternalEvent.start_at, type_=UtcDateTime()) >= start)
        if end is not None:
            timed.append(ExternalEvent.start_at < end)
        if first_day is not None:
            all_day.append(ExternalEvent.end_date > first_day)
        if last_day is not None:
            all_day.append(ExternalEvent.start_date <= last_day)
        filters.append(or_(and_(*timed), and_(*all_day)))
        return self.session.scalars(select(ExternalEvent).where(*filters)).all()


class FeedStateRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, source: str) -> FeedState | None:
        return self.session.get(FeedState, source)

    def ensure(self, source: str, now: datetime) -> FeedState:
        """The row for `source`, created due-now the first time so a new feed is fetched at startup."""
        state = self.get(source)
        if state is None:
            state = FeedState(source=source, state="idle", status="never", consecutive_failures=0, next_due_at=now, updated_at=now)
            self.session.add(state)
            self.session.flush()
        return state
