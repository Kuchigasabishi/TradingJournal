"""Phase 3: GET /api/events, the one read the calendar screens use.

Expected results are worked out from the fixture oracles (week A and calendar A), not from the API.
"""
import pytest

from support.feeds import calendar_events, ff_week

NEWS = list(ff_week("week_a").values())
CALENDAR = [{**event, "source": "gcal"} for event in calendar_events("a").values()]
EVERYTHING = NEWS + CALENDAR


def ident(event: dict) -> tuple:
    return (event["source"], event["title"], event["start_at"] or event["start_day"], event.get("currency"))


def covering(events: list[dict], first: str | None, last: str | None) -> list[dict]:
    return [e for e in events if (first is None or e["end_day"] >= first) and (last is None or e["start_day"] <= last)]


def fetch_all(api, query: str = "") -> list[dict]:
    response = api.get(f"/api/events?limit=500{('&' + query) if query else ''}")
    assert response.status == 200, response.text()
    page = response.json()
    assert page["total"] == len(page["items"]), "more than one page"
    return page["items"]


def test_a_day_lists_what_covers_it_all_day_events_first(api):
    items = fetch_all(api, "from=2044-05-12&to=2044-05-12")
    assert {ident(e) for e in items} == {ident(e) for e in covering(EVERYTHING, "2044-05-12", "2044-05-12")}
    assert items[0]["title"] == "Bank day off" and items[0]["all_day"]  # all-day events lead the day
    timed = [e["start_at"] for e in items if not e["all_day"]]
    assert timed == sorted(timed)
    # a multi-day event is listed once, on whichever day you ask for
    assert [e["title"] for e in items if e["title"] == "Asia session review"] == ["Asia session review"]


def test_an_event_that_crosses_midnight_belongs_to_both_days(api):
    for day in ("2044-05-12", "2044-05-13"):
        items = fetch_all(api, f"from={day}&to={day}&source=gcal")
        asia = [e for e in items if e["title"] == "Asia session review"]
        assert len(asia) == 1 and (asia[0]["start_day"], asia[0]["end_day"]) == ("2044-05-12", "2044-05-13"), day
    items = fetch_all(api, "from=2044-05-19&to=2044-05-19&source=gcal")
    assert [(e["title"], e["start_day"], e["end_day"]) for e in items] == [("Trading course", "2044-05-18", "2044-05-20")]


def test_a_range_is_inclusive_at_both_ends_and_may_be_open(api):
    items = fetch_all(api, "from=2044-05-09&to=2044-05-10")
    assert {ident(e) for e in items} == {ident(e) for e in covering(EVERYTHING, "2044-05-09", "2044-05-10")}
    april = fetch_all(api, "to=2044-04-30")
    assert [e["start_day"] for e in april] == ["2044-04-04", "2044-04-11", "2044-04-18", "2044-04-25"]  # only the weekly review, in order
    later = fetch_all(api, "from=2044-06-30")
    assert "Quarter-end planning" in {e["title"] for e in later} and all(e["end_day"] >= "2044-06-30" for e in later)


def test_events_can_be_filtered_by_source(api):
    assert len(fetch_all(api, "source=forexfactory")) == len(NEWS)
    assert len(fetch_all(api, "source=gcal")) == len(CALENDAR)
    assert {e["source"] for e in fetch_all(api, "source=gcal")} == {"gcal"}


def test_news_can_be_filtered_by_impact_and_several_levels_at_once(api):
    high = fetch_all(api, "impact=high")
    assert len(high) == 13 and {e["impact"] for e in high} == {"high"}
    both = fetch_all(api, "impact=high&impact=medium")
    assert len(both) == 23 and {e["source"] for e in both} == {"forexfactory"}  # calendar events have no impact, so no level matches them
    assert len(fetch_all(api, "impact=holiday")) == 3


def test_a_currency_filter_includes_the_events_for_every_currency(api):
    usd = fetch_all(api, "currency=usd")  # case does not matter
    assert len(usd) == 34 + 6 and {e["currency"] for e in usd} == {"USD", "ALL"}
    assert {e["currency"] for e in fetch_all(api, "currency=ALL")} == {"ALL"}
    assert len(fetch_all(api, "currency=NZD")) == 3 + 6


def test_filters_combine(api):
    items = fetch_all(api, "from=2044-05-12&to=2044-05-12&impact=high&currency=USD")
    by_hand = {"Core PPI m/m", "Core Retail Sales m/m", "PPI m/m", "Retail Sales m/m", "Fed Chairman Warsh Speaks"}  # 23:30 in New York is still the 12th
    assert {e["title"] for e in items} == by_hand
    oracle = [e for e in covering(NEWS, "2044-05-12", "2044-05-12") if e["impact"] == "high" and e["currency"] in ("USD", "ALL")]
    assert {ident(e) for e in items} == {ident(e) for e in oracle}


def test_pages_add_up_to_the_whole_list(api):
    whole = fetch_all(api)
    assert len(whole) == len(EVERYTHING)
    pages, offset = [], 0
    while True:
        page = api.get(f"/api/events?limit=50&offset={offset}").json()
        assert (page["limit"], page["offset"], page["total"]) == (50, offset, len(EVERYTHING))
        pages += page["items"]
        offset += 50
        if offset >= page["total"]:
            break
    assert [e["id"] for e in pages] == [e["id"] for e in whole]
    order = [(e["start_day"], not e["all_day"], e["start_at"] or "") for e in whole]
    assert order == sorted(order)  # by day, then all-day first, then by time


@pytest.mark.parametrize(
    "query",
    ["from=2044-05-12&to=2044-05-11", "from=not-a-date", "impact=urgent", "source=bogus", "limit=0", "limit=501", "offset=-1"],
)
def test_bad_queries_are_refused(api, query):
    assert api.get(f"/api/events?{query}").status == 422
