"""Shared API types: exact decimals as strings, normalized text, UTC instants and the paging envelope."""
from datetime import timezone
from decimal import Context, Decimal
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    Field,
    PlainSerializer,
    StringConstraints,
)

_CONTEXT = Context(prec=60)


def canonical_decimal(value: Decimal) -> str:
    """Shortest plain-notation form: 1.10000000 -> 1.1, 1E+2 -> 100, -0 -> 0."""
    if value == 0:
        return "0"
    return format(value.normalize(_CONTEXT), "f")


_as_string = PlainSerializer(canonical_decimal, return_type=str, when_used="json")

# Input allows at most 10 whole digits and 8 decimals, so a value always fits the scaled-integer column.
# JSON may carry numbers or strings in; it always carries canonical strings out.
Money = Annotated[Decimal, Field(max_digits=18, decimal_places=8), _as_string]
PositiveMoney = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=8), _as_string]
MoneyOut = Annotated[Decimal, _as_string]

UtcDatetime = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(timezone.utc))]


def normalize_instrument(value):
    return value.strip().upper() if isinstance(value, str) else value


def normalize_tag(value):
    return " ".join(value.split()) if isinstance(value, str) else value


def _normalize_side(value):
    return value.strip().lower() if isinstance(value, str) else value


def _dedupe_tags(names: list[str]) -> list[str]:
    first_spelling: dict[str, str] = {}
    for name in names:
        first_spelling.setdefault(name.casefold(), name)
    return list(first_spelling.values())


def _blank_to_none(value):
    return None if isinstance(value, str) and not value.strip() else value


Instrument = Annotated[
    str, BeforeValidator(normalize_instrument), StringConstraints(pattern=r"^[A-Z0-9][A-Z0-9/._-]{0,19}$")
]
Side = Annotated[Literal["long", "short"], BeforeValidator(_normalize_side)]
TagName = Annotated[str, BeforeValidator(normalize_tag), StringConstraints(pattern=r"^\w[\w \-/.#+]{0,39}$")]
Tags = Annotated[list[TagName], Field(max_length=20), AfterValidator(_dedupe_tags)]

# Free text: trimmed, and a blank value means "no text".
OptionalText = Annotated[
    Annotated[str, StringConstraints(strip_whitespace=True, max_length=10_000)] | None,
    BeforeValidator(_blank_to_none),
]
NoteBody = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10_000)]

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


Status = Literal["open", "closed"]
