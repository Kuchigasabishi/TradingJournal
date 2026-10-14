from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.models import Note, Tag, Trade, trade_tags
from app.db.repositories import NoteRepository, TagRepository, TradeCriteria, TradeRepository
from helpers import utc


def make_trade(**overrides) -> Trade:
    values = dict(
        instrument="EURUSD",
        side="long",
        lot_size=Decimal("0.1"),
        entry_price=Decimal("1.1"),
        opened_at=utc(2030, 1, 2, 9),
        exit_price=Decimal("1.2"),
        closed_at=utc(2030, 1, 2, 13),
        pnl=Decimal("10"),
    )
    values.update(overrides)
    return Trade(**values)


def open_trade(**overrides) -> Trade:
    return make_trade(**{"exit_price": None, "closed_at": None, "pnl": None, **overrides})


def test_a_trade_round_trips_through_the_database_exactly(session):
    repo = TradeRepository(session)
    trade = repo.add(make_trade(entry_price=Decimal("1.12345678"), pnl=Decimal("-0.00000001"), notes="n"))
    session.commit()
    session.expunge_all()
    loaded = repo.get(trade.id)
    assert loaded is not trade
    assert (loaded.entry_price, loaded.pnl, loaded.lot_size) == (Decimal("1.12345678"), Decimal("-0.00000001"), Decimal("0.1"))
    assert loaded.opened_at == utc(2030, 1, 2, 9) and loaded.opened_at.utcoffset().total_seconds() == 0
    assert loaded.created_at.tzinfo is not None


def test_updated_at_moves_when_something_changes(session):
    repo = TradeRepository(session)
    trade = repo.add(make_trade(created_at=utc(2020, 1, 1), updated_at=utc(2020, 1, 1)))
    session.commit()
    trade.notes = "edited"
    session.commit()
    assert trade.created_at == utc(2020, 1, 1)
    assert trade.updated_at > utc(2020, 1, 1)


@pytest.fixture
def dataset(session):
    repo = TradeRepository(session)
    a = repo.add(make_trade(instrument="EURUSD", closed_at=utc(2030, 1, 2, 13), opened_at=utc(2030, 1, 2, 9), pnl=Decimal("10")))
    b = repo.add(make_trade(instrument="GBPUSD", side="short", opened_at=utc(2030, 1, 3, 9), closed_at=utc(2030, 1, 3, 13), pnl=Decimal("-5")))
    c = repo.add(open_trade(instrument="EURUSD", opened_at=utc(2030, 1, 4, 9)))
    d = repo.add(make_trade(instrument="USDJPY", side="short", opened_at=utc(2030, 1, 5, 9), closed_at=utc(2030, 1, 5, 13), pnl=Decimal("0")))
    repo.set_tags(a, ["breakout", "london"])
    repo.set_tags(b, ["Breakout"])
    session.commit()
    return repo, {"a": a, "b": b, "c": c, "d": d}


def ids(rows, trades, *names):
    return [row.id for row in rows] == [trades[name].id for name in names]


def test_default_order_is_newest_journal_day_first(dataset):
    repo, t = dataset
    rows, total = repo.list(TradeCriteria())
    assert total == 4 and ids(rows, t, "d", "c", "b", "a")  # the open trade sorts by its opening time


@pytest.mark.parametrize(
    ("criteria", "expected"),
    [
        (dict(instrument="EURUSD"), ("c", "a")),
        (dict(side="short"), ("d", "b")),
        (dict(status="open"), ("c",)),
        (dict(status="closed"), ("d", "b", "a")),
        (dict(tags=("breakout",)), ("b", "a")),
        (dict(tags=("BREAKOUT", "London")), ("a",)),  # all tags must match, case-insensitively
        (dict(tags=("nope",)), ()),
        (dict(start=utc(2030, 1, 3), end=utc(2030, 1, 5)), ("c", "b")),  # end is exclusive
    ],
)
def test_filters(dataset, criteria, expected):
    repo, t = dataset
    rows, total = repo.list(TradeCriteria(**criteria))
    assert total == len(expected) and ids(rows, t, *expected)


def test_sorting_by_pnl_is_numeric_with_missing_values_last(dataset):
    repo, t = dataset
    ascending, _ = repo.list(TradeCriteria(sort="pnl", descending=False))
    descending, _ = repo.list(TradeCriteria(sort="pnl", descending=True))
    assert ids(ascending, t, "b", "d", "a", "c")  # -5, 0, 10, then the open trade
    assert ids(descending, t, "a", "d", "b", "c")


def test_paging_keeps_the_total(dataset):
    repo, t = dataset
    rows, total = repo.list(TradeCriteria(limit=2, offset=1))
    assert total == 4 and ids(rows, t, "c", "b")


def test_tags_are_reused_case_insensitively_keeping_the_first_spelling(dataset, session):
    _, t = dataset
    assert session.scalar(select(func.count()).select_from(Tag)) == 2
    assert [tag.name for tag in t["b"].tags] == ["breakout"]


def test_unused_tags_are_collected(dataset, session):
    repo, t = dataset
    repo.set_tags(t["a"], [])
    repo.collect_orphan_tags()
    session.commit()
    assert [name for (name,) in session.execute(select(Tag.name))] == ["breakout"]


def test_tag_usage_counts_most_used_first(dataset, session):
    assert TagRepository(session).usage() == [("breakout", 2), ("london", 1)]


def test_deleting_a_trade_removes_its_tag_links(dataset, session):
    repo, t = dataset
    repo.delete(t["a"])
    repo.collect_orphan_tags()
    session.commit()
    assert session.scalar(select(func.count()).select_from(trade_tags)) == 1
    assert TagRepository(session).usage() == [("breakout", 1)]


@pytest.mark.parametrize(
    "overrides",
    [
        dict(lot_size=Decimal("0")),
        dict(entry_price=Decimal("0")),
        dict(side="sideways"),
        dict(closed_at=utc(2030, 1, 1)),  # before it opened
        dict(exit_price=None),  # closed without an exit price
        dict(pnl=None),  # closed without P&L
    ],
)
def test_the_database_itself_refuses_invalid_trades(session, overrides):
    session.add(make_trade(**overrides))
    with pytest.raises(IntegrityError):
        session.commit()


def test_the_database_refuses_closing_data_on_an_open_trade(session):
    session.add(open_trade(pnl=Decimal("5")))
    with pytest.raises(IntegrityError):
        session.commit()


def test_notes_list_newest_day_first_with_inclusive_bounds(session):
    repo = NoteRepository(session)
    for day, body in [(date(2030, 1, 1), "a"), (date(2030, 1, 2), "b"), (date(2030, 1, 2), "c"), (date(2030, 1, 3), "d")]:
        repo.add(Note(day=day, body=body))
    session.commit()
    rows, total = repo.list(date(2030, 1, 2), date(2030, 1, 3), 10, 0)
    assert total == 3 and [n.body for n in rows] == ["d", "c", "b"]
    rows, total = repo.list(None, None, 2, 2)
    assert total == 4 and [n.body for n in rows] == ["b", "a"]
