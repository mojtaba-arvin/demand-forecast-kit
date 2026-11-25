import json
import sqlite3
from pathlib import Path

import pytest

import demand_forecast_kit.db_admin as db_admin
from demand_forecast_kit.db_admin import (
    backup_database,
    main,
    restore_database,
    verify_database,
)


def _create_database(path, *, child_parent_id=1) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute(
            "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL "
            "REFERENCES parent(id))"
        )
        connection.execute("INSERT INTO parent (id, value) VALUES (1, 'original')")
        if child_parent_id is not None:
            connection.execute(
                "INSERT INTO child (id, parent_id) VALUES (1, ?)", (child_parent_id,)
            )


def test_online_backup_verify_and_restore_round_trip(tmp_path) -> None:
    database = tmp_path / "operations.sqlite"
    backup = tmp_path / "backup.sqlite"
    _create_database(database)

    result = backup_database(database, backup)
    assert result["integrity_check"] == "ok"
    assert len(result["sha256"]) == 64
    assert verify_database(backup)["foreign_key_violations"] == 0

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE parent SET value='changed' WHERE id=1")
        connection.execute("INSERT INTO parent (id, value) VALUES (2, 'new')")

    for suffix in ("-wal", "-shm", "-journal"):
        Path(f"{database}{suffix}").write_bytes(b"stale-sidecar")

    restored = restore_database(backup, database, confirm_services_stopped=True)
    assert restored["integrity_check"] == "ok"
    assert all(not Path(f"{database}{suffix}").exists() for suffix in ("-wal", "-shm", "-journal"))
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT value FROM parent WHERE id=1").fetchone()[0] == "original"
        assert connection.execute("SELECT COUNT(*) FROM parent").fetchone()[0] == 1


def test_backup_refuses_overwrite_and_same_path(tmp_path) -> None:
    database = tmp_path / "operations.sqlite"
    backup = tmp_path / "backup.sqlite"
    _create_database(database)
    backup_database(database, backup)

    with pytest.raises(FileExistsError):
        backup_database(database, backup)
    with pytest.raises(ValueError, match="different files"):
        backup_database(database, database)


def test_restore_requires_stopped_services_confirmation(tmp_path) -> None:
    database = tmp_path / "operations.sqlite"
    backup = tmp_path / "backup.sqlite"
    _create_database(database)
    backup_database(database, backup)

    with pytest.raises(ValueError, match="services are stopped"):
        restore_database(backup, database, confirm_services_stopped=False)


def test_verify_detects_foreign_key_violations(tmp_path) -> None:
    database = tmp_path / "broken.sqlite"
    _create_database(database, child_parent_id=None)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("INSERT INTO child (id, parent_id) VALUES (1, 999)")

    with pytest.raises(RuntimeError, match="foreign_key_check"):
        verify_database(database)


def test_db_admin_cli_emits_backup_report(monkeypatch, tmp_path, capsys) -> None:
    database = tmp_path / "operations.sqlite"
    backup = tmp_path / "backup.sqlite"
    _create_database(database)
    monkeypatch.setattr(
        "sys.argv",
        ["demand-forecast-db", "backup", str(database), str(backup)],
    )

    main()

    result = json.loads(capsys.readouterr().out)
    assert result["integrity_check"] == "ok"
    assert result["backup"] == str(backup.resolve())


def test_online_backup_includes_committed_wal_content(tmp_path) -> None:
    database = tmp_path / "wal.sqlite"
    backup = tmp_path / "wal-backup.sqlite"
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO events (value) VALUES ('committed-in-wal')")
        connection.commit()

        backup_database(database, backup)

        with sqlite3.connect(backup) as restored:
            value = restored.execute("SELECT value FROM events").fetchone()[0]
            assert value == "committed-in-wal"
    finally:
        connection.close()


def test_restore_failure_restores_sidecars_and_preserves_database(
    monkeypatch, tmp_path
) -> None:
    database = tmp_path / "operations.sqlite"
    backup = tmp_path / "backup.sqlite"
    _create_database(database)
    backup_database(database, backup)

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE parent SET value='current' WHERE id=1")

    sidecars = {
        "-wal": b"wal-sidecar",
        "-shm": b"shm-sidecar",
        "-journal": b"journal-sidecar",
    }
    for suffix, content in sidecars.items():
        Path(f"{database}{suffix}").write_bytes(content)

    original_replace = db_admin.os.replace

    def fail_database_replacement(source, destination) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        if (
            destination_path == database.resolve()
            and source_path.name.startswith(f".{database.name}.restore.")
        ):
            raise OSError("simulated replacement failure")
        original_replace(source, destination)

    monkeypatch.setattr(db_admin.os, "replace", fail_database_replacement)

    with pytest.raises(OSError, match="simulated replacement failure"):
        restore_database(backup, database, confirm_services_stopped=True)

    for suffix, content in sidecars.items():
        assert Path(f"{database}{suffix}").read_bytes() == content
    with sqlite3.connect(database) as connection:
        value = connection.execute("SELECT value FROM parent WHERE id=1").fetchone()[0]
    assert value == "current"


def test_backup_does_not_overwrite_destination_created_during_publish(
    monkeypatch, tmp_path
) -> None:
    database = tmp_path / "operations.sqlite"
    backup = tmp_path / "backup.sqlite"
    _create_database(database)
    original_link = db_admin.os.link

    def create_destination_then_link(source, destination) -> None:
        Path(destination).write_text("created by concurrent process")
        original_link(source, destination)

    monkeypatch.setattr(db_admin.os, "link", create_destination_then_link)

    with pytest.raises(FileExistsError):
        backup_database(database, backup)

    assert backup.read_text() == "created by concurrent process"
