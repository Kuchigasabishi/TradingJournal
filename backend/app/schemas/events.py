"""API types for events from outside calendars, the feeds that supply them, and sync requests."""
from datetime import date
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field

SourceName = Literal["forexfactory", "gcal"]
Impact = Literal["low", "medium", "high", "holiday", "unknown"]
FeedStatus = Literal["never", "ok", "throttled", "bad_content", "error"]
FeedRunState = Literal["idle", "queued", "running"]
SyncOutcome = Literal["queued", "running", "cooldown", "disabled"]


class EventRead(BaseModel):
    """One event. Timed events carry UTC instants; all-day events carry only days. `start_day` and `end_day` (inclusive)
    are the calendar days the event covers in the server's APP_TIMEZONE, so a client never has to work them out."""

    id: int
    source: SourceName
    title: str
    description: str | None
    location: str | None
    url: str | None
    currency: str | None = Field(description="News only: a currency code such as USD, or ALL for an event that concerns every currency")
    impact: Impact | None = Field(description="News only")
    forecast: str | None
    previous: str | None
    all_day: bool
    start_at: AwareDatetime | None
    end_at: AwareDatetime | None
    start_day: date
    end_day: date
    updated_at: AwareDatetime


class SourceStatus(BaseModel):
    """Where one feed stands. Never carries the feed's address: the Google Calendar address is a secret."""

    source: SourceName
    label: str
    enabled: bool
    disabled_reason: str | None
    state: FeedRunState
    status: FeedStatus = Field(description="How the last attempt ended; never means no attempt yet")
    message: str | None = Field(description="A short, plain reason when the last attempt did not succeed")
    http_status: int | None
    last_attempt_at: AwareDatetime | None
    last_success_at: AwareDatetime | None
    next_due_at: AwareDatetime | None
    next_manual_at: AwareDatetime | None = Field(description="Earliest instant a manual sync is accepted again")
    consecutive_failures: int
    event_count: int
    poll_minutes: int


class SyncResult(BaseModel):
    source: SourceName
    outcome: SyncOutcome
    retry_after_seconds: int | None = Field(None, description="Set when the outcome is cooldown")


class SyncResponse(BaseModel):
    sources: list[SyncResult]
