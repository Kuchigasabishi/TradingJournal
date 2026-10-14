import hashlib
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.connectors import gcal
from app.connectors.base import BadContent
from feed_helpers import NOW, fixture

NEW_YORK = ZoneInfo("America/New_York")


def parse(body: bytes, tz=NEW_YORK, now=NOW):
    return gcal.parse(body, now=now, default_tz=tz)


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def week():
    """Calendar A, parsed once, indexed by title for the events that happen once. The weekly series has many instances."""
    result = parse(fixture("gcal", "personal_a.ics"))
    return result, {e.title: e for e in result.events if e.title != "Weekly review"}


def reviews(result):
    return sorted(e.start_at for e in result.events if e.title == "Weekly review")


# --- recurrence: a weekly series with an exception, a moved instance and a cancelled one ------------------------------


def test_the_weekly_series_skips_the_exception_and_the_cancelled_instance(week):
    result, _ = week
    starts = reviews(result)
    # Mondays 10:00 New York (14:00 UTC): 2 May and 9 May, not 16 May (moved), 23 May (EXDATE) or 30 May (cancelled).
    may = [s.day for s in starts if (s.year, s.month) == (2044, 5)]
    assert may == [2, 9]
    # The series is "10:00 in New York", so it follows daylight saving: 14:00 UTC in summer, 15:00 UTC in winter.
    assert all(s.astimezone(NEW_YORK).hour == 10 and s.astimezone(NEW_YORK).minute == 0 for s in starts)
    assert utc(2044, 5, 2, 14) in starts and utc(2044, 12, 5, 15) in starts
    assert utc(2044, 6, 6, 14) in starts and utc(2044, 5, 30, 14) not in starts


def test_the_window_is_60_days_back_and_400_days_ahead(week):
    result, _ = week
    starts = reviews(result)
    assert min(starts) >= NOW - timedelta(days=60)
    assert starts[0] == utc(2044, 4, 4, 14)  # the series itself starts on 4 April, inside the window
    assert max(starts) <= NOW + timedelta(days=400)
    titles = {e.title for e in result.events}
    assert not any("window" in title for title in titles)  # one event before it and one after it are not mirrored


def test_a_moved_instance_is_at_its_new_time_and_keeps_the_identity_of_the_old_slot(week):
    result, events = week
    moved = events["Weekly review (moved)"]
    assert moved.start_at == utc(2044, 5, 17, 19, 0) and moved.end_at == utc(2044, 5, 17, 19, 30)  # Tuesday 15:00 in New York
    original_slot = hashlib.sha1(b"weekly-review@fixture.example|" + utc(2044, 5, 16, 14).isoformat().encode()).hexdigest()
    assert moved.key == original_slot, "moving an instance must update its row, not replace it"


def test_instances_of_one_series_have_distinct_keys(week):
    result, _ = week
    keys = [e.key for e in result.events]
    assert len(keys) == len(set(keys))


# --- times and zones ----------------------------------------------------------------------------------------------------


def test_utc_london_and_floating_times_all_become_utc(week):
    _, events = week
    assert events["Call with the prop firm"].start_at == utc(2044, 5, 10, 14)  # written in UTC
    london = events["London open briefing"]
    assert (london.start_at, london.end_at) == (utc(2044, 5, 11, 8), utc(2044, 5, 11, 9))  # 09:00 BST
    # No zone on the time. Google's X-WR-TIMEZONE says New York: 18:00 there is 22:00 UTC.
    assert events["Floating dinner"].start_at == utc(2044, 5, 12, 22)


def test_a_floating_time_with_no_calendar_zone_is_read_in_the_owners_zone():
    ics = b"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//t//EN\nBEGIN:VEVENT\nUID:a@x\nDTSTART:20440512T180000\nDTEND:20440512T190000\nSUMMARY:Floating\nEND:VEVENT\nEND:VCALENDAR\n"
    in_new_york = parse(ics, tz=ZoneInfo("America/New_York")).events[0]
    in_tokyo = parse(ics, tz=ZoneInfo("Asia/Tokyo")).events[0]
    assert in_new_york.start_at == utc(2044, 5, 12, 22)
    assert in_tokyo.start_at == utc(2044, 5, 12, 9)


def test_all_day_events_are_dates_with_an_exclusive_end(week):
    _, events = week
    day_off, course = events["Bank day off"], events["Trading course"]
    assert (day_off.all_day, day_off.start_date, day_off.end_date, day_off.start_at) == (True, date(2044, 5, 12), date(2044, 5, 13), None)
    assert (course.start_date, course.end_date) == (date(2044, 5, 18), date(2044, 5, 21))  # three days: 18th, 19th and 20th


def test_an_event_that_crosses_midnight_has_both_ends(week):
    _, events = week
    asia = events["Asia session review"]
    assert (asia.start_at, asia.end_at) == (utc(2044, 5, 13, 2), utc(2044, 5, 13, 6))  # 22:00 to 02:00 New York


