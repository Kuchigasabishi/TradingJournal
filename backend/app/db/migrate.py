"""Programmatic Alembic helpers: run migrations at startup and report schema state for /api/ready."""
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection
from sqlalchemy.pool import NullPool

from app.db.session import ensure_database_directory

log = logging.getLogger("app.db")

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def alembic_config(url: str | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    if url:
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))  # configparser interpolation
    return config


def current_revision(connection: Connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


def head_revision() -> str:
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    assert head is not None, "no migrations found"
    return head


def run_migrations(url: str, revision: str = "head") -> None:
    """Upgrade the database and log one `migrations` record. Alembic's own INFO chatter stays muted."""
    ensure_database_directory(url)
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            before = current_revision(connection)
        command.upgrade(alembic_config(url), revision)
        with engine.connect() as connection:
            after = current_revision(connection)
    finally:
        engine.dispose()
    log.info("migrations", extra={"from_revision": before, "to_revision": after, "applied": before != after})
