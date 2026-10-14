"""Types shared by the feed connectors (docs/BLUEPRINT.md, section 4.3).

A connector never touches the database. It fetches bytes and turns them into `NormalizedEvent`s, or raises a
`FeedError` that says what kind of trouble it was. Error messages are short fixed phrases: they never carry a
URL, because the Google Calendar address is a secret.
"""
from dataclasses import dataclass, field
from datetime import date, datetime

# Outcomes a sync can end in, in feed_state.status. `unchanged` is a success the server confirmed with a 304.
STATUS_OK = "ok"
STATUS_THROTTLED = "throttled"
STATUS_BAD_CONTENT = "bad_content"
STATUS_ERROR = "error"


class FeedError(Exception):
    """Something went wrong with a feed. `status` is the feed_state status it maps to."""

    status = STATUS_ERROR

    def __init__(self, message: str, *, http_status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.http_status = http_status


class Throttled(FeedError):
    """The host told us to slow down (HTTP 429, or its "Request Denied" page)."""

    status = STATUS_THROTTLED


class BadContent(FeedError):
    """The host answered, but not with a usable feed (HTML, truncated or malformed data, too many bad items)."""

    status = STATUS_BAD_CONTENT


class FetchFailed(FeedError):
    """No usable answer: the connection failed, timed out, or the host returned an error status."""

    status = STATUS_ERROR


@dataclass(frozen=True)
class NormalizedEvent:
    """One event, in the shape both connectors produce and the database stores.

    Timed events have `start_at` (UTC) and maybe `end_at`. All-day events have `start_date` and an exclusive
    `end_date`. News events carry currency, impact, forecast and previous; calendar events carry a description
    and a location.
    """

    source: str
    key: str
    title: str
    all_day: bool = False
    start_at: datetime | None = None
    end_at: datetime | None = None
    start_date: date | None = None
    end_date: date | None = None
    description: str | None = None
    location: str | None = None
    url: str | None = None
    currency: str | None = None
    impact: str | None = None
    forecast: str | None = None
    previous: str | None = None


@dataclass
class ParseResult:
    events: list[NormalizedEvent]
    total: int  # items the feed held, usable or not
    dropped: int = 0  # malformed or duplicated items that were left out
    problems: list[str] = field(default_factory=list)  # a few examples, for the log

    def ensure_usable(self) -> "ParseResult":
        """A feed where more than half of the items are unusable is not a feed we understand: refuse all of it."""
        if self.total > 0 and self.dropped * 2 > self.total:
            raise BadContent(f"{self.dropped} of {self.total} items were unusable")
        return self


@dataclass
class FetchResult:
    body: bytes = b""
    not_modified: bool = False
    http_status: int = 200
    etag: str | None = None
    last_modified: str | None = None


def clip(text: str | None, limit: int) -> str | None:
    """Trimmed text cut to `limit` characters, or None when nothing is left."""
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
