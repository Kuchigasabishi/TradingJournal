"""Engine and session setup, plus transaction logging (docs/BLUEPRINT.md, sections 3.4 and 6.3).

Every transaction that commits, and every rolled-back transaction that had written something, is
logged as a `db_transaction` record. The record carries the request ID of the HTTP request that
caused it, so the harness can prove each successful write request is backed by a commit.
"""
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

log = logging.getLogger("app.db")
_WRITE_VERBS = ("INSERT", "UPDATE", "DELETE", "REPLACE")


@dataclass
class _Transaction:
    started: float = field(default_factory=time.perf_counter)
    statements: int = 0
    writes: int = 0


def ensure_database_directory(url: str) -> None:
    """Create the folder of a file-based SQLite database, so a fresh checkout starts without manual setup."""
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite" and parsed.database not in (None, "", ":memory:"):
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)


def make_engine(url: str) -> Engine:
    parsed = make_url(url)
    sqlite = parsed.get_backend_name() == "sqlite"
    options: dict[str, Any] = {}
    if sqlite:
        options["connect_args"] = {"check_same_thread": False}
        if parsed.database in (None, "", ":memory:"):
            options["poolclass"] = StaticPool  # one shared connection, so every session sees the same memory DB
    engine = create_engine(url, **options)
    if sqlite:
        event.listen(engine, "do_connect", lambda dialect, record, args, kwargs: ensure_database_directory(url))
        event.listen(engine, "connect", _sqlite_pragmas)
    _log_transactions(engine)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    # expire_on_commit=False: services refresh explicitly, so returned objects never lazy-load afterwards.
    return sessionmaker(bind=engine, expire_on_commit=False)


def _sqlite_pragmas(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


def _log_transactions(engine: Engine) -> None:
    @event.listens_for(engine, "begin")
    def on_begin(conn) -> None:
        conn.info["transaction"] = _Transaction()

    @event.listens_for(engine, "before_cursor_execute")
    def on_execute(conn, cursor, statement, parameters, context, executemany) -> None:
        current = conn.info.get("transaction")
        if current is not None:
            current.statements += 1
            if statement.lstrip().upper().startswith(_WRITE_VERBS):
                current.writes += 1

    @event.listens_for(engine, "commit")
    def on_commit(conn) -> None:
        _finish(conn, "commit")

    @event.listens_for(engine, "rollback")
    def on_rollback(conn) -> None:
        _finish(conn, "rollback")


def _finish(conn, outcome: str) -> None:
    current = conn.info.pop("transaction", None)
    if current is None:
        return
    # Commits are always logged: services only commit when they mean to write, even if nothing changed.
    # Rollbacks are logged only when something had been written, because read-only requests end in an
    # implicit rollback that is not worth a record.
    if outcome == "rollback" and current.writes == 0:
        return
    log.log(
        logging.INFO if outcome == "commit" else logging.WARNING,
        "db_transaction",
        extra={
            "outcome": outcome,
            "statements": current.statements,
            "writes": current.writes,
            "duration_ms": round((time.perf_counter() - current.started) * 1000, 2),
        },
    )
