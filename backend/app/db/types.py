"""Column types that keep money exact and instants unambiguous on SQLite (docs/BLUEPRINT.md, P3 and P4).

Money, prices and lot sizes are stored as integer counts of 1e-8 units. That is exact to store, sum
and sort in SQL, where SQLite's own NUMERIC would silently fall back to binary floating point.
Instants are stored as naive UTC and always come back as timezone-aware UTC.
"""
from datetime import datetime, timezone
from decimal import Context, Decimal, InvalidOperation

from sqlalchemy import BigInteger, DateTime
from sqlalchemy.types import TypeDecorator

SCALE = 8
MAX_DIGITS = 18  # 18 digits at scale 1e-8 stays below the signed 64-bit limit once scaled
_CONTEXT = Context(prec=60)  # wide enough that scaling never rounds, whatever the thread's context says


def to_scaled(value: Decimal | int | str) -> int:
    """Exact integer count of 1e-8 units. Raises ValueError rather than ever rounding."""
    if isinstance(value, (float, bool)):
        raise TypeError("money must be a Decimal, int or str, never a float")
    try:
        number = value if isinstance(value, Decimal) else Decimal(value)
    except InvalidOperation:
        raise ValueError(f"not a number: {value!r}") from None
    if not number.is_finite():
        raise ValueError(f"not a finite number: {value!r}")
    scaled = number.scaleb(SCALE, context=_CONTEXT)
    whole = scaled.to_integral_value()
    if scaled != whole:
        raise ValueError(f"{number} has more than {SCALE} decimal places")
    result = int(whole)
    if abs(result) >= 10**MAX_DIGITS:
        raise ValueError(f"{number} has more than {MAX_DIGITS} digits")
    return result


def from_scaled(value: int) -> Decimal:
    return Decimal(value).scaleb(-SCALE, context=_CONTEXT)


class ScaledDecimal(TypeDecorator):
    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else to_scaled(value)

    def process_result_value(self, value, dialect):
        return None if value is None else from_scaled(value)


class UtcDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("naive datetime: an explicit UTC offset is required")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return None if value is None else value.replace(tzinfo=timezone.utc)
