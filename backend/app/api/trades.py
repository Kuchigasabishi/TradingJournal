from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query, Response

from app.api.deps import trade_service
from app.schemas.common import Page, Side, Status, normalize_instrument, normalize_tag
from app.schemas.trades import TradeCreate, TradeRead, TradeUpdate
from app.services.trades import TradeService

router = APIRouter(prefix="/api/trades", tags=["trades"])

TradeId = Path(ge=1, description="Trade id")


@router.post("", response_model=TradeRead, status_code=201)
def create_trade(body: TradeCreate, response: Response, service: TradeService = Depends(trade_service)) -> TradeRead:
    """Create a trade. Leave exit_price, closed_at and pnl out for an open trade."""
    trade = service.create(body)
    response.headers["Location"] = f"/api/trades/{trade.id}"
    return TradeRead.from_trade(trade)


@router.get("", response_model=Page[TradeRead])
def list_trades(
    from_day: date | None = Query(None, alias="from", description="First day, inclusive, in the server's APP_TIMEZONE"),
    to_day: date | None = Query(None, alias="to", description="Last day, inclusive, in the server's APP_TIMEZONE"),
    instrument: str | None = Query(None, description="Exact instrument, case-insensitive"),
    side: Side | None = None,
    status: Status | None = None,
    tag: list[str] = Query(default_factory=list, description="Repeat for several tags; a trade must carry all of them"),
    sort: Literal["journal_at", "opened_at", "closed_at", "pnl"] = "journal_at",
    order: Literal["asc", "desc"] = "desc",
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    service: TradeService = Depends(trade_service),
) -> Page[TradeRead]:
    """List trades. A trade belongs to the day it was closed, or the day it was opened while it is still open."""
    rows, total = service.list(
        instrument=normalize_instrument(instrument) if instrument else None,
        side=side,
        status=status,
        tags=[normalize_tag(name) for name in tag],
        from_day=from_day,
        to_day=to_day,
        sort=sort,
        descending=order == "desc",
        limit=limit,
        offset=offset,
    )
    return Page[TradeRead](items=[TradeRead.from_trade(trade) for trade in rows], total=total, limit=limit, offset=offset)


@router.get("/{trade_id}", response_model=TradeRead, responses={404: {"description": "No such trade"}})
def get_trade(trade_id: int = TradeId, service: TradeService = Depends(trade_service)) -> TradeRead:
    return TradeRead.from_trade(service.get(trade_id))


@router.patch("/{trade_id}", response_model=TradeRead, responses={404: {"description": "No such trade"}})
def update_trade(body: TradeUpdate, trade_id: int = TradeId, service: TradeService = Depends(trade_service)) -> TradeRead:
    """Partial update. Send null to clear exit_price, closed_at, pnl or notes; set all three closing fields to reopen."""
    return TradeRead.from_trade(service.update(trade_id, body))


@router.delete("/{trade_id}", status_code=204, responses={404: {"description": "No such trade"}})
def delete_trade(trade_id: int = TradeId, service: TradeService = Depends(trade_service)) -> Response:
    service.delete(trade_id)
    return Response(status_code=204)
