from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, func, insert, select

from app.db.types import ScaledDecimal, UtcDateTime, from_scaled, to_scaled


def test_to_scaled_is_exact():
    assert to_scaled(Decimal("1.1")) == 110_000_000
    assert to_scaled("0.00000001") == 1
    assert to_scaled(Decimal("-0.00000001")) == -1
    assert to_scaled(5) == 500_000_000
    assert to_scaled(Decimal("9999999999.99999999")) == 999_999_999_999_999_999


def test_to_scaled_never_rounds():
    with pytest.raises(ValueError, match="more than 8 decimal places"):
        to_scaled(Decimal("0.000000001"))


@pytest.mark.parametrize("bad", ["abc", "NaN", "Infinity", Decimal("NaN")])
def test_to_scaled_rejects_non_numbers(bad):
    with pytest.raises(ValueError):
        to_scaled(bad)


@pytest.mark.parametrize("bad", [0.1, True])
def test_to_scaled_rejects_floats_and_bools(bad):
    with pytest.raises(TypeError):
        to_scaled(bad)


def test_to_scaled_rejects_values_that_would_not_fit_in_64_bits():
    with pytest.raises(ValueError, match="18 digits"):
        to_scaled(Decimal("10000000000"))


@pytest.mark.parametrize("text", ["0", "1.1", "-0.00000001", "9999999999.99999999", "123.45678901"[:12]])
def test_scaled_round_trip(text):
    assert from_scaled(to_scaled(Decimal(text))) == Decimal(text)


def test_sql_sums_and_sorts_money_exactly():
    table = Table("t", MetaData(), Column("id", Integer, primary_key=True), Column("v", ScaledDecimal))
    engine = create_engine("sqlite://")
    table.create(engine)
    with engine.begin() as connection:
        connection.execute(insert(table), [{"v": Decimal(v)} for v in ("0.1", "0.2", "-10", "2", "100")])
        total = connection.scalar(select(func.sum(table.c.v)).where(table.c.v < 1))
        ordered = connection.scalars(select(table.c.v).order_by(table.c.v)).all()
    assert total == Decimal("-9.7")  # 0.1 + 0.2 - 10, with no floating-point residue
    assert ordered == [Decimal("-10"), Decimal("0.1"), Decimal("0.2"), Decimal("2"), Decimal("100")]


def test_utc_datetime_rejects_naive_values():
    with pytest.raises(ValueError, match="UTC offset"):
        UtcDateTime().process_bind_param(datetime(2030, 1, 1), None)


def test_utc_datetime_stores_utc_and_returns_aware_utc():
    table = Table("t", MetaData(), Column("id", Integer, primary_key=True), Column("at", UtcDateTime))
    engine = create_engine("sqlite://")
    table.create(engine)
    eastern = timezone(timedelta(hours=-5))
    with engine.begin() as connection:
        connection.execute(insert(table), [{"at": datetime(2031, 3, 8, 12, 0, tzinfo=eastern)}])
        value = connection.scalar(select(table.c.at))
    assert value == datetime(2031, 3, 8, 17, 0, tzinfo=timezone.utc)
    assert value.utcoffset() == timedelta(0)
