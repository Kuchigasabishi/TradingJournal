"""baseline: trades, tags, trade_tags and notes

Money columns are integer counts of 1e-8 units and instants are naive UTC. The migration uses plain
storage types on purpose, so it never depends on application code that may change later.

Revision ID: 0001
Revises:
Create Date: 2026-10-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instrument", sa.String(length=20), nullable=False),
        sa.Column("side", sa.String(length=5), nullable=False),
        sa.Column("lot_size", sa.BigInteger(), nullable=False),
        sa.Column("entry_price", sa.BigInteger(), nullable=False),
        sa.Column("exit_price", sa.BigInteger(), nullable=True),
        sa.Column("opened_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("pnl", sa.BigInteger(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("side IN ('long', 'short')", name=op.f("ck_trades_side_valid")),
        sa.CheckConstraint("lot_size > 0", name=op.f("ck_trades_lot_size_positive")),
        sa.CheckConstraint("entry_price > 0", name=op.f("ck_trades_entry_price_positive")),
        sa.CheckConstraint("exit_price IS NULL OR exit_price > 0", name=op.f("ck_trades_exit_price_positive")),
        sa.CheckConstraint("closed_at IS NULL OR closed_at >= opened_at", name=op.f("ck_trades_closed_after_opened")),
        sa.CheckConstraint(
            "(closed_at IS NULL) = (exit_price IS NULL) AND (closed_at IS NULL) = (pnl IS NULL)",
            name=op.f("ck_trades_closure_all_or_nothing"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trades")),
        sqlite_autoincrement=True,
    )
    op.create_index(op.f("ix_trades_instrument"), "trades", ["instrument"])
    op.create_index(op.f("ix_trades_opened_at"), "trades", ["opened_at"])
    op.create_index(op.f("ix_trades_closed_at"), "trades", ["closed_at"])

    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=40, collation="NOCASE"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tags")),
        sa.UniqueConstraint("name", name=op.f("uq_tags_name")),
        sqlite_autoincrement=True,
    )

    op.create_table(
        "trade_tags",
        sa.Column("trade_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["trade_id"], ["trades.id"], name=op.f("fk_trade_tags_trade_id_trades"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], name=op.f("fk_trade_tags_tag_id_tags"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("trade_id", "tag_id", name=op.f("pk_trade_tags")),
    )
    op.create_index(op.f("ix_trade_tags_tag_id"), "trade_tags", ["tag_id"])

    op.create_table(
        "notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notes")),
        sqlite_autoincrement=True,
    )
    op.create_index(op.f("ix_notes_day"), "notes", ["day"])


def downgrade() -> None:
    op.drop_index(op.f("ix_notes_day"), table_name="notes")
    op.drop_table("notes")
    op.drop_index(op.f("ix_trade_tags_tag_id"), table_name="trade_tags")
    op.drop_table("trade_tags")
    op.drop_table("tags")
    op.drop_index(op.f("ix_trades_closed_at"), table_name="trades")
    op.drop_index(op.f("ix_trades_opened_at"), table_name="trades")
    op.drop_index(op.f("ix_trades_instrument"), table_name="trades")
    op.drop_table("trades")
