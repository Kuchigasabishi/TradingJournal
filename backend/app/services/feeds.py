"""Feed synchronization (docs/BLUEPRINT.md, section 4.3).

A sync fetches a feed, parses it, reconciles the stored events with it and records the outcome, all without holding
a database transaction open while the network is slow. Where each feed stands (its schedule, the last outcome, its
backoff) is persisted in `feed_state`, so a restart never refetches early and a failure never loses events: a
failed fetch leaves the stored rows exactly as they were.
"""
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, time as clock_time, timedelta, timezone

from sqlalchemy.orm import Session, sessionmaker

from app.connectors.base import STATUS_OK, FeedError, NormalizedEvent, clip
from app.connectors.registry import Source
from app.core.clock import Clock
from app.core.config import Settings
from app.db.models import ExternalEvent, FeedState
from app.db.repositories import EventRepository, FeedStateRepository
from app.schemas.events import SourceStatus, SyncResult
from app.services.uow import transaction

log = logging.getLogger("app.feeds")

# After a failure, wait this long before the next scheduled attempt: 15, 30, 60, then 120 minutes (the cap).
BACKOFF_MINUTES = (15, 30, 60, 120)
_FIELDS = ("title", "description", "location", "url", "currency", "impact", "forecast", "previous", "all_day", "start_at", "end_at", "start_date", "end_date")


@dataclass
class Counts:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0


def _instant(item: NormalizedEvent | ExternalEvent) -> datetime:
    """When an event starts, as an instant. An all-day event starts at midnight UTC of its date, which is all this is used for."""
    return item.start_at or datetime.combine(item.start_date, clock_time.min, tzinfo=timezone.utc)


def _apply(row: ExternalEvent, event: NormalizedEvent) -> bool:
    changed = False
    for name in _FIELDS:
        value = getattr(event, name)
        if getattr(row, name) != value:
            setattr(row, name, value)
            changed = True
    return changed


def reconcile(repo: EventRepository, source: Source, events: list[NormalizedEvent], now: datetime) -> Counts:
    """Make the stored events agree with what the feed holds now, by the source's policy (see registry.Reconcile)."""
    existing = repo.by_source(source.name)
    incoming = {event.key: event for event in events}
    counts = Counts()
    for key, event in incoming.items():
        row = existing.get(key)
        if row is None:
            row = ExternalEvent(source=source.name, external_key=key, first_seen_at=now, updated_at=now)
            for name in _FIELDS:
                setattr(row, name, getattr(event, name))
            repo.add(row)
            counts.added += 1
        elif _apply(row, event):
            row.updated_at = now
            counts.updated += 1
        else:
            counts.unchanged += 1

    gone = [row for key, row in existing.items() if key not in incoming]
    if source.reconcile == "upsert_window" and incoming:
        low, high = min(_instant(e) for e in events), max(_instant(e) for e in events)
        # Only what is still to come, inside the week the feed covers: a past event is history and stays.
        gone = [row for row in gone if _instant(row) > now and low <= _instant(row) <= high]
    elif source.reconcile == "upsert_window":
        gone = []
    for row in gone:
        repo.delete(row)
        counts.removed += 1
    return counts


