import json
from datetime import datetime, timedelta, timezone

import pytest

from app.connectors import forexfactory as ff
from app.connectors.base import BadContent, Throttled
from feed_helpers import fixture


def by_key(result):
    return {event.key: event for event in result.events}


# --- the two forms of the recorded export are the same data ---------------------------------------------------


def test_the_recorded_json_and_xml_agree_event_for_event():
    """The XML has no time zone. Reading its date and time as UTC makes all 108 events equal their JSON twins, whose
    offsets (-04:00) leave no doubt. If this ever fails, the XML time zone assumption is wrong."""
    as_json = ff.parse(fixture("forexfactory", "recorded", "ff_calendar_thisweek_2026-10-13.json"))
    as_xml = ff.parse(fixture("forexfactory", "recorded", "ff_calendar_thisweek_2026-10-13.xml"))
    assert (as_json.total, as_xml.total, as_json.dropped, as_xml.dropped) == (108, 108, 0, 0)
    json_events, xml_events = by_key(as_json), by_key(as_xml)
    assert json_events.keys() == xml_events.keys()
    for key, event in json_events.items():
        twin = xml_events[key]
        assert (event.title, event.currency, event.impact, event.forecast, event.previous, event.start_at) == (
            twin.title, twin.currency, twin.impact, twin.forecast, twin.previous, twin.start_at,
        )


def test_new_york_summer_time_is_four_hours_behind_utc_in_both_forms():
    first_json = ff.parse(fixture("forexfactory", "recorded", "ff_calendar_thisweek_2026-10-13.json")).events[0]
    first_xml = ff.parse(fixture("forexfactory", "recorded", "ff_calendar_thisweek_2026-10-13.xml")).events[0]
    # 19:00 on Sunday 11 October 2026 in New York, which is 23:00 UTC; the XML says 10-11-2026 and 11:00pm.
    assert first_json.start_at == first_xml.start_at == datetime(2026, 10, 11, 23, 0, tzinfo=timezone.utc)
    assert (first_json.title, first_json.currency, first_json.impact) == ("Bank Holiday", "JPY", "holiday")


