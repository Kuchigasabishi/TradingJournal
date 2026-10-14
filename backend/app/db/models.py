"""SQLAlchemy 2.0 models for the journal (docs/BLUEPRINT.md, section 4.1)."""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Column, Date, ForeignKey, Index, Integer, MetaData, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.clock import utcnow
from app.db.types import ScaledDecimal, UtcDateTime

# Explicit constraint names keep SQLite batch migrations and Alembic's drift check reliable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


trade_tags = Table(
    "trade_tags",
    Base.metadata,
    Column("trade_id", ForeignKey("trades.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    Index("ix_trade_tags_tag_id", "tag_id"),
)


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(primary_key=True)
    # NOCASE makes "Breakout" and "breakout" one tag; the first spelling used is kept.
    name: Mapped[str] = mapped_column(String(40, collation="NOCASE"), unique=True)


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (
        CheckConstraint("side IN ('long', 'short')", name="side_valid"),
        CheckConstraint("lot_size > 0", name="lot_size_positive"),
        CheckConstraint("entry_price > 0", name="entry_price_positive"),
        CheckConstraint("exit_price IS NULL OR exit_price > 0", name="exit_price_positive"),
        CheckConstraint("closed_at IS NULL OR closed_at >= opened_at", name="closed_after_opened"),
        # A trade is open (no closing data at all) or closed (all of it): never half and half.
        CheckConstraint(
            "(closed_at IS NULL) = (exit_price IS NULL) AND (closed_at IS NULL) = (pnl IS NULL)",
            name="closure_all_or_nothing",
        ),
        Index("ix_trades_instrument", "instrument"),
        Index("ix_trades_opened_at", "opened_at"),
        Index("ix_trades_closed_at", "closed_at"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument: Mapped[str] = mapped_column(String(20))
    side: Mapped[str] = mapped_column(String(5))
    lot_size: Mapped[Decimal] = mapped_column(ScaledDecimal)
    entry_price: Mapped[Decimal] = mapped_column(ScaledDecimal)
    exit_price: Mapped[Decimal | None] = mapped_column(ScaledDecimal)
    opened_at: Mapped[datetime] = mapped_column(UtcDateTime)
    closed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    pnl: Mapped[Decimal | None] = mapped_column(ScaledDecimal)  # user-entered, account currency
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)

    tags: Mapped[list[Tag]] = relationship(
        secondary=trade_tags, order_by=Tag.name, lazy="selectin", passive_deletes=True
    )


class Note(Base):
    """A journal note for one calendar day. Trade-specific notes live on the trade itself."""

    __tablename__ = "notes"
    __table_args__ = (Index("ix_notes_day", "day"), {"sqlite_autoincrement": True})

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


FEED_SOURCES = ("forexfactory", "gcal")
EVENT_IMPACTS = ("low", "medium", "high", "holiday", "unknown")


class ExternalEvent(Base):
    """An event from an outside calendar: ForexFactory's economic calendar or the owner's Google Calendar.

    A timed event has `start_at` (and perhaps `end_at`), both UTC instants. An all-day event has dates instead:
    `start_date` and an exclusive `end_date`, as iCalendar writes them, so a holiday stays on its own day whatever
    the display time zone is. Calendar days are computed when read, like trade days.
    """

    __tablename__ = "external_events"
    __table_args__ = (
        CheckConstraint("source IN ('forexfactory', 'gcal')", name="source_valid"),
        CheckConstraint("impact IS NULL OR impact IN ('low', 'medium', 'high', 'holiday', 'unknown')", name="impact_valid"),
        # Timed or all-day, never both and never neither.
        CheckConstraint(
            "(all_day = 1 AND start_date IS NOT NULL AND end_date IS NOT NULL AND start_at IS NULL AND end_at IS NULL)"
            " OR (all_day = 0 AND start_at IS NOT NULL AND start_date IS NULL AND end_date IS NULL)",
            name="timed_or_all_day",
        ),
        CheckConstraint("end_at IS NULL OR end_at >= start_at", name="end_not_before_start"),
        CheckConstraint("end_date IS NULL OR end_date > start_date", name="end_date_after_start"),
        UniqueConstraint("source", "external_key", name="uq_external_events_source_key"),
        Index("ix_external_events_start_at", "start_at"),
        Index("ix_external_events_start_date", "start_date"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16))
    external_key: Mapped[str] = mapped_column(String(64))  # stable within the source: a hash, or the iCal UID and instance
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(String(500))
    currency: Mapped[str | None] = mapped_column(String(12))  # news only: USD, EUR ... or ALL
    impact: Mapped[str | None] = mapped_column(String(10))  # news only
    forecast: Mapped[str | None] = mapped_column(String(40))
    previous: Mapped[str | None] = mapped_column(String(40))
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    start_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    end_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)  # exclusive
    first_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class FeedState(Base):
    """Where one feed stands: its schedule (kept across restarts, so a restart never refetches early), the outcome
    of its last attempt and its backoff. One row per source."""

    __tablename__ = "feed_state"
    __table_args__ = (
        CheckConstraint("source IN ('forexfactory', 'gcal')", name="source_valid"),
        CheckConstraint("state IN ('idle', 'queued', 'running')", name="state_valid"),
        CheckConstraint("status IN ('never', 'ok', 'throttled', 'bad_content', 'error')", name="status_valid"),
    )

    source: Mapped[str] = mapped_column(String(16), primary_key=True)
    state: Mapped[str] = mapped_column(String(10), default="idle")
    status: Mapped[str] = mapped_column(String(12), default="never")
    last_attempt_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    next_due_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    next_manual_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    http_status: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str | None] = mapped_column(String(200))  # short, never holds a URL
    etag: Mapped[str | None] = mapped_column(String(200))
    last_modified: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
