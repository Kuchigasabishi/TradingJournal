"""Derives the ForexFactory fixture weeks from the two recorded originals.

    python fixtures/tools/build_forexfactory_fixtures.py

The originals in fixtures/forexfactory/recorded/ are the weekly export exactly as the host served it on 2026-10-13,
once as JSON and once as XML (line endings are LF already). This script writes four files next to them:

    week_a.json, week_a.xml   the same 108 events moved by whole weeks into the week of Sunday 2044-05-08
    week_b.json, week_b.xml   week A as it might look a day later: some events removed, changed, added or moved

A whole number of weeks keeps every weekday and, because both weeks fall in US daylight time, every New York clock
time. The suite pins its clock to Wednesday 2044-05-11 12:00 UTC (APP_NOW_OVERRIDE), so "this week" is always the
same week and the tests never depend on today's date. The script checks its own work: re-rendering the unmodified
events in each format must reproduce the shifted original byte for byte, which proves the templates match the real
export, and the two recorded formats must agree event by event.

It also writes synthetic_cp1252.xml, a small hand-made export with the awkward cases the real week happened not to
contain: windows-1252 bytes, entities, CDATA titles, and times that are not a time of day.
"""
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "forexfactory"
RECORDED = OUT / "recorded"
TARGET_SUNDAY = date(2044, 5, 8)  # the original week starts on Sunday 2026-10-11 (evening, New York time)
ORIGINAL_SUNDAY = date(2026, 10, 11)
SHIFT = TARGET_SUNDAY - ORIGINAL_SUNDAY
assert SHIFT.days % 7 == 0, "shift by whole weeks only"

XML_HEAD = '<?xml version="1.0" encoding="windows-1252"?>\n<weeklyevents>\n'
XML_TAIL = "</weeklyevents>\n"


# --- reading the recorded originals ---------------------------------------------------------------------


