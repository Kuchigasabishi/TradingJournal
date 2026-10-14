import logging

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.db.migrate import alembic_config, current_revision, head_revision, run_migrations
from app.db.models import Base
from app.db.session import make_engine
from app.main import create_app

OPENED = "2030-01-02 09:00:00.000000"
CLOSED = "2030-01-02 13:00:00.000000"


@pytest.fixture
def url(tmp_path) -> str:
    return f"sqlite:///{(tmp_path / 'journal.db').as_posix()}"


@pytest.fixture
def migrated(url):
    run_migrations(url)
    engine = make_engine(url)  # same pragmas as the app, foreign keys on
    yield engine
    engine.dispose()


def insert_trade(connection, **overrides):
    row = dict(
        instrument="EURUSD", side="long", lot_size=10_000_000, entry_price=110_000_000, exit_price=None,
        opened_at=OPENED, closed_at=None, pnl=None, created_at=OPENED, updated_at=OPENED,
    )
    row.update(overrides)
    connection.execute(
        text(
            "INSERT INTO trades (instrument, side, lot_size, entry_price, exit_price, opened_at, closed_at, pnl, created_at, updated_at) "
            "VALUES (:instrument, :side, :lot_size, :entry_price, :exit_price, :opened_at, :closed_at, :pnl, :created_at, :updated_at)"
        ),
        row,
    )


def test_upgrade_creates_the_schema_and_stamps_the_head(migrated):
    assert {"trades", "tags", "trade_tags", "notes", "alembic_version"} <= set(inspect(migrated).get_table_names())
    with migrated.connect() as connection:
        assert current_revision(connection) == head_revision()


def test_the_migration_and_the_models_describe_the_same_schema(migrated):
    with migrated.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []


def test_downgrade_removes_every_table(url):
    run_migrations(url)
    command.downgrade(alembic_config(url), "base")
    assert set(inspect(create_engine(url)).get_table_names()) <= {"alembic_version"}


def test_a_valid_trade_is_accepted(migrated):
    with migrated.begin() as connection:
        insert_trade(connection)
        insert_trade(connection, closed_at=CLOSED, exit_price=120_000_000, pnl=1_000_000_000)


@pytest.mark.parametrize(
    "overrides",
    [
        dict(lot_size=0),
        dict(entry_price=0),
        dict(side="sideways"),
        dict(closed_at="2030-01-01 09:00:00.000000", exit_price=1, pnl=1),  # before it opened
        dict(closed_at=CLOSED, exit_price=1),  # closed without P&L
        dict(closed_at=CLOSED, pnl=1),  # closed without an exit price
        dict(pnl=5),  # P&L on an open trade
        dict(exit_price=5),  # exit price on an open trade
        dict(closed_at=CLOSED, exit_price=0, pnl=1),
    ],
)
def test_the_migrated_schema_enforces_the_trade_rules(migrated, overrides):
    with pytest.raises(IntegrityError):
        with migrated.begin() as connection:
            insert_trade(connection, **overrides)


def test_tag_names_are_unique_ignoring_case(migrated):
    with migrated.begin() as connection:
        connection.execute(text("INSERT INTO tags (name) VALUES ('Breakout')"))
    with pytest.raises(IntegrityError):
        with migrated.begin() as connection:
            connection.execute(text("INSERT INTO tags (name) VALUES ('breakout')"))


def test_deleting_a_trade_cascades_to_its_tag_links(migrated):
    with migrated.begin() as connection:
        insert_trade(connection)
        connection.execute(text("INSERT INTO tags (name) VALUES ('a')"))
        connection.execute(text("INSERT INTO trade_tags (trade_id, tag_id) VALUES (1, 1)"))
        connection.execute(text("DELETE FROM trades"))
        assert connection.scalar(text("SELECT count(*) FROM trade_tags")) == 0


def test_ids_are_never_reused_after_a_delete(migrated):
    with migrated.begin() as connection:
        insert_trade(connection)
        connection.execute(text("DELETE FROM trades"))
        insert_trade(connection)
        assert connection.scalar(text("SELECT id FROM trades")) == 2


def test_startup_applies_the_migrations_and_reports_ready(url):
    settings = Settings(app_env="test", database_url=url, auto_migrate=True, _env_file=None)
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok", "migration": head_revision(), "timezone": "UTC"}


def test_ready_reports_the_time_zone_clients_should_use(url):
    settings = Settings(app_env="test", database_url=url, app_timezone="America/New_York", auto_migrate=True, _env_file=None)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/ready").json()["timezone"] == "America/New_York"


