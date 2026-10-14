"""Phase 3: the owner's Google Calendar, read through its secret iCal address, is mirrored as the file says.

fixtures/gcal/personal_a.ics is a Google-style calendar with every hard case; tests/support/feeds.py writes out by hand
what it holds, so the app is checked against the file and not against its own parser.
"""
from support.feeds import calendar_events, calendar_key, calendar_view


def stored_calendar(feeds):
    return {calendar_key(event): event for event in feeds.all_events("gcal")}


def test_the_calendar_is_mirrored_with_all_its_hard_cases(feeds):
    stored = stored_calendar(feeds)
    expected = calendar_events("a")
    assert stored.keys() == expected.keys()
    for key, event in expected.items():
        assert calendar_view(stored[key]) == event, key
    for event in stored.values():
        assert (event["currency"], event["impact"], event["forecast"], event["previous"]) == (None, None, None, None)  # those belong to news


def test_a_weekly_series_is_expanded_with_its_exceptions(feeds):
    stored = stored_calendar(feeds)
    reviews = sorted(start for title, start in stored if title == "Weekly review")
    assert len(reviews) == 60
    assert (reviews[0], reviews[-1]) == ("2044-04-04T14:00:00Z", "2045-06-12T14:00:00Z")  # the window runs 60 days back and 400 ahead
    assert "2044-05-09T14:00:00Z" in reviews  # 10:00 in New York summer time
    assert "2044-11-07T15:00:00Z" in reviews  # still 10:00 there, after the clocks went back
    for skipped in ("2044-05-16", "2044-05-23", "2044-05-30"):
        assert not any(start.startswith(skipped) for start in reviews), skipped  # moved, excluded and cancelled
    moved = stored[("Weekly review (moved)", "2044-05-17T19:00:00Z")]
    assert (moved["start_day"], moved["description"]) == ("2044-05-17", None)  # the moved instance does not inherit the description


def test_the_events_outside_the_sync_window_are_not_mirrored(feeds):
    titles = {title for title, _ in stored_calendar(feeds)}
    assert "Before the window (more than 60 days back)" not in titles  # 2044-01-10, more than 60 days before the app's clock
    assert "After the window (more than 400 days ahead)" not in titles  # 2046-01-10
    assert "Quarter-end planning" in titles  # an event 50 days ahead is inside it


def test_zones_are_resolved_to_utc_instants(feeds):
    stored = stored_calendar(feeds)
    # written in UTC, in London summer time, in New York time, and with no zone at all (read in the calendar's own zone)
    assert stored[("Call with the prop firm", "2044-05-10T14:00:00Z")]["end_at"] == "2044-05-10T15:00:00Z"
    london = stored[("London open briefing", "2044-05-11T08:00:00Z")]
    assert london["end_at"] == "2044-05-11T09:00:00Z" and london["start_day"] == "2044-05-11"
    assert stored[("Floating dinner", "2044-05-12T22:00:00Z")]["end_at"] == "2044-05-12T23:00:00Z"


def test_all_day_and_multi_day_events_cover_their_days(feeds):
    stored = stored_calendar(feeds)
    day_off = stored[("Bank day off", "2044-05-12")]
    assert (day_off["all_day"], day_off["start_at"], day_off["end_at"], day_off["start_day"], day_off["end_day"]) == (True, None, None, "2044-05-12", "2044-05-12")
    course = stored[("Trading course", "2044-05-18")]
    assert (course["start_day"], course["end_day"]) == ("2044-05-18", "2044-05-20")  # the file ends it on the 21st, exclusive
    asia = stored[("Asia session review", "2044-05-13T02:00:00Z")]
    assert (asia["start_day"], asia["end_day"]) == ("2044-05-12", "2044-05-13")  # 22:00 to 02:00 in New York: two days


def test_descriptions_become_plain_text_and_locations_are_kept(feeds):
    stored = stored_calendar(feeds)
    review = stored[("Weekly review", "2044-05-09T14:00:00Z")]
    assert review["description"] == "Review the week, check the journal.\nBring the charts."  # escaped commas and newlines in the file
    broker = stored[("Broker call", "2044-05-13T15:00:00Z")]
    assert broker["description"] == "Agenda:\n1. Margin rules\n2. Platform update and fees\n\nBring questions."  # Google's HTML, as text
    london = stored[("London open briefing", "2044-05-11T08:00:00Z")]
    assert london["location"] == "Zoom, London desk"
    assert "plan, including the levels from last week, the news calendar" in london["description"]  # a folded line, whole again
    assert any(title.startswith("Café – résumé") for title, _ in stored)  # UTF-8 survives the trip


def test_a_changed_calendar_is_mirrored_exactly(feeds):
    before = stored_calendar(feeds)
    feeds.script(gcal={"variant": "b"})
    status = feeds.sync("gcal")["gcal"]
    after = stored_calendar(feeds)

    expected = calendar_events("b")
    assert (status["status"], status["message"]) == ("ok", None)
    assert after.keys() == expected.keys()
    for key, event in expected.items():
        assert calendar_view(after[key]) == event, key
    assert status["event_count"] == len(expected)

    deleted = ("Broker call", "2044-05-13T15:00:00Z")
    assert deleted in before and deleted not in after  # deleted in Google, so gone here
    assert ("FOMC watch party", "2044-05-12T18:00:00Z") in after  # added in Google
    # an event that was moved or renamed in Google is the same row here: the calendar's own id is what identifies it
    moved = (before[("Call with the prop firm", "2044-05-10T14:00:00Z")], after[("Call with the prop firm", "2044-05-10T15:00:00Z")])
    renamed = (before[("Trading course", "2044-05-18")], after[("Trading course (advanced)", "2044-05-18")])
    for old, new in (moved, renamed):
        assert new["id"] == old["id"]
    # the rest is left exactly as it was
    untouched = {key for key in before.keys() & after.keys()}
    assert len(untouched) == len(before) - 3  # the broker call, the moved call and the renamed course are not the same keys
    for key in untouched:
        assert after[key] == before[key], key


def test_a_calendar_with_no_events_is_a_valid_calendar(feeds):
    feeds.script(gcal={"mode": "empty"})
    status = feeds.sync("gcal")["gcal"]
    assert (status["status"], status["message"], status["event_count"]) == ("ok", None, 0)  # emptied in Google, so emptied here
    assert feeds.all_events("gcal") == []