class FeedService:
    def __init__(self, session_factory: sessionmaker[Session], settings: Settings, clock: Clock, sources: dict[str, Source]) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.clock = clock
        self.sources = sources

    # --- what the API shows ------------------------------------------------------------------------

    def status(self, session: Session) -> list[SourceStatus]:
        states, events = FeedStateRepository(session), EventRepository(session)
        result = []
        for source in self.sources.values():
            state = states.get(source.name)
            result.append(
                SourceStatus(
                    source=source.name,  # type: ignore[arg-type]
                    label=source.label,
                    enabled=source.enabled,
                    disabled_reason=source.disabled_reason,
                    state=state.state if state else "idle",  # type: ignore[arg-type]
                    status=state.status if state else "never",  # type: ignore[arg-type]
                    message=state.message if state else None,
                    http_status=state.http_status if state else None,
                    last_attempt_at=state.last_attempt_at if state else None,
                    last_success_at=state.last_success_at if state else None,
                    next_due_at=state.next_due_at if state and source.enabled else None,
                    next_manual_at=state.next_manual_at if state else None,
                    consecutive_failures=state.consecutive_failures if state else 0,
                    event_count=events.count(source.name),
                    poll_minutes=source.poll_minutes,
                )
            )
        return result

    def request_sync(self, session: Session, names: list[str]) -> list[SyncResult]:
        """Queue a manual sync for each named source (all of them when `names` is empty) and return at once: the
        fetch happens on the source's own worker thread. A source that is disabled, already running or inside its
        cooldown is reported, not queued. The request's own transaction records the queue, so a request that was
        accepted is always backed by a commit."""
        now = self.clock.now()
        states = FeedStateRepository(session)
        results: list[SyncResult] = []
        with transaction(session):
            for name in names or list(self.sources):
                source = self.sources[name]
                if not source.enabled:
                    results.append(SyncResult(source=name, outcome="disabled"))  # type: ignore[arg-type]
                    continue
                state = states.ensure(name, now)
                if state.state in ("queued", "running"):
                    results.append(SyncResult(source=name, outcome="running"))  # type: ignore[arg-type]
                elif state.next_manual_at is not None and now < state.next_manual_at:
                    wait = math.ceil((state.next_manual_at - now).total_seconds())
                    results.append(SyncResult(source=name, outcome="cooldown", retry_after_seconds=wait))  # type: ignore[arg-type]
                else:
                    state.state = "queued"
                    state.next_manual_at = now + timedelta(seconds=self.settings.sync_cooldown_seconds)
                    state.updated_at = now
                    results.append(SyncResult(source=name, outcome="queued"))  # type: ignore[arg-type]
        return results

    # --- what the workers do -----------------------------------------------------------------------

    def prepare(self) -> None:
        """At startup: make sure every enabled feed has a state row, and clear a `running` mark a crash left behind."""
        now = self.clock.now()
        with self.session_factory() as session, transaction(session):
            states = FeedStateRepository(session)
            for source in self.sources.values():
                if source.enabled:
                    state = states.ensure(source.name, now)
                    if state.state == "running":
                        state.state = "idle"
                        state.next_due_at = now

    def next_work(self, name: str) -> tuple[str | None, float]:
        """(why to sync now, or None, and how many seconds until there is something to do)."""
        with self.session_factory() as session:
            state = FeedStateRepository(session).get(name)
            if state is None:
                return None, self.settings.feed_tick_seconds
            if state.state == "queued":
                return "manual", 0.0
            now = self.clock.now()
            if state.next_due_at is None or state.next_due_at <= now:
                return ("startup" if state.last_attempt_at is None else "schedule"), 0.0
            return None, (state.next_due_at - now).total_seconds()

    def run_sync(self, name: str, trigger: str) -> str:
        """One sync of one feed. Returns its outcome: ok, unchanged, throttled, bad_content or error."""
        source = self.sources[name]
        began = time.perf_counter()
        with self.session_factory() as session, transaction(session):
            state = FeedStateRepository(session).ensure(name, self.clock.now())
            state.state = "running"
            state.last_attempt_at = self.clock.now()
            state.updated_at = state.last_attempt_at
            etag, last_modified = state.etag, state.last_modified

        events: list[NormalizedEvent] | None = None
        items = dropped = 0
        problems: list[str] = []
        fetched_etag = fetched_modified = None
        failure: FeedError | None = None
        http_status: int | None = None
        outcome = STATUS_OK
        try:
            fetched = source.fetch(etag, last_modified)
            http_status = fetched.http_status
            if fetched.not_modified:
                outcome = "unchanged"
            else:
                parsed = source.parse(fetched.body, self.clock.now())
                events, items, dropped, problems = parsed.events, parsed.total, parsed.dropped, parsed.problems
                fetched_etag, fetched_modified = fetched.etag, fetched.last_modified
        except FeedError as error:
            failure, http_status, outcome = error, error.http_status, error.status
        except Exception:  # a bug in a parser must not kill the worker or leave the feed marked as running
            log.exception("feed_sync_crashed", extra={"feed": name})
            failure = FeedError("the feed could not be read because of an internal error; see the server log")
            outcome = failure.status

        counts, total, backoff = Counts(), 0, None
        now = self.clock.now()
        try:
            with self.session_factory() as session, transaction(session):
                repo = EventRepository(session)
                state = FeedStateRepository(session).ensure(name, now)
                if failure is None:
                    if events is not None:
                        counts = reconcile(repo, source, events, now)
                        state.etag, state.last_modified = fetched_etag, fetched_modified
                    state.status, state.message, state.http_status = STATUS_OK, None, http_status
                    state.consecutive_failures = 0
                    state.last_success_at = now
                    state.next_due_at = now + timedelta(minutes=source.poll_minutes)
                else:
                    state.status, state.message, state.http_status = failure.status, clip(failure.message, 200), http_status
                    state.consecutive_failures += 1
                    backoff = BACKOFF_MINUTES[min(state.consecutive_failures - 1, len(BACKOFF_MINUTES) - 1)]
                    state.next_due_at = now + timedelta(minutes=backoff)
                state.state = "idle"
                state.updated_at = now
                total = repo.count(name)
        except Exception:
            log.exception("feed_sync_not_stored", extra={"feed": name})
            self._mark_failed(name, "the events could not be stored; see the server log")
            outcome = "error"

        log.log(
            logging.INFO if outcome in (STATUS_OK, "unchanged") else logging.WARNING,
            "feed_sync",
            extra={
                "feed": name,
                "trigger": trigger,
                "outcome": outcome,
                "http_status": http_status,
                "host": source.host,
                "items": items,
                "dropped": dropped,
                "added": counts.added,
                "updated": counts.updated,
                "unchanged": counts.unchanged,
                "removed": counts.removed,
                "event_count": total,
                "backoff_minutes": backoff,
                "reason": failure.message if failure else None,
                "problems": problems[:3] or None,
                "duration_ms": round((time.perf_counter() - began) * 1000, 1),
            },
        )
        return outcome

    def _mark_failed(self, name: str, message: str) -> None:
        now = self.clock.now()
        with self.session_factory() as session, transaction(session):
            state = FeedStateRepository(session).ensure(name, now)
            state.state, state.status, state.message = "idle", "error", message
            state.consecutive_failures += 1
            state.next_due_at = now + timedelta(minutes=BACKOFF_MINUTES[min(state.consecutive_failures - 1, len(BACKOFF_MINUTES) - 1)])
            state.updated_at = now