def test_a_fresh_checkout_creates_its_database_folder(tmp_path):
    nested = tmp_path / "not" / "yet" / "there" / "journal.db"
    settings = Settings(app_env="test", database_url=f"sqlite:///{nested.as_posix()}", auto_migrate=True, _env_file=None)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/ready").status_code == 200
    assert nested.is_file()


def test_startup_logs_one_migrations_record(url, caplog):
    caplog.set_level(logging.INFO, logger="app.db")
    run_migrations(url)
    run_migrations(url)  # already at head
    records = [r for r in caplog.records if r.getMessage() == "migrations"]
    head = head_revision()
    assert [(r.from_revision, r.to_revision, r.applied) for r in records] == [(None, head, True), (head, head, False)]


def test_data_survives_an_app_restart(url):
    settings = Settings(app_env="test", database_url=url, auto_migrate=True, _env_file=None)
    payload = {"instrument": "GBPJPY", "side": "short", "lot_size": "0.01", "entry_price": "190.12345678", "opened_at": "2030-01-02T09:00:00Z"}
    with TestClient(create_app(settings)) as first:
        created = first.post("/api/trades", json=payload).json()
    with TestClient(create_app(settings)) as second:  # a new app, engine and connection pool on the same file
        assert second.get(f"/api/trades/{created['id']}").json() == created


# --- Phase 3: external events and feed state -----------------------------------------------------------------------------------


def insert_event(connection, **overrides):
    row = dict(
        source="forexfactory", external_key="k1", title="CPI", all_day=0, start_at=OPENED, end_at=None, start_date=None, end_date=None,
        impact="high", first_seen_at=OPENED, updated_at=OPENED,
    )
    row.update(overrides)
    connection.execute(
        text(
            "INSERT INTO external_events (source, external_key, title, all_day, start_at, end_at, start_date, end_date, impact, first_seen_at, updated_at) "
            "VALUES (:source, :external_key, :title, :all_day, :start_at, :end_at, :start_date, :end_date, :impact, :first_seen_at, :updated_at)"
        ),
        row,
    )


def test_the_event_tables_exist_after_upgrade(migrated):
    assert {"external_events", "feed_state"} <= set(inspect(migrated).get_table_names())


def test_an_event_is_timed_or_all_day_never_both_and_never_neither(migrated):
    with migrated.begin() as connection:
        insert_event(connection, external_key="timed")
        insert_event(connection, external_key="all-day", all_day=1, start_at=None, start_date="2044-05-12", end_date="2044-05-13")
    bad = [
        dict(external_key="both", all_day=1, start_date="2044-05-12", end_date="2044-05-13"),  # a start time and dates
        dict(external_key="neither", start_at=None),
        dict(external_key="all-day-no-end", all_day=1, start_at=None, start_date="2044-05-12"),
        dict(external_key="timed-with-dates", start_date="2044-05-12", end_date="2044-05-13"),
        dict(external_key="ends-first", end_at="2030-01-02 08:00:00.000000"),
        dict(external_key="empty-span", all_day=1, start_at=None, start_date="2044-05-12", end_date="2044-05-12"),
    ]
    for overrides in bad:
        with pytest.raises(IntegrityError), migrated.begin() as connection:
            insert_event(connection, **overrides)


def test_a_source_and_an_impact_must_be_known_and_a_key_is_unique_within_its_source(migrated):
    with migrated.begin() as connection:
        insert_event(connection)
    for overrides in (dict(external_key="a", source="outlook"), dict(external_key="b", impact="extreme"), dict(external_key="k1")):
        with pytest.raises(IntegrityError), migrated.begin() as connection:
            insert_event(connection, **overrides)
    with migrated.begin() as connection:
        insert_event(connection, source="gcal", impact=None)  # the same key under another source is a different event


def test_feed_state_allows_only_known_values(migrated):
    def insert(**overrides):
        row = dict(source="forexfactory", state="idle", status="never", consecutive_failures=0, updated_at=OPENED)
        row.update(overrides)
        with migrated.begin() as connection:
            connection.execute(text("INSERT INTO feed_state (source, state, status, consecutive_failures, updated_at) VALUES (:source, :state, :status, :consecutive_failures, :updated_at)"), row)

    insert()
    for overrides in (dict(source="outlook"), dict(source="gcal", state="paused"), dict(source="gcal", status="fine")):
        with pytest.raises(IntegrityError):
            insert(**overrides)
    with pytest.raises(IntegrityError):
        insert()  # one row per source
