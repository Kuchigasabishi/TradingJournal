"""external events and feed state

Events from outside calendars (ForexFactory economic news, the owner's Google Calendar) and the schedule and
outcome of each feed. Timed events carry UTC instants; all-day events carry dates with an exclusive end, as
iCalendar does. Like the baseline, this migration uses plain storage types on purpose.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("external_key", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location", sa.String(length=300), nullable=True),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("currency", sa.String(length=12), nullable=True),
        sa.Column("impact", sa.String(length=10), nullable=True),
        sa.Column("forecast", sa.String(length=40), nullable=True),
        sa.Column("previous", sa.String(length=40), nullable=True),
        sa.Column("all_day", sa.Boolean(), nullable=False),
        sa.Column("start_at", sa.DateTime(), nullable=True),
        sa.Column("end_at", sa.DateTime(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("source IN ('forexfactory', 'gcal')", name=op.f("ck_external_events_source_valid")),
        sa.CheckConstraint(
            "impact IS NULL OR impact IN ('low', 'medium', 'high', 'holiday', 'unknown')", name=op.f("ck_external_events_impact_valid")
        ),
        sa.CheckConstraint(
            "(all_day = 1 AND start_date IS NOT NULL AND end_date IS NOT NULL AND start_at IS NULL AND end_at IS NULL)"
            " OR (all_day = 0 AND start_at IS NOT NULL AND start_date IS NULL AND end_date IS NULL)",
            name=op.f("ck_external_events_timed_or_all_day"),
        ),
        sa.CheckConstraint("end_at IS NULL OR end_at >= start_at", name=op.f("ck_external_events_end_not_before_start")),
        sa.CheckConstraint("end_date IS NULL OR end_date > start_date", name=op.f("ck_external_events_end_date_after_start")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_events")),
        sa.UniqueConstraint("source", "external_key", name="uq_external_events_source_key"),
        sqlite_autoincrement=True,
    )
    op.create_index(op.f("ix_external_events_start_at"), "external_events", ["start_at"])
    op.create_index(op.f("ix_external_events_start_date"), "external_events", ["start_date"])

    op.create_table(
        "feed_state",
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("next_due_at", sa.DateTime(), nullable=True),
        sa.Column("next_manual_at", sa.DateTime(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("message", sa.String(length=200), nullable=True),
        sa.Column("etag", sa.String(length=200), nullable=True),
        sa.Column("last_modified", sa.String(length=100), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("source IN ('forexfactory', 'gcal')", name=op.f("ck_feed_state_source_valid")),
        sa.CheckConstraint("state IN ('idle', 'queued', 'running')", name=op.f("ck_feed_state_state_valid")),
        sa.CheckConstraint("status IN ('never', 'ok', 'throttled', 'bad_content', 'error')", name=op.f("ck_feed_state_status_valid")),
        sa.PrimaryKeyConstraint("source", name=op.f("pk_feed_state")),
    )


def downgrade() -> None:
    op.drop_table("feed_state")
    op.drop_index(op.f("ix_external_events_start_date"), table_name="external_events")
    op.drop_index(op.f("ix_external_events_start_at"), table_name="external_events")
    op.drop_table("external_events")
