from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import feed_scheduler, feed_service, get_session
from app.schemas.events import SourceName, SourceStatus, SyncResponse
from app.services.feeds import FeedService
from app.services.scheduler import FeedScheduler

router = APIRouter(prefix="/api", tags=["sync"])


@router.get("/sources/status", response_model=list[SourceStatus], openapi_extra={"x-phase": 3})
def sources_status(session: Session = Depends(get_session), feeds: FeedService = Depends(feed_service)) -> list[SourceStatus]:
    """Where each feed stands: its schedule, how its last attempt ended and how many events it holds. Never the feed's address."""
    return feeds.status(session)


@router.post(
    "/sync",
    response_model=SyncResponse,
    status_code=202,
    openapi_extra={"x-phase": 3},
    responses={
        409: {"model": SyncResponse, "description": "Nothing was queued: the sources are already syncing or disabled"},
        429: {"model": SyncResponse, "description": "Nothing was queued: the sources are inside their cooldown (see Retry-After)"},
    },
)
def sync(
    response: Response,
    source: list[SourceName] = Query(default_factory=list, description="Repeat to pick feeds. Leave out for all of them"),
    session: Session = Depends(get_session),
    feeds: FeedService = Depends(feed_service),
    scheduler: FeedScheduler | None = Depends(feed_scheduler),
) -> SyncResponse:
    """Ask for a refresh now. The answer comes at once: the fetch runs on the feed's own worker thread, so a slow
    host never holds up this request. Poll `GET /api/sources/status` to see it finish.

    202 when at least one feed was queued. Otherwise 429 with `Retry-After` when the feeds are inside their cooldown
    (between manual syncs), or 409 when they are already syncing or disabled. The body always says what happened to each.
    """
    results = feeds.request_sync(session, list(dict.fromkeys(source)))
    queued = [result.source for result in results if result.outcome == "queued"]
    for name in queued:
        if scheduler is not None:
            scheduler.poke(name)
    if not queued:
        waits = [result.retry_after_seconds for result in results if result.outcome == "cooldown" and result.retry_after_seconds]
        response.status_code = 429 if waits else 409
        if waits:
            response.headers["Retry-After"] = str(min(waits))
    return SyncResponse(sources=results)
