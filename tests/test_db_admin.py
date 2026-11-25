import json
import sqlite3

import pytest

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

    restored = restore_database(backup, database, confirm_services_stopped=True)
    assert restored["integrity_check"] == "ok"
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
