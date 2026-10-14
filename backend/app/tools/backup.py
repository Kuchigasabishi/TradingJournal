"""A consistent copy of the journal's database, taken while the app is running.

    python -m app.tools.backup [--to DIR]             (in the container: docker compose exec app python -m app.tools.backup --to /data/backups)

SQLite's online backup API copies the database page by page under its own locking, so the copy is a single point in time even
while the app writes, and the write-ahead log is accounted for. The copy is checked (`PRAGMA integrity_check`) before it
is reported, and it is written under a temporary name and renamed, so a backup that did not finish never looks like one that
did. One JSON line says what was written. docs/RUNBOOK.md has the restore procedure.
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import make_url

from app.core.config import Settings

COUNTED = ("trades", "notes", "tags", "external_events")


class BackupError(Exception):
    pass


def database_path(url: str) -> Path:
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite" or not parsed.database or parsed.database == ":memory:":
        raise BackupError("only a SQLite database file can be backed up with this tool")
    return Path(parsed.database)


def backup(database: Path, directory: Path, now: datetime | None = None) -> dict:
    if not database.is_file():
        raise BackupError(f"there is no database at {database}")
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise BackupError(f"cannot write to {directory}: {error.strerror}") from None
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    final = directory / f"tj-{stamp}.db"
    if final.exists():
        raise BackupError(f"{final.name} already exists: a backup a second ago is not replaced")
    partial = final.with_suffix(".db.partial")
    source = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True, timeout=30)
    copy = sqlite3.connect(partial)
    try:
        source.backup(copy)
        copy.commit()
        verdict = copy.execute("PRAGMA integrity_check").fetchone()[0]
        if verdict != "ok":
            raise BackupError(f"the copy failed its integrity check: {verdict}")
        tables = {row[0] for row in copy.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        counts = {name: copy.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in COUNTED if name in tables}  # names are constants above
    except Exception as error:
        copy.close()
        source.close()
        partial.unlink(missing_ok=True)
        if isinstance(error, (OSError, sqlite3.Error)) and not isinstance(error, BackupError):
            raise BackupError(f"the backup failed: {error}") from None
        raise
    copy.close()
    source.close()
    os.replace(partial, final)
    return {"backup": str(final), "bytes": final.stat().st_size, "integrity": "ok", "rows": counts}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Back up the journal's SQLite database while the app runs.")
    parser.add_argument("--to", type=Path, help="the folder to write into (default: a backups folder next to the database)")
    args = parser.parse_args(argv)
    try:
        database = database_path(Settings().database_url)
        result = backup(database, args.to or database.parent / "backups")
    except BackupError as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