def test_a_duration_gives_the_end_and_a_missing_end_gives_an_instant():
    ics = (
        b"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//t//EN\n"
        b"BEGIN:VEVENT\nUID:d@x\nDTSTART:20440512T100000Z\nDURATION:PT90M\nSUMMARY:Has duration\nEND:VEVENT\n"
        b"BEGIN:VEVENT\nUID:i@x\nDTSTART:20440512T120000Z\nSUMMARY:No end\nEND:VEVENT\n"
        b"BEGIN:VEVENT\nUID:a@x\nDTSTART;VALUE=DATE:20440513\nSUMMARY:All day, no end\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    events = {e.title: e for e in parse(ics).events}
    assert events["Has duration"].end_at == utc(2044, 5, 12, 11, 30)
    assert events["No end"].end_at is None
    assert (events["All day, no end"].start_date, events["All day, no end"].end_date) == (date(2044, 5, 13), date(2044, 5, 14))


# --- text --------------------------------------------------------------------------------------------------------------------


def test_escapes_folding_unicode_and_html_are_handled(week):
    _, events = week
    assert events["Café – résumé review"].start_at == utc(2044, 5, 10, 20)
    london = events["London open briefing"]
    # The long description was folded over two lines in the file, and escaped commas are plain commas.
    assert london.description.startswith("Walk through the overnight Asian range and the London open plan, including the levels")
    assert "\n" not in london.description and london.location == "Zoom, London desk"
    broker = events["Broker call"]
    assert broker.description == "Agenda:\n1. Margin rules\n2. Platform update and fees\n\nBring questions."  # tags and entities are gone
    review = next(e for e in week[0].events if e.title == "Weekly review")
    assert review.description == "Review the week, check the journal.\nBring the charts."


def test_plain_text_leaves_plain_text_alone_and_caps_length():
    assert gcal.plain_text("Line one\r\nLine two", 100) == "Line one\nLine two"
    assert gcal.plain_text("x" * 50, 10) == "xxxxxxxxx…"
    assert gcal.plain_text("   ", 10) is None and gcal.plain_text(None, 10) is None


# --- bad calendars ---------------------------------------------------------------------------------------------------------


def test_a_web_page_is_not_a_calendar():
    with pytest.raises(BadContent, match="not a calendar"):
        parse(fixture("gcal", "sign_in_page.html"))
    with pytest.raises(BadContent):
        parse(b"")


def test_a_calendar_that_was_cut_off_is_refused_so_the_mirror_cannot_delete_the_rest():
    # icalendar reads a file that stops mid-event leniently. Without this check a half download would look like a
    # calendar with fewer events, and mirroring it would delete everything after the cut.
    with pytest.raises(BadContent, match="cut off"):
        parse(fixture("gcal", "malformed.ics"))
    whole = fixture("gcal", "personal_a.ics")
    with pytest.raises(BadContent, match="cut off"):
        parse(whole[: len(whole) // 2])


def test_a_calendar_whose_events_all_lack_a_start_is_refused():
    with pytest.raises(BadContent, match="3 of 3"):
        parse(fixture("gcal", "no_start_dates.ics"))


def test_one_broken_series_costs_one_series_not_the_calendar():
    ics = (
        b"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//t//EN\n"
        b"BEGIN:VEVENT\nUID:bad@x\nDTSTART:20440510T100000Z\nRRULE:FREQ=BOGUS\nSUMMARY:Bad rule\nEND:VEVENT\n"
        b"BEGIN:VEVENT\nUID:g1@x\nDTSTART:20440511T100000Z\nSUMMARY:Good one\nEND:VEVENT\n"
        b"BEGIN:VEVENT\nUID:g2@x\nDTSTART:20440512T100000Z\nSUMMARY:Good two\nEND:VEVENT\n"
        b"BEGIN:VEVENT\nUID:ns@x\nSUMMARY:No start\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    result = parse(ics)
    assert sorted(e.title for e in result.events) == ["Good one", "Good two"]
    assert result.dropped == 2 and result.total == 4
    assert any("no start" in problem for problem in result.problems)


def test_an_empty_calendar_is_a_calendar():
    result = parse(b"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//t//EN\nEND:VCALENDAR\n")
    assert (result.events, result.total, result.dropped) == ([], 0, 0)


def test_the_crlf_line_endings_google_uses_read_the_same():
    crlf = fixture("gcal", "personal_a.ics").replace(b"\n", b"\r\n")
    assert {e.key for e in parse(crlf).events} == {e.key for e in parse(fixture("gcal", "personal_a.ics")).events}


def test_calendar_b_differs_from_a_as_the_readme_says():
    a = {e.key: e for e in parse(fixture("gcal", "personal_a.ics")).events}
    b = {e.key: e for e in parse(fixture("gcal", "personal_b.ics")).events}
    assert sorted(a[k].title for k in a.keys() - b.keys()) == ["Broker call"]
    assert sorted(b[k].title for k in b.keys() - a.keys()) == ["FOMC watch party"]
    changed = sorted((a[k].title, b[k].title) for k in a.keys() & b.keys() if (a[k].title, a[k].start_at) != (b[k].title, b[k].start_at))
    assert changed == [("Call with the prop firm", "Call with the prop firm"), ("Trading course", "Trading course (advanced)")]