def test_the_fixture_week_is_the_recorded_week_moved_by_whole_weeks():
    recorded = ff.parse(fixture("forexfactory", "recorded", "ff_calendar_thisweek_2026-10-13.json")).events
    week_a = ff.parse(fixture("forexfactory", "week_a.json")).events
    assert len(week_a) == 108
    for before, after in zip(recorded, week_a):
        shift = after.start_at - before.start_at
        assert shift.days % 7 == 0 and shift.seconds == 0
        assert (before.title, before.currency, before.impact, before.forecast) == (after.title, after.currency, after.impact, after.forecast)
    assert week_a[0].start_at == datetime(2044, 5, 8, 23, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("name", ["week_a", "week_b"])
def test_each_fixture_week_reads_the_same_from_json_and_from_xml(name):
    as_json, as_xml = by_key(ff.parse(fixture("forexfactory", f"{name}.json"))), by_key(ff.parse(fixture("forexfactory", f"{name}.xml")))
    assert as_json.keys() == as_xml.keys()
    assert all((as_json[k].start_at, as_json[k].impact, as_json[k].forecast) == (as_xml[k].start_at, as_xml[k].impact, as_xml[k].forecast) for k in as_json)


def test_week_b_differs_from_week_a_in_the_ways_the_readme_says():
    a, b = by_key(ff.parse(fixture("forexfactory", "week_a.json"))), by_key(ff.parse(fixture("forexfactory", "week_b.json")))
    gone, new = a.keys() - b.keys(), b.keys() - a.keys()
    assert sorted(a[k].title for k in gone) == ["BOC Gov Macklem Speaks", "MPC Member Mann Speaks", "Unemployment Claims"]
    assert sorted(b[k].title for k in new) == ["BOC Gov Macklem Speaks", "Cash Rate"]
    changed = sorted(a[k].title for k in a.keys() & b.keys() if (a[k].forecast, a[k].impact) != (b[k].forecast, b[k].impact))
    assert changed == ["BOE Gov Bailey Speaks", "Core Retail Sales m/m"]


# --- what the parser makes of each field -------------------------------------------------------------------------


def test_impacts_currencies_and_text_are_normalized():
    result = ff.parse(fixture("forexfactory", "week_a.json"))
    assert {e.impact for e in result.events} == {"low", "medium", "high", "holiday"}
    assert {e.currency for e in result.events} == {"USD", "GBP", "EUR", "CAD", "AUD", "JPY", "ALL", "CNY", "NZD", "CHF"}
    assert all(e.source == "forexfactory" and e.start_at.tzinfo is timezone.utc for e in result.events)
    cpi = next(e for e in result.events if e.title == "Core CPI m/m")
    assert (cpi.forecast, cpi.previous, cpi.currency, cpi.impact) == ("0.2%", "0.3%", "USD", "high")
    plain = next(e for e in result.events if e.title == "MPC Member Breeden Speaks")
    assert (plain.forecast, plain.previous) == (None, None)  # empty means none


def test_keys_do_not_depend_on_the_form_or_the_run():
    one = ff.make_key("CPI m/m", "USD", datetime(2044, 5, 11, 12, 30, tzinfo=timezone.utc))
    assert one == ff.make_key("CPI m/m", "USD", datetime(2044, 5, 11, 8, 30, tzinfo=timezone(timedelta(hours=-4))))
    assert one != ff.make_key("CPI m/m", "EUR", datetime(2044, 5, 11, 12, 30, tzinfo=timezone.utc))
    assert len(one) == 40


def test_windows_1252_entities_cdata_and_untimed_events():
    result = ff.parse(fixture("forexfactory", "synthetic_cp1252.xml"))
    titles = {e.title: e for e in result.events}
    assert set(titles) == {"Fed’s Beige Book & Outlook", "Riksbank Gov Thedéen Speaks", "OPEC-JMMC Meetings", "G7 Leaders Summit"}
    beige = titles["Fed’s Beige Book & Outlook"]
    assert beige.start_at == datetime(2044, 5, 11, 18, 0, tzinfo=timezone.utc)  # 6:00pm, read as UTC
    # "All Day" and "Tentative" are not times of day, so the event holds its date. An impact the app does not know is kept as such.
    opec, g7 = titles["OPEC-JMMC Meetings"], titles["G7 Leaders Summit"]
    assert (opec.all_day, opec.start_date, opec.end_date, opec.impact, opec.currency) == (True, datetime(2044, 5, 12).date(), datetime(2044, 5, 13).date(), "unknown", "ALL")
    assert (g7.all_day, g7.start_date, g7.start_at) == (True, datetime(2044, 5, 13).date(), None)


def test_a_midnight_and_noon_are_read_correctly():
    xml = b"""<?xml version="1.0" encoding="windows-1252"?><weeklyevents>
      <event><title>Midnight</title><country>USD</country><date>05-11-2044</date><time>12:00am</time><impact>Low</impact></event>
      <event><title>Noon</title><country>USD</country><date>05-11-2044</date><time>12:00pm</time><impact>Low</impact></event>
      <event><title>Quarter past one</title><country>USD</country><date>05-11-2044</date><time>1:15pm</time><impact>Low</impact></event>
    </weeklyevents>"""
    hours = {e.title: (e.start_at.hour, e.start_at.minute) for e in ff.parse(xml).events}
    assert hours == {"Midnight": (0, 0), "Noon": (12, 0), "Quarter past one": (13, 15)}


# --- anything that is not the feed ---------------------------------------------------------------------------------


def test_the_hosts_request_denied_page_is_throttling_not_garbage():
    with pytest.raises(Throttled):
        ff.parse(fixture("forexfactory", "request_denied.html"))


def test_other_html_and_noise_is_bad_content():
    for body in (fixture("forexfactory", "maintenance.html"), b"plain text", b"", b"   "):
        with pytest.raises(BadContent):
            ff.parse(body)


def test_truncated_and_malformed_documents_are_bad_content():
    for body in (fixture("forexfactory", "truncated.xml"), b'[{"title": "cut off", ', b'{"error": "nope"}', b"[1, 2, 3]"):
        with pytest.raises(BadContent):
            ff.parse(body)


def test_xml_that_declares_entities_is_refused():
    bomb = b'<?xml version="1.0"?><!DOCTYPE weeklyevents [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]><weeklyevents>&b;</weeklyevents>'
    with pytest.raises(BadContent, match="DOCTYPE"):
        ff.parse(bomb)


def test_an_xml_document_that_is_not_a_weekly_list_is_bad_content():
    with pytest.raises(BadContent):
        ff.parse(b'<?xml version="1.0"?><rss><channel/></rss>')


def test_the_form_is_sniffed_from_the_bytes_not_the_content_type():
    body = fixture("forexfactory", "week_a.json")
    assert len(ff.parse(b"\xef\xbb\xbf" + body).events) == 108  # a byte order mark and leading blanks are fine
    assert len(ff.parse(b"\n  " + body).events) == 108


# --- bad items inside a good feed -------------------------------------------------------------------------------------


def good(title="Event", when="2044-05-11T08:30:00-04:00", **extra):
    return {"title": title, "country": "USD", "date": when, "impact": "High", "forecast": "", "previous": "", **extra}


def test_malformed_items_are_dropped_and_the_rest_kept():
    items = [good("One"), good("Two"), good("Three"), {"title": "No date", "country": "USD"}, good("Naive", when="2044-05-11T08:30:00")]
    result = ff.parse(json.dumps(items).encode())
    assert [e.title for e in result.events] == ["One", "Two", "Three"]
    assert (result.total, result.dropped) == (5, 2)
    assert any("no date" in problem for problem in result.problems) and any("no UTC offset" in problem for problem in result.problems)


def test_a_feed_that_is_mostly_unusable_is_refused_whole():
    items = [good("Only good one")] + [{"title": "", "date": "x"}] * 3
    with pytest.raises(BadContent, match="3 of 4"):
        ff.parse(json.dumps(items).encode())


def test_duplicate_events_collapse_to_one():
    result = ff.parse(json.dumps([good("Same"), good("Same"), good("Other")]).encode())
    assert [e.title for e in result.events] == ["Same", "Other"]
    assert result.dropped == 1


def test_a_feed_with_no_events_is_not_a_feed():
    with pytest.raises(BadContent, match="no events"):
        ff.parse(b"[]")


def test_unknown_impact_and_long_text_are_handled():
    result = ff.parse(json.dumps([good("T" * 400, impact="Non-Economic", forecast="x" * 80)]).encode())
    event = result.events[0]
    assert event.impact == "unknown"
    assert len(event.title) == 300 and event.title.endswith("…")
    assert len(event.forecast) == 40
