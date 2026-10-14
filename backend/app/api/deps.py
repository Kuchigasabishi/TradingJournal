from collections.abc import Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.calendar import CalendarService
from app.services.events import EventService
from app.services.feeds import FeedService
from app.services.notes import NoteService
from app.services.scheduler import FeedScheduler
from app.services.trades import TradeService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_session(request: Request) -> Iterator[Session]:
    # Only closes the session. Services commit before the endpoint returns (see services/uow.py).
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def trade_service(session: Session = Depends(get_session), settings: Settings = Depends(get_settings)) -> TradeService:
    return TradeService(session, settings.tz)


def note_service(session: Session = Depends(get_session)) -> NoteService:
    return NoteService(session)


def calendar_service(session: Session = Depends(get_session), settings: Settings = Depends(get_settings)) -> CalendarService:
    return CalendarService(session, settings.tz)


def event_service(session: Session = Depends(get_session), settings: Settings = Depends(get_settings)) -> EventService:
    return EventService(session, settings.tz)


def feed_service(request: Request) -> FeedService:
    return request.app.state.feeds


def feed_scheduler(request: Request) -> FeedScheduler | None:
    return request.app.state.scheduler