def read_json(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


_EVENT = re.compile(r"\t<event>\n(.*?)\t</event>\n", re.S)
_FIELD = re.compile(r"\t\t<(\w+)(?: />|>(?:<!\[CDATA\[(.*?)\]\]>|(.*?))</\1>)\n", re.S)


def read_xml(path: Path) -> list[dict]:
    text = path.read_bytes().decode("cp1252")
    events = []
    for block in _EVENT.findall(text):
        fields = {m.group(1): (m.group(2) if m.group(2) is not None else (m.group(3) or "")) for m in _FIELD.finditer(block)}
        events.append(fields)
    return events


# --- writing the two formats ----------------------------------------------------------------------------


def render_json(events: list[dict]) -> str:
    # PHP's json_encode, which is what the host runs, escapes forward slashes.
    return json.dumps(events, separators=(",", ":"), ensure_ascii=True).replace("/", "\\/")


def _cdata(tag: str, value: str) -> str:
    return f"\t\t<{tag}><![CDATA[{value}]]></{tag}>\n" if value else f"\t\t<{tag} />\n"


def render_xml(events: list[dict]) -> str:
    out = [XML_HEAD]
    for e in events:
        out.append("\t<event>\n")
        out.append(f"\t\t<title>{escape(e['title'])}</title>\n")
        out.append(f"\t\t<country>{escape(e['country'])}</country>\n")
        for tag in ("date", "time", "impact", "forecast", "previous", "url"):
            out.append(_cdata(tag, e[tag]))
        out.append("\t</event>\n")
    out.append(XML_TAIL)
    return "".join(out)


# --- the shared model: one dict per event, in UTC ---------------------------------------------------------


def from_json_events(raw: list[dict]) -> list[dict]:
    """Recorded JSON to the shared model. The JSON carries no url, so that field stays empty here."""
    events = []
    for item in raw:
        when = datetime.fromisoformat(item["date"]).astimezone(timezone.utc)
        events.append({**item, "when": when})
    return events


def to_xml_fields(event: dict, url: str) -> dict:
    when: datetime = event["when"]
    hour = when.hour % 12 or 12
    return {
        "title": event["title"],
        "country": event["country"],
        "date": when.strftime("%m-%d-%Y"),
        "time": f"{hour}:{when.minute:02d}{'am' if when.hour < 12 else 'pm'}",
        "impact": event["impact"],
        "forecast": event["forecast"],
        "previous": event["previous"],
        "url": url,
    }


def to_json_item(event: dict, offset_hours: int = -4) -> dict:
    local = event["when"].astimezone(timezone(timedelta(hours=offset_hours)))
    return {
        "title": event["title"],
        "country": event["country"],
        "date": local.isoformat(),
        "impact": event["impact"],
        "forecast": event["forecast"],
        "previous": event["previous"],
    }


def check_recorded(json_events: list[dict], xml_events: list[dict]) -> None:
    assert len(json_events) == len(xml_events) == 108, (len(json_events), len(xml_events))
    for j, x in zip(json_events, xml_events):
        expected = to_xml_fields(j, x["url"])
        assert expected == x, (expected, x)


def shifted(events: list[dict]) -> list[dict]:
    return [{**e, "when": e["when"] + SHIFT} for e in events]


# --- week B: the same week a day later ---------------------------------------------------------------------


def make_week_b(week_a: list[dict]) -> list[dict]:
    def find(title: str, currency: str, weekday: str, hhmm: str) -> dict:
        matches = [e for e in week_a if e["title"] == title and e["country"] == currency and e["when"].strftime("%a %H:%M") == f"{weekday} {hhmm}"]
        assert len(matches) == 1, (title, currency, weekday, hhmm, len(matches))
        return matches[0]

    b = [dict(e) for e in week_a]
    by_id = {id(e): e for e in b}

    def clone(source: dict) -> dict:
        return next(e for e in b if e["title"] == source["title"] and e["country"] == source["country"] and e["when"] == source["when"])

    # The clock is Wednesday 2044-05-11 12:00 UTC: everything on Wednesday morning and before is past, the rest is future.
    removed_future = clone(find("Unemployment Claims", "USD", "Thu", "12:30"))
    forecast_changed = clone(find("Core Retail Sales m/m", "USD", "Thu", "12:30"))
    impact_changed = clone(find("BOE Gov Bailey Speaks", "GBP", "Thu", "07:30"))
    moved = clone(find("BOC Gov Macklem Speaks", "CAD", "Fri", "04:15"))
    removed_past = clone(find("MPC Member Mann Speaks", "GBP", "Mon", "12:50"))

    forecast_changed["forecast"] = "0.5%"
    impact_changed["impact"] = "Low"
    moved["when"] = moved["when"] + timedelta(minutes=30)
    b = [e for e in b if e is not removed_future and e is not removed_past]
    b.append({"title": "Cash Rate", "country": "AUD", "when": datetime(2044, 5, 12, 4, 30, tzinfo=timezone.utc), "impact": "High", "forecast": "4.35%", "previous": "4.35%"})
    b.sort(key=lambda e: e["when"])  # the host lists a week in time order
    del by_id
    return b


# --- synthetic edge cases ---------------------------------------------------------------------------------


def synthetic_cp1252() -> bytes:
    text = (
        XML_HEAD
        + "\t<event>\n\t\t<title>Fed’s Beige Book &amp; Outlook</title>\n\t\t<country>USD</country>\n"
        + _cdata("date", "05-11-2044") + _cdata("time", "6:00pm") + _cdata("impact", "Medium") + _cdata("forecast", "") + _cdata("previous", "")
        + _cdata("url", "https://www.forexfactory.com/calendar/1-example") + "\t</event>\n"
        + "\t<event>\n\t\t<title><![CDATA[Riksbank Gov Thedéen Speaks]]></title>\n\t\t<country>SEK</country>\n"
        + _cdata("date", "05-12-2044") + _cdata("time", "9:15am") + _cdata("impact", "Low") + _cdata("forecast", "") + _cdata("previous", "")
        + _cdata("url", "") + "\t</event>\n"
        + "\t<event>\n\t\t<title>OPEC-JMMC Meetings</title>\n\t\t<country>All</country>\n"
        + _cdata("date", "05-12-2044") + _cdata("time", "All Day") + _cdata("impact", "Non-Economic") + _cdata("forecast", "") + _cdata("previous", "")
        + _cdata("url", "") + "\t</event>\n"
        + "\t<event>\n\t\t<title>G7 Leaders Summit</title>\n\t\t<country>All</country>\n"
        + _cdata("date", "05-13-2044") + _cdata("time", "Tentative") + _cdata("impact", "Low") + _cdata("forecast", "") + _cdata("previous", "")
        + _cdata("url", "") + "\t</event>\n"
        + XML_TAIL
    )
    return text.encode("cp1252")


# --- main -----------------------------------------------------------------------------------------------------


def main() -> int:
    recorded_json = read_json(RECORDED / "ff_calendar_thisweek_2026-10-13.json")
    recorded_xml = read_xml(RECORDED / "ff_calendar_thisweek_2026-10-13.xml")
    json_events = from_json_events(recorded_json)
    check_recorded(json_events, recorded_xml)
    urls = [x["url"] for x in recorded_xml]

    # The templates must reproduce the recorded files exactly, before anything is shifted or changed.
    assert render_json([to_json_item(e) for e in json_events]) == (RECORDED / "ff_calendar_thisweek_2026-10-13.json").read_text(encoding="utf-8"), "JSON template drifted"
    assert render_xml([to_xml_fields(e, u) for e, u in zip(json_events, urls)]).encode("cp1252") == (RECORDED / "ff_calendar_thisweek_2026-10-13.xml").read_bytes(), "XML template drifted"

    week_a = shifted(json_events)
    url_of = {(e["title"], e["country"], e["when"]): u for e, u in zip(week_a, urls)}
    week_b = make_week_b(week_a)

    def write(name: str, events: list[dict]) -> None:
        (OUT / f"{name}.json").write_text(render_json([to_json_item(e) for e in events]), encoding="utf-8", newline="\n")
        xml = render_xml([to_xml_fields(e, url_of.get((e["title"], e["country"], e["when"]), "")) for e in events])
        (OUT / f"{name}.xml").write_bytes(xml.encode("cp1252"))
        print(f"{name}: {len(events)} events")

    write("week_a", week_a)
    write("week_b", week_b)
    (OUT / "synthetic_cp1252.xml").write_bytes(synthetic_cp1252())
    print("synthetic_cp1252.xml written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
