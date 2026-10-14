"""Phase 1: list filters, ordering and paging. Each test isolates its rows behind a unique tag."""
from support.journal import unique


def listing(api, group: str, query: str = "") -> dict:
    return api.get(f"/api/trades?tag={group}&{query}").json()


def ids(api, group: str, query: str = "") -> set[int]:
    return {trade["id"] for trade in listing(api, group, query)["items"]}


def test_filters_narrow_the_list(api, journal):
    group = unique("F")
    a = journal.trade(instrument=f"{group}A", tags=[group, "breakout"])
    b = journal.trade(instrument=f"{group}B", side="short", tags=[group], opened_at="2032-03-01T09:00:00Z", closed_at="2032-03-01T10:00:00Z")
    c = journal.open_trade(instrument=f"{group}A", tags=[group], opened_at="2032-03-02T09:00:00Z")
    everything = {a["id"], b["id"], c["id"]}

    assert ids(api, group) == everything
    assert ids(api, group, f"instrument={group.lower()}a") == {a["id"], c["id"]}  # case-insensitive
    assert ids(api, group, "side=short") == {b["id"]}
    assert ids(api, group, "status=open") == {c["id"]}
    assert ids(api, group, "status=closed") == {a["id"], b["id"]}
    assert ids(api, group, "tag=BREAKOUT") == {a["id"]}  # every tag must match, ignoring case
    assert ids(api, group, "tag=nonexistent-tag") == set()
    assert ids(api, group, f"instrument={group}A&status=closed&tag=breakout") == {a["id"]}


def test_date_filters_follow_the_servers_time_zone(api, journal):
    group = unique("D")
    winter = {"opened_at": "2032-01-15T12:00:00Z"}
    before_midnight = journal.trade(tags=[group], closed_at="2032-01-16T04:59:59Z", **winter)  # 23:59:59 on the 15th in New York
    after_midnight = journal.trade(tags=[group], closed_at="2032-01-16T05:00:00Z", **winter)  # 00:00:00 on the 16th
    still_open = journal.open_trade(tags=[group], opened_at="2032-01-16T20:00:00Z")  # an open trade counts on its opening day

    assert ids(api, group, "from=2032-01-15&to=2032-01-15") == {before_midnight["id"]}
    assert ids(api, group, "from=2032-01-16&to=2032-01-16") == {after_midnight["id"], still_open["id"]}
    assert ids(api, group, "from=2032-01-15&to=2032-01-16") == {before_midnight["id"], after_midnight["id"], still_open["id"]}
    assert ids(api, group, "from=2032-01-17") == set()
    assert api.get(f"/api/trades?tag={group}&from=2032-02-01&to=2032-01-01").status == 422


def test_paging_slices_a_stable_order_and_reports_the_total(api, journal):
    group = unique("P")
    for day in range(1, 6):
        journal.trade(tags=[group], opened_at=f"2032-04-0{day}T09:00:00Z", closed_at=f"2032-04-0{day}T10:00:00Z")
    everything = listing(api, group)
    assert everything["total"] == 5 and [t["closed_at"][:10] for t in everything["items"]] == [f"2032-04-0{d}" for d in (5, 4, 3, 2, 1)]

    middle = listing(api, group, "limit=2&offset=2")
    assert (middle["total"], middle["limit"], middle["offset"]) == (5, 2, 2)
    assert [t["id"] for t in middle["items"]] == [t["id"] for t in everything["items"][2:4]]
    assert listing(api, group, "limit=2&offset=4")["items"] == everything["items"][4:]
    oldest_first = listing(api, group, "order=asc")["items"]
    assert [t["id"] for t in oldest_first] == [t["id"] for t in reversed(everything["items"])]


def test_paging_limits_are_validated(api):
    assert api.get("/api/trades?limit=0").status == 422
    assert api.get("/api/trades?limit=501").status == 422
    assert api.get("/api/trades?offset=-1").status == 422
    assert api.get("/api/trades?sort=colour").status == 422
