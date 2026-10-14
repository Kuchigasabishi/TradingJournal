"""ForexFactory's public weekly economic calendar (docs/BLUEPRINT.md, D3 and section 4.3).

The host publishes one export in two forms, JSON and XML, and this parser reads both and produces identical
events. The forms were compared event by event on 2026-10-13 (108 of 108 identical), which settled what the
XML does not say:

* JSON carries an ISO 8601 instant with an offset, for example `2026-10-11T19:00:00-04:00` (New York in summer).
* XML carries a date as `MM-DD-YYYY` and a time as `h:mmam` or `h:mmpm`, with no zone. They are **UTC**: the same
  event is `10-11-2026` and `11:00pm`, which is that same 19:00 in New York.
* XML is declared `windows-1252` and wraps most values in CDATA.

Only the public export is read. No HTML page is ever scraped (D3).
"""
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

from app.connectors.base import BadContent, NormalizedEvent, ParseResult, Throttled, clip
from app.connectors.http import looks_like_denial

SOURCE = "forexfactory"
IMPACTS = {"low": "low", "medium": "medium", "high": "high", "holiday": "holiday"}
_TIME = re.compile(r"^(\d{1,2}):(\d{2})\s*([ap]m)$", re.IGNORECASE)
_PROBLEM_EXAMPLES = 5


def impact_of(text: str | None) -> str:
    """Low, Medium, High or Holiday, whatever the case. Anything else is kept as `unknown` rather than guessed."""
    return IMPACTS.get((text or "").strip().lower(), "unknown")


def currency_of(text: str | None) -> str | None:
    value = (text or "").strip().upper()
    return value[:12] or None  # "All" becomes ALL: an event that concerns every currency


def make_key(title: str, currency: str | None, when: datetime | date) -> str:
    """The feed has no ids, so an event is identified by what it is, for whom, and when."""
    stamp = when.astimezone(timezone.utc).isoformat() if isinstance(when, datetime) else when.isoformat()
    return hashlib.sha1(f"{title}|{currency or ''}|{stamp}".encode("utf-8")).hexdigest()


def _event(title, currency, when, impact, forecast, previous, url) -> NormalizedEvent:
    key = make_key(title, currency, when)
    common = dict(
        source=SOURCE, key=key, title=title, currency=currency, impact=impact,
        forecast=clip(forecast, 40), previous=clip(previous, 40), url=clip(url, 500),
    )
    if isinstance(when, datetime):
        return NormalizedEvent(start_at=when.astimezone(timezone.utc), **common)
    return NormalizedEvent(all_day=True, start_date=when, end_date=when + timedelta(days=1), **common)


def _title(raw) -> str:
    title = clip(raw if isinstance(raw, str) else None, 300)
    if not title:
        raise ValueError("no title")
    return title


# --- JSON --------------------------------------------------------------------------------------------


def _from_json_item(item) -> NormalizedEvent:
    if not isinstance(item, dict):
        raise ValueError("not an object")
    title = _title(item.get("title"))
    raw_date = item.get("date")
    if not isinstance(raw_date, str):
        raise ValueError("no date")
    try:
        when = datetime.fromisoformat(raw_date)
    except ValueError:
        raise ValueError("date is not ISO 8601") from None
    if when.tzinfo is None:
        raise ValueError("date has no UTC offset")
    return _event(
        title, currency_of(item.get("country")), when, impact_of(item.get("impact")),
        item.get("forecast") if isinstance(item.get("forecast"), str) else None,
        item.get("previous") if isinstance(item.get("previous"), str) else None,
        item.get("url") if isinstance(item.get("url"), str) else None,
    )


def _parse_json(body: bytes) -> ParseResult:
    try:
        data = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise BadContent("the feed is not valid JSON") from None
    if not isinstance(data, list):
        raise BadContent("the feed JSON is not a list of events")
    return _collect(data, _from_json_item)


# --- XML ---------------------------------------------------------------------------------------------


def _text(element: ET.Element, tag: str) -> str | None:
    value = element.findtext(tag)
    return value.strip() if value is not None else None


def _from_xml_event(element: ET.Element) -> NormalizedEvent:
    title = _title(_text(element, "title"))
    raw_date = _text(element, "date")
    try:
        day = datetime.strptime(raw_date or "", "%m-%d-%Y").date()
    except ValueError:
        raise ValueError("date is not MM-DD-YYYY") from None
    raw_time = _text(element, "time") or ""
    match = _TIME.match(raw_time)
    if match:
        hour, minute, meridiem = int(match.group(1)), int(match.group(2)), match.group(3).lower()
        if not (1 <= hour <= 12 and minute < 60):
            raise ValueError("time is not h:mmam or h:mmpm")
        hour = hour % 12 + (12 if meridiem == "pm" else 0)
        when: datetime | date = datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc)
    else:
        when = day  # "All Day", "Tentative" and the like have no time of day, so the event holds its date
    return _event(
        title, currency_of(_text(element, "country")), when, impact_of(_text(element, "impact")),
        _text(element, "forecast"), _text(element, "previous"), _text(element, "url"),
    )


def _parse_xml(body: bytes) -> ParseResult:
    lowered = body.lower()
    # A weekly list has no use for a DTD, and entity declarations are how XML bombs are built.
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise BadContent("XML with a DOCTYPE or entity declarations is refused")
    try:
        root = ET.fromstring(body)  # the bytes carry their own encoding declaration (windows-1252)
    except ET.ParseError:
        raise BadContent("the feed is not valid XML") from None
    if root.tag != "weeklyevents":
        raise BadContent("the feed XML is not a weekly events list")
    return _collect(root.findall("event"), _from_xml_event)


# --- shared ------------------------------------------------------------------------------------------


def _collect(items, convert) -> ParseResult:
    events: dict[str, NormalizedEvent] = {}
    dropped, problems = 0, []

    def drop(reason: str) -> None:
        nonlocal dropped
        dropped += 1
        if len(problems) < _PROBLEM_EXAMPLES:
            problems.append(reason)

    for index, item in enumerate(items):
        try:
            event = convert(item)
        except ValueError as exc:
            drop(f"item {index}: {exc}")
            continue
        if event.key in events:
            drop(f"item {index}: duplicates an earlier event")
            continue
        events[event.key] = event
    return ParseResult(events=list(events.values()), total=len(items), dropped=dropped, problems=problems)


def parse(body: bytes) -> ParseResult:
    """Reads the JSON or the XML form of the export, whichever `body` is. The content type is not trusted."""
    head = body.lstrip(b"\xef\xbb\xbf \t\r\n")[:64]
    if head[:1] in (b"[", b"{"):
        result = _parse_json(body)
    elif head.startswith(b"<?xml") or head.lower().startswith(b"<weeklyevents"):
        result = _parse_xml(body)
    elif head.startswith(b"<"):
        # HTML, or some other markup. The host's over-limit page is HTML, and is a different problem from garbage.
        if looks_like_denial(body):
            raise Throttled("the host answered with its request-denied page")
        raise BadContent("the feed is HTML, not JSON or XML")
    else:
        raise BadContent("the feed is neither JSON nor XML")
    if result.total == 0:
        raise BadContent("the feed held no events")
    return result.ensure_usable()
