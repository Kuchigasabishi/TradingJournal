"""Trade request and response models. Cross-field rules live in the service (see closure_errors)."""
from pydantic import AwareDatetime, BaseModel, ConfigDict

from app.db.models import Trade
from app.schemas.common import (
    Instrument,
    Money,
    MoneyOut,
    OptionalText,
    PositiveMoney,
    Side,
    Status,
    Tags,
    UtcDatetime,
)
from typing import Literal


class TradeCreate(BaseModel):
    """A trade is open (no exit_price, closed_at or pnl) or closed (all three). pnl is entered by the user."""

    model_config = ConfigDict(extra="forbid")

    instrument: Instrument
    side: Side
    lot_size: PositiveMoney
    entry_price: PositiveMoney
    opened_at: UtcDatetime
    exit_price: PositiveMoney | None = None
    closed_at: UtcDatetime | None = None
    pnl: Money | None = None
    notes: OptionalText = None
    tags: Tags = []


class TradeUpdate(BaseModel):
    """Partial update (JSON merge patch): omitted fields stay, an explicit null clears optional ones."""

    model_config = ConfigDict(extra="forbid")

    instrument: Instrument | None = None
    side: Side | None = None
    lot_size: PositiveMoney | None = None
    entry_price: PositiveMoney | None = None
    opened_at: UtcDatetime | None = None
    exit_price: PositiveMoney | None = None
    closed_at: UtcDatetime | None = None
    pnl: Money | None = None
    notes: OptionalText = None
    tags: Tags | None = None


class TradeRead(BaseModel):
    id: int
    instrument: str
    side: Literal["long", "short"]
    lot_size: MoneyOut
    entry_price: MoneyOut
    exit_price: MoneyOut | None
    opened_at: AwareDatetime
    closed_at: AwareDatetime | None
    pnl: MoneyOut | None
    notes: str | None
    tags: list[str]
    status: Status
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @classmethod
    def from_trade(cls, trade: Trade) -> "TradeRead":
        return cls(
            id=trade.id,
            instrument=trade.instrument,
            side=trade.side,
            lot_size=trade.lot_size,
            entry_price=trade.entry_price,
            exit_price=trade.exit_price,
            opened_at=trade.opened_at,
            closed_at=trade.closed_at,
            pnl=trade.pnl,
            notes=trade.notes,
            tags=[tag.name for tag in trade.tags],
            status="closed" if trade.closed_at is not None else "open",
            created_at=trade.created_at,
            updated_at=trade.updated_at,
        )


class TagUsage(BaseModel):
    name: str
    count: int
