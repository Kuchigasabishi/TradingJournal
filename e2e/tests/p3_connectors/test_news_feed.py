"""Phase 3: the ForexFactory week, read from the XML the stub serves, arrives as the fixture says.

The expected events come from fixtures/forexfactory/week_a.json (explicit New York offsets), read here with plain json,
while the app is served the XML form (UTC date and time, no zone): two independent routes to the same instants.
"""
from support.feeds import ff_week, news_key, news_view

# Hand-checked against the file: (title, currency, UTC instant, New York day)
SAMPLES = [
    ("CPI m/m", "USD", "2044-05-11T12:30:00Z", "2044-05-11"),  # 08:30 in New York
    ("Employment Change", "AUD", "2044-05-12T00:30:00Z", "2044-05-11"),  # 20:30 on the 11th in New York, while the UTC date is the 12th
    ("Fed Chairman Warsh Speaks", "USD", "2044-05-13T03:30:00Z", "2044-05-12"),  # 23:30 on the 12th
    ("Bank Holiday", "JPY", "2044-05-08T23:00:00Z", "2044-05-08"),  # 19:00 on the Sunday that opens the week
]


def stored_news(feeds):
    return {news_key(event): event for event in feeds.all_events("forexfactory")}


def test_the_whole_week_is_stored_as_the_feed_holds_it(feeds):
    stored = stored_news(feeds)
    expected = ff_week("week_a")
    assert stored.keys() == expected.keys()
    for key, event in expected.items():
        assert news_view(stored[key]) == event, key
    for event in stored.values():
        assert event["description"] is None and event["location"] is None
        assert event["url"].startswith("https://www.forexfactory.com/calendar/"), event["title"]  # the XML carries a link for every event


def test_times_are_utc_instants_and_days_are_new_york_days(feeds):
    stored = stored_news(feeds)
    for title, currency, start_at, day in SAMPLES:
        event = stored[(title, currency, start_at)]
        assert (event["start_at"], event["start_day"], event["end_day"]) == (start_at, day, day), title
        assert event["all_day"] is False and event["end_at"] is None


def test_the_impact_levels_and_figures_are_kept(feeds):
    stored = stored_news(feeds)
    cpi = stored[("CPI m/m", "USD", "2044-05-11T12:30:00Z")]
    assert (cpi["impact"], cpi["forecast"], cpi["previous"]) == ("high", "0.6%", "0.4%")
    assert stored[("BOE Gov Bailey Speaks", "GBP", "2044-05-12T07:30:00Z")]["impact"] == "medium"
    assert stored[("MPC Member Breeden Speaks", "GBP", "2044-05-09T09:30:00Z")]["impact"] == "low"
    holiday = stored[("Bank Holiday", "USD", "2044-05-09T11:00:00Z")]
    assert (holiday["impact"], holiday["forecast"], holiday["previous"]) == ("holiday", None, None)  # empty in the feed means none
    counts = {}
    for event in stored.values():
        counts[event["impact"]] = counts.get(event["impact"], 0) + 1
    assert counts == {"low": 82, "high": 13, "medium": 10, "holiday": 3}


def test_an_event_for_every_currency_is_kept_as_ALL(feeds):
    stored = stored_news(feeds)
    imf = stored[("IMF Meetings", "ALL", "2044-05-09T14:15:00Z")]
    assert imf["currency"] == "ALL"
    assert sum(1 for event in stored.values() if event["currency"] == "ALL") == 6


def test_the_json_form_of_the_feed_gives_the_same_events(feeds):
    xml = stored_news(feeds)
    feeds.script(ff={"format": "json"})
    feeds.sync("forexfactory")
    request = feeds.stub.requests("forexfactory")[-1]
    assert request["format"] == "json"
    json_form = stored_news(feeds)

    assert json_form.keys() == xml.keys()
    for key, event in xml.items():
        # the JSON form has no link, so that is the one thing that differs; the same event is the same row
        assert {**json_form[key], "url": None, "updated_at": None} == {**event, "url": None, "updated_at": None}, key
        assert json_form[key]["id"] == event["id"]
    assert all(event["url"] is None for event in json_form.values())
