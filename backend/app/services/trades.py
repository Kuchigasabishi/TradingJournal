"""Trade use cases: whole-state validation, tag handling, the transaction, and domain log records.

Log records carry ids, the instrument, the side and the names of changed fields, never amounts or
note text.
"""
import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.errors import InvalidStateError, NotFoundError, field_error
from app.db.models import Trade
from app.db.repositories import TradeCriteria, TradeRepository
from app.schemas.trades import TradeCreate, TradeUpdate
from app.services.uow import transaction

log = logging.getLogger("app.journal")

NON_NULLABLE = ("instrument", "side", "lot_size", "entry_price", "opened_at")


@dataclass(frozen=True)
class TradeState:
    instrument: str
    side: str
    lot_size: Decimal
    entry_price: Decimal
    opened_at: datetime
    exit_price: Decimal | None
    closed_at: datetime | None
    pnl: Decimal | None
    notes: str | None
    tags: list[str]

    @classmethod
    def of(cls, trade: Trade) -> "TradeState":
        return cls(
            instrument=trade.instrument,
            side=trade.side,
            lot_size=trade.lot_size,
            entry_price=trade.entry_price,
            opened_at=trade.opened_at,
            exit_price=trade.exit_price,
            closed_at=trade.closed_at,
            pnl=trade.pnl,
            notes=trade.notes,
            tags=[tag.name for tag in trade.tags],
        )


def closure_errors(state: TradeState) -> list[dict[str, Any]]:
    """A trade is open (no closing data) or closed (all of it). This is the single source of that rule."""
    errors = []
    if state.closed_at is not None:
        if state.exit_price is None:
            errors.append(field_error("exit_price", "exit_price is required when closed_at is set", "closure.required"))
        if state.pnl is None:
            errors.append(field_error("pnl", "pnl is required when closed_at is set: enter the realized P&L", "closure.required"))
        if state.closed_at < state.opened_at:
            errors.append(field_error("closed_at", "closed_at must not be earlier than opened_at", "closure.order"))
    else:
        if state.exit_price is not None:
            errors.append(field_error("exit_price", "exit_price is only allowed on a closed trade: set closed_at as well", "closure.unexpected"))
        if state.pnl is not None:
            errors.append(field_error("pnl", "pnl is only allowed on a closed trade: set closed_at as well", "closure.unexpected"))
    return errors


def local_day_start(day: date, tz: ZoneInfo) -> datetime:
    """The first instant of `day` in `tz`, as UTC."""
    return datetime.combine(day, time.min, tzinfo=tz).astimezone(timezone.utc)


class TradeService:
    def __init__(self, session: Session, tz: ZoneInfo) -> None:
        self.session = session
        self.tz = tz
        self.repo = TradeRepository(session)

    def create(self, data: TradeCreate) -> Trade:
        state = TradeState(**data.model_dump())
        if errors := closure_errors(state):
            raise InvalidStateError(errors)
        trade = Trade(**{name: getattr(state, name) for name in state.__dataclass_fields__ if name != "tags"})
        with transaction(self.session):
            self.repo.add(trade)
            self.repo.set_tags(trade, state.tags)
        self.session.refresh(trade)  # the response is what the database actually stored
        log.info("trade_created", extra=self._facts(trade))
        return trade

    def get(self, trade_id: int) -> Trade:
        trade = self.repo.get(trade_id)
        if trade is None:
            raise NotFoundError("Trade", trade_id)
        return trade

    def list(
        self,
        *,
        instrument: str | None,
        side: str | None,
        status: str | None,
        tags: Sequence[str],
        from_day: date | None,
        to_day: date | None,
        sort: str,
        descending: bool,
        limit: int,
        offset: int,
    ) -> tuple[Sequence[Trade], int]:
        if from_day and to_day and from_day > to_day:
            raise InvalidStateError([field_error("from", "from must not be later than to", "range", where="query")])
        try:
            start = local_day_start(from_day, self.tz) if from_day else None
            end = local_day_start(to_day + timedelta(days=1), self.tz) if to_day else None
        except (OverflowError, ValueError):
            raise InvalidStateError([field_error("from", "date is outside the supported range", "range", where="query")]) from None
        criteria = TradeCriteria(
            instrument=instrument,
            side=side,
            status=status,
            tags=tuple(tags),
            start=start,
            end=end,
            sort=sort,
            descending=descending,
            limit=limit,
            offset=offset,
        )
        return self.repo.list(criteria)

    def update(self, trade_id: int, patch: TradeUpdate) -> Trade:
        trade = self.get(trade_id)
        changes = patch.model_dump(exclude_unset=True)
        if nulls := [name for name in NON_NULLABLE if name in changes and changes[name] is None]:
            raise InvalidStateError([field_error(name, f"{name} cannot be null", "null_not_allowed") for name in nulls])
        merged = replace(TradeState.of(trade), **changes)
        if errors := closure_errors(merged):
            raise InvalidStateError(errors)
        with transaction(self.session):
            for name, value in changes.items():
                if name != "tags":
                    setattr(trade, name, value)
            if "tags" in changes:
                self.repo.set_tags(trade, changes["tags"])
                self.repo.collect_orphan_tags()
        self.session.refresh(trade)
        log.info("trade_updated", extra={**self._facts(trade), "changed_fields": sorted(changes)})
        return trade

    def delete(self, trade_id: int) -> None:
        trade = self.get(trade_id)
        facts = self._facts(trade)
        with transaction(self.session):
            self.repo.delete(trade)
            self.repo.collect_orphan_tags()
        log.info("trade_deleted", extra=facts)

    @staticmethod
    def _facts(trade: Trade) -> dict[str, Any]:
        return {
            "trade_id": trade.id,
            "instrument": trade.instrument,
            "side": trade.side,
            "status": "closed" if trade.closed_at is not None else "open",
            "tag_count": len(trade.tags),
        }
