"""The owner's Google Calendar, read through its secret iCal address (docs/BLUEPRINT.md, D4 and section 4.3).

Parsing is done by `icalendar`, and recurring events are expanded by `recurring-ical-events`, because a calendar
is mostly recurrence rules, exceptions, moved instances and time zones, and none of that survives line-by-line
VEVENT parsing. What the expansion handles for us:

* weekly and other RRULE series, with EXDATE exceptions;
* moved instances (RECURRENCE-ID overrides) and cancelled instances (STATUS:CANCELLED, which we then drop);
* TZID zones, UTC times, all-day dates and DURATION, and Google's X-WR-TIMEZONE for times that carry no zone.

A time with no zone at all (floating) is read in the owner's time zone, APP_TIMEZONE.
"""
import hashlib
import html
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events

from app.connectors.base import BadContent, NormalizedEvent, ParseResult, clip

SOURCE = "gcal"
WINDOW_BEFORE = timedelta(days=60)
WINDOW_AFTER = timedelta(days=400)
MAX_INSTANCES = 5000  # a runaway rule must not fill the database
_PROBLEM_EXAMPLES = 5
_BREAKS = re.compile(r"<\s*(br\s*/?|/p|/div|/li|/tr)\s*>", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")
_BLANK_RUNS = re.compile(r"\n{3,}")


def plain_text(value: str | None, limit: int) -> str | None:
    """Google often writes descriptions as small HTML. The app shows text, so tags become line breaks or vanish."""
    if not value:
        return None
    if "<" in value and ">" in value:
        value = _TAGS.sub("", _BREAKS.sub("\n", value))
    value = html.unescape(value).replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    return clip(_BLANK_RUNS.sub("\n\n", value), limit)


def _utc(value, default_tz: ZoneInfo) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=default_tz)  # floating time: the owner's zone
    return value.astimezone(timezone.utc)


def _identity(component, recurring: bool) -> str:
    """Who an event is. A one-off event is its UID, so moving it updates its row. An occurrence of a recurring series
    is the UID plus which occurrence it is (the RECURRENCE-ID the library gives every instance), and a moved
    occurrence keeps the slot it was moved from, so moving it updates its row instead of replacing it."""
    uid = str(component.get("UID", ""))
    if not recurring:
        return hashlib.sha1(uid.encode("utf-8")).hexdigest()
    slot = component["RECURRENCE-ID"].dt
    stamp = slot.astimezone(timezone.utc).isoformat() if isinstance(slot, datetime) else slot.isoformat()
    return hashlib.sha1(f"{uid}|{stamp}".encode("utf-8")).hexdigest()


def _convert(component, recurring: bool, default_tz: ZoneInfo) -> NormalizedEvent:
    start, end = component.start, component.end
    title = clip(str(component.get("SUMMARY", "")), 300) or "(no title)"
    common = dict(
        source=SOURCE,
        key=_identity(component, recurring),
        title=title,
        description=plain_text(str(component["DESCRIPTION"]) if "DESCRIPTION" in component else None, 20_000),
        location=clip(str(component["LOCATION"]) if "LOCATION" in component else None, 300),
        url=clip(str(component["URL"]) if "URL" in component else None, 500),
    )
    if not isinstance(start, datetime):  # an all-day event: a date, and an exclusive end date
        end_date = end if isinstance(end, date) and not isinstance(end, datetime) and end > start else start + timedelta(days=1)
        return NormalizedEvent(all_day=True, start_date=start, end_date=end_date, **common)
    start_at = _utc(start, default_tz)
    end_at = _utc(end, default_tz) if isinstance(end, datetime) else None
    if end_at is not None and end_at <= start_at:
        end_at = None  # an instant, or a bad end: either way there is no span to draw
    return NormalizedEvent(start_at=start_at, end_at=end_at, **common)


def _expand(calendar: icalendar.Calendar, begin: datetime, finish: datetime):
    """The instances between `begin` and `finish`, series by series so that one broken series costs one series.

    Returns (instances, series_dropped, problems), each instance paired with whether it belongs to a recurring
    series. Each UID's events (the master and its overrides) are expanded in a small calendar of their own that keeps
    the zone definitions and X-WR-TIMEZONE.
    """
    shared = [component for component in calendar.subcomponents if component.name != "VEVENT"]
    groups: dict[str, list] = defaultdict(list)
    dropped, problems = 0, []
    for index, component in enumerate(c for c in calendar.subcomponents if c.name == "VEVENT"):
        if "DTSTART" not in component:  # the library cannot even load such an event, so it is dropped here
            dropped += 1
            problems.append(f"event {index}: no start")
            continue
        groups[str(component.get("UID", f"no-uid-{index}"))].append(component)

    instances = []
    for uid_index, components in enumerate(groups.values()):
        mini = icalendar.Calendar()
        for name in ("PRODID", "VERSION", "X-WR-TIMEZONE"):
            if name in calendar:
                mini[name] = calendar[name]
        for component in [*shared, *components]:
            mini.add_component(component)
        recurring = any(name in component for component in components for name in ("RRULE", "RDATE", "RECURRENCE-ID"))
        try:
            instances.extend((instance, recurring) for instance in recurring_ical_events.of(mini).between(begin, finish))
        except Exception as exc:  # the library raises its own error types for bad rules; any of them costs one series
            dropped += 1
            if len(problems) < _PROBLEM_EXAMPLES:
                problems.append(f"series {uid_index}: {type(exc).__name__}")
    return instances, dropped, problems


def parse(body: bytes, *, now: datetime, default_tz: ZoneInfo) -> ParseResult:
    """Events from `now` minus 60 days to `now` plus 400 days. Raises BadContent for anything that is not a calendar."""
    head = body.lstrip(b"\xef\xbb\xbf \t\r\n")[:32].upper()
    if not head.startswith(b"BEGIN:VCALENDAR"):
        raise BadContent("the address returned a web page or other data, not a calendar")
    # A complete calendar ends with END:VCALENDAR. Checking is what stops a download that was cut off, and that
    # icalendar would read as a calendar with fewer events, from being mirrored: the mirror would delete the rest.
    if not body.rstrip().upper().endswith(b"END:VCALENDAR"):
        raise BadContent("the calendar is cut off: it does not end with END:VCALENDAR")
    try:
        calendar = icalendar.Calendar.from_ical(body)
    except Exception as exc:  # icalendar raises ValueError and its own subclasses for malformed files
        raise BadContent(f"the calendar could not be parsed ({type(exc).__name__})") from None
    if not isinstance(calendar, icalendar.Calendar):
        raise BadContent("the data is not a calendar")

    instances, lost, problems = _expand(calendar, now - WINDOW_BEFORE, now + WINDOW_AFTER)
    events: dict[str, NormalizedEvent] = {}
    seen = unusable = 0
    for component, recurring in instances:
        if str(component.get("STATUS", "")).upper() == "CANCELLED":
            continue  # a cancelled instance is gone, not an event
        seen += 1
        try:
            event = _convert(component, recurring, default_tz)
        except Exception as exc:  # one malformed instance, for example a date mixed with a date-time
            unusable += 1
            if len(problems) < _PROBLEM_EXAMPLES:
                problems.append(f"instance: {type(exc).__name__}")
            continue
        if event.key in events:
            unusable += 1
            continue
        events[event.key] = event
        if len(events) >= MAX_INSTANCES:
            problems.append(f"stopped at {MAX_INSTANCES} events")
            break
    # `lost` counts events and series that never made it to instances; `seen` counts every live instance.
    return ParseResult(events=list(events.values()), total=seen + lost, dropped=unusable + lost, problems=problems).ensure_usable()
