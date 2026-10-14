"""The online backup: consistent, checked, atomic."""
import json
import sqlite3
import threading
from datetime import datetime, timezone

import pytest

from app.db.migrate import run_migrations
from app.tools.backup import BackupError, backup, database_path, main

NOW = datetime(2044, 5, 11, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "tj.db"
    run_migrations(f"sqlite:///{path.as_posix()}")
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("INSERT INTO notes (day, body, created_at, updated_at) VALUES ('2044-05-11', 'kept', '2044-05-11 12:00:00', '2044-05-11 12:00:00')")
    return path


def test_a_backup_is_a_whole_database_with_the_rows_of_its_moment(database, tmp_path):
    result = backup(database, tmp_path / "backups", NOW)
    assert result["integrity"] == "ok" and result["rows"]["notes"] == 1 and result["rows"]["trades"] == 0
    assert result["backup"].endswith("tj-20440511T120000Z.db")
    copy = sqlite3.connect(result["backup"])
    assert copy.execute("SELECT body FROM notes").fetchone() == ("kept",)
    assert copy.execute("PRAGMA journal_mode").fetchone()[0] in ("wal", "delete")
    copy.close()
    assert list((tmp_path / "backups").glob("*.partial")) == [], "no half-written file is left behind"


def test_a_backup_taken_while_the_app_writes_is_still_consistent(database, tmp_path):
    stop = threading.Event()

    def writer():
        db = sqlite3.connect(database, timeout=30)
        n = 0
        while not stop.is_set():
            n += 1
            db.execute("INSERT INTO notes (day, body, created_at, updated_at) VALUES ('2044-05-12', ?, '2044-05-12 00:00:00', '2044-05-12 00:00:00')", (f"note {n}",))
            db.commit()
        db.close()

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        results = [backup(database, tmp_path / "backups", NOW.replace(second=second)) for second in range(5)]
    finally:
        stop.set()
        thread.join()
    assert all(r["integrity"] == "ok" and r["rows"]["notes"] >= 1 for r in results)


def test_it_refuses_what_it_cannot_back_up(tmp_path):
    with pytest.raises(BackupError, match="no database"):
        backup(tmp_path / "missing.db", tmp_path / "out", NOW)
    with pytest.raises(BackupError, match="only a SQLite"):
        database_path("postgresql://u:p@host/db")
    with pytest.raises(BackupError, match="only a SQLite"):
        database_path("sqlite://")


def test_an_unwritable_destination_is_a_clean_error_not_a_traceback(database, tmp_path):
    blocker = tmp_path / "file-not-folder"
    blocker.write_text("in the way")
    with pytest.raises(BackupError, match="cannot write"):
        backup(database, blocker / "backups", NOW)


def test_a_second_backup_in_the_same_second_does_not_replace_the_first(database, tmp_path):
    backup(database, tmp_path / "backups", NOW)
    with pytest.raises(BackupError, match="already exists"):
        backup(database, tmp_path / "backups", NOW)


def test_the_command_line_prints_one_json_line(database, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database.as_posix()}")
    assert main(["--to", str(tmp_path / "out")]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["integrity"] == "ok" and printed["rows"]["notes"] == 1
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'nope.db').as_posix()}")
    assert main(["--to", str(tmp_path / "out")]) == 1
    assert "no database" in json.loads(capsys.readouterr().err)["error"]
