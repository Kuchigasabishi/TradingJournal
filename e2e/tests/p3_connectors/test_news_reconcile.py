"""Phase 3: what a later fetch of the ForexFactory week does to the events already stored.

Week B is week A a day later (fixtures/README.md): one future event removed (Unemployment Claims), one forecast changed
(Core Retail Sales), one impact changed (BOE Gov Bailey), one event moved by 30 minutes (BOC Gov Macklem), one added
(Cash Rate), and one past event removed (MPC Member Mann), which the app must keep: ForexFactory publishes one week at a
time, so history only stays if it is never deleted.
"""
from support.feeds import FIXTURES, ff_week, news_key

NOW = "2044-05-11T12:00:00Z"  # the app's clock when it started; it only moves forward
BAILEY = ("BOE Gov Bailey Speaks", "GBP", "2044-05-12T07:30:00Z")
CORE_RETAIL = ("Core Retail Sales m/m", "USD", "2044-05-12T12:30:00Z")
CLAIMS = ("Unemployment Claims", "USD", "2044-05-12T12:30:00Z")  # removed from the later week
MACKLEM_OLD = ("BOC Gov Macklem Speaks", "CAD", "2044-05-13T04:15:00Z")  # moved: the old time disappears...
MACKLEM_NEW = ("BOC Gov Macklem Speaks", "CAD", "2044-05-13T04:45:00Z")  # ...and the new one appears
CASH_RATE = ("Cash Rate", "AUD", "2044-05-12T04:30:00Z")  # added
MANN = ("MPC Member Mann Speaks", "GBP", "2044-05-09T12:50:00Z")  # in the past, so it stays


def stored_news(feeds):
    return {news_key(event): event for event in feeds.all_events("forexfactory")}


def test_a_later_week_updates_adds_and_removes_future_events_but_keeps_the_past(feeds):
    week_a, week_b = ff_week("week_a"), ff_week("week_b")
    assert week_a.keys() - week_b.keys() == {CLAIMS, MACKLEM_OLD, MANN}  # what the fixtures were built to do
    assert week_b.keys() - week_a.keys() == {MACKLEM_NEW, CASH_RATE}
    before = stored_news(feeds)

    feeds.script(ff={"variant": "b"})
    status = feeds.sync("forexfactory")["forexfactory"]
    after = stored_news(feeds)

    assert (status["status"], status["message"]) == ("ok", None)
    assert after.keys() == week_b.keys() | {MANN}
    assert status["event_count"] == len(after) == len(before)  # two removed, two added, and the past event kept
    assert before.keys() - after.keys() == {CLAIMS, MACKLEM_OLD}  # future events the feed no longer lists
    assert after.keys() - before.keys() == {MACKLEM_NEW, CASH_RATE}
    assert after[MANN] == before[MANN] and after[MANN]["start_at"] < NOW  # history is kept exactly as it was

    # changed events are updated in place: same row, new value
    assert after[BAILEY]["id"] == before[BAILEY]["id"]
    assert (before[BAILEY]["impact"], after[BAILEY]["impact"]) == ("medium", "low")
    assert after[CORE_RETAIL]["id"] == before[CORE_RETAIL]["id"]
    assert (before[CORE_RETAIL]["forecast"], after[CORE_RETAIL]["forecast"]) == ("0.6%", "0.5%")
    assert after[CASH_RATE]["impact"] == "high" and after[CASH_RATE]["forecast"] == "4.35%"

    # and nothing else is touched: not even the time a row was last updated
    untouched = (before.keys() & after.keys()) - {BAILEY, CORE_RETAIL}
    assert len(untouched) == len(before) - 4  # two were removed and two were changed
    for key in untouched:
        assert after[key] == before[key], key

    # the earlier week comes back as it was, and what the later week added goes again
    feeds.script(ff={"variant": "a"})
    feeds.sync("forexfactory")
    again = stored_news(feeds)
    assert again.keys() == before.keys()
    assert {key: again[key]["impact"] for key in (BAILEY,)} == {BAILEY: "medium"}


def test_an_unchanged_feed_is_answered_with_304_and_changes_nothing(feeds):
    feeds.sync("forexfactory")  # makes sure the app holds the validators of the current answer
    before = feeds.all_events("forexfactory")
    status = feeds.sync("forexfactory")["forexfactory"]

    request = feeds.stub.requests("forexfactory")[-1]
    assert request["conditional"] is True and request["status"] == 304
    assert (status["status"], status["http_status"], status["message"]) == ("ok", 304, None)
    assert feeds.all_events("forexfactory") == before


def test_the_fixture_weeks_have_the_shape_this_module_relies_on():
    for name in ("week_a", "week_b"):
        assert (FIXTURES / "forexfactory" / f"{name}.xml").is_file() and (FIXTURES / "forexfactory" / f"{name}.json").is_file()
    assert len(ff_week("week_a")) == 108 and len(ff_week("week_b")) == 107
