"""Phase 1: month summaries bucket closed trades by their closing day in the server's time zone (New York).

Each test owns its own month in 2031, which no other test writes to, so results are exact.
"""
from support.journal import unique

OPENED = "2031-01-01T00:00:00Z"


def month(api, year: int, number: int) -> dict:
    response = api.get(f"/api/calendar/month?year={year}&month={number}")
    assert response.status == 200
    return response.json()


def days(summary: dict) -> list[tuple[str, str, int]]:
    return [(d["date"], d["pnl"], d["trade_count"]) for d in summary["days"]]


def test_winter_buckets_follow_utc_minus_5_and_months_split_at_local_midnight(api, journal):
    for pnl, closed_at in [
        ("0.1", "2031-01-16T04:59:59Z"),  # 23:59:59 on the 15th in New York
        ("0.2", "2031-01-16T05:00:00Z"),  # 00:00:00 on the 16th
        ("0.3", "2031-01-16T12:00:00Z"),
        ("-1", "2031-02-01T04:59:59Z"),  # still January 31st locally
        ("9", "2031-02-01T05:00:00Z"),  # February
    ]:
        journal.trade(pnl=pnl, opened_at=OPENED, closed_at=closed_at)
    journal.open_trade(opened_at="2031-01-10T00:00:00Z")  # open trades never count

    january = month(api, 2031, 1)
    assert january["timezone"] == "America/New_York" and (january["year"], january["month"]) == (2031, 1)
    assert days(january) == [("2031-01-15", "0.1", 1), ("2031-01-16", "0.5", 2), ("2031-01-31", "-1", 1)]
    assert january["totals"] == {"pnl": "-0.4", "trade_count": 4, "wins": 3, "losses": 1, "breakeven": 0}
    assert days(month(api, 2031, 2)) == [("2031-02-01", "9", 1)]


def test_summer_buckets_follow_utc_minus_4(api, journal):
    for pnl, closed_at in [("1", "2031-07-16T03:59:59Z"), ("2", "2031-07-16T04:00:00Z")]:
        journal.trade(pnl=pnl, opened_at="2031-07-01T00:00:00Z", closed_at=closed_at)
    # A fixed UTC-5 offset would put 04:00Z at 23:00 on the 15th: the offset has to follow daylight saving.
    assert days(month(api, 2031, 7)) == [("2031-07-15", "1", 1), ("2031-07-16", "2", 1)]


def test_the_spring_forward_day_holds_23_hours(api, journal):
    for pnl, closed_at in [
        ("1", "2031-03-09T04:59:59Z"),
        ("2", "2031-03-09T05:00:00Z"),
        ("4", "2031-03-10T03:59:59Z"),
        ("8", "2031-03-10T04:00:00Z"),
    ]:
        journal.trade(pnl=pnl, opened_at="2031-03-01T00:00:00Z", closed_at=closed_at)
    assert days(month(api, 2031, 3)) == [("2031-03-08", "1", 1), ("2031-03-09", "6", 2), ("2031-03-10", "8", 1)]


def test_day_totals_are_exact_decimal_sums(api, journal):
    for _ in range(10):
        journal.trade(pnl="0.1", opened_at="2031-05-01T00:00:00Z", closed_at="2031-05-10T15:00:00Z")
    journal.trade(pnl="0.2", opened_at="2031-05-01T00:00:00Z", closed_at="2031-05-11T15:00:00Z")
    journal.trade(pnl="0.1", opened_at="2031-05-01T00:00:00Z", closed_at="2031-05-11T16:00:00Z")
    summary = month(api, 2031, 5)
    # Ten times 0.1 is 0.9999999999999999 in floating point; here it is exactly 1.
    assert days(summary) == [("2031-05-10", "1", 10), ("2031-05-11", "0.3", 2)]
    assert summary["totals"]["pnl"] == "1.3"


def test_wins_losses_and_breakeven_are_counted_by_sign(api, journal):
    for pnl in ("5", "-3", "0", "0.00000001", "-0.00000001"):
        journal.trade(pnl=pnl, opened_at="2031-06-01T00:00:00Z", closed_at="2031-06-10T15:00:00Z")
    (day,) = month(api, 2031, 6)["days"]
    assert (day["trade_count"], day["wins"], day["losses"], day["breakeven"], day["pnl"]) == (5, 2, 2, 1, "2")


def test_a_month_without_trades_is_empty(api):
    summary = month(api, 2031, 9)
    assert summary["days"] == []
    assert summary["totals"] == {"pnl": "0", "trade_count": 0, "wins": 0, "losses": 0, "breakeven": 0}


def test_the_month_summary_validates_its_parameters(api):
    for query in ("year=2031&month=13", "year=2031&month=0", "year=1969&month=1", "month=1", "year=2031"):
        assert api.get(f"/api/calendar/month?{query}").status == 422, query


def test_a_trade_changes_the_summary_when_it_is_edited_or_deleted(api, journal):
    group = unique("C")
    trade = journal.trade(pnl="10", tags=[group], opened_at="2031-08-01T00:00:00Z", closed_at="2031-08-10T15:00:00Z")
    assert days(month(api, 2031, 8)) == [("2031-08-10", "10", 1)]
    api.patch(f"/api/trades/{trade['id']}", data={"pnl": "-4.5"})
    assert days(month(api, 2031, 8)) == [("2031-08-10", "-4.5", 1)]
    api.patch(f"/api/trades/{trade['id']}", data={"exit_price": None, "closed_at": None, "pnl": None})  # reopened
    assert month(api, 2031, 8)["days"] == []
    api.patch(f"/api/trades/{trade['id']}", data={"exit_price": "1.2", "closed_at": "2031-08-11T15:00:00Z", "pnl": "7"})
    assert days(month(api, 2031, 8)) == [("2031-08-11", "7", 1)]
    api.delete(f"/api/trades/{trade['id']}")
    journal.forget_trade(trade["id"])
    assert month(api, 2031, 8)["days"] == []
