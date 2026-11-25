"""SQLite online backup, integrity verification, and controlled restore CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path


def _readonly_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def _integrity_report(path: Path) -> dict[str, int | str]:
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(_readonly_uri(path), uri=True)
    try:
        integrity_rows = [str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        connection.close()
    if integrity_rows != ["ok"]:
        raise RuntimeError(f"SQLite integrity_check failed: {integrity_rows}")
    if foreign_key_errors:
        raise RuntimeError(
            f"SQLite foreign_key_check found {len(foreign_key_errors)} violation(s)"
        )
    return {
        "integrity_check": "ok",
        "foreign_key_violations": len(foreign_key_errors),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _temporary_database(parent: Path, prefix: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=prefix, suffix=".sqlite", dir=parent)
    os.close(descriptor)
    return Path(name)


def backup_database(
    source: Path, destination: Path, *, overwrite: bool = False
) -> dict[str, int | str]:
    """Create and verify a transactionally consistent SQLite online backup."""
    source = source.resolve()
    destination = destination.resolve()
    if source == destination:
        raise ValueError("source and backup destination must be different files")
    if not source.is_file():
        raise FileNotFoundError(source)
    if destination.exists() and not overwrite:
        raise FileExistsError(destination)

    temporary = _temporary_database(destination.parent, f".{destination.name}.")
    try:
        source_connection = sqlite3.connect(_readonly_uri(source), uri=True)
        destination_connection = sqlite3.connect(temporary)
        try:
            source_connection.backup(destination_connection)
            destination_connection.commit()
        finally:
            destination_connection.close()
            source_connection.close()
        integrity = _integrity_report(temporary)
        digest = _sha256_file(temporary)
        os.replace(temporary, destination)
        return {
            "backup": str(destination),
            "sha256": digest,
            **integrity,
        }
    finally:
        temporary.unlink(missing_ok=True)


def verify_database(path: Path) -> dict[str, int | str]:
    """Verify SQLite page integrity and foreign-key consistency."""
    resolved = path.resolve()
    return {
        "database": str(resolved),
        "sha256": _sha256_file(resolved),
        **_integrity_report(resolved),
    }


def restore_database(
    backup: Path,
    destination: Path,
    *,
    confirm_services_stopped: bool,
) -> dict[str, int | str]:
    """Atomically restore a verified backup after the operator stops all DB users."""
    backup = backup.resolve()
    destination = destination.resolve()
    if not confirm_services_stopped:
        raise ValueError(
            "restore requires explicit confirmation that API and worker processes are stopped"
        )
    if backup == destination:
        raise ValueError("backup and restore destination must be different files")
    _integrity_report(backup)

    temporary = _temporary_database(destination.parent, f".{destination.name}.restore.")
    sidecars = [Path(f"{destination}-wal"), Path(f"{destination}-shm")]
    moved_sidecars: list[tuple[Path, Path]] = []
    try:
        source_connection = sqlite3.connect(_readonly_uri(backup), uri=True)
        destination_connection = sqlite3.connect(temporary)
        try:
            source_connection.backup(destination_connection)
            destination_connection.commit()
        finally:
            destination_connection.close()
            source_connection.close()
        integrity = _integrity_report(temporary)

        try:
            for sidecar in sidecars:
                if sidecar.exists():
                    parked = _temporary_database(destination.parent, f".{sidecar.name}.")
                    parked.unlink(missing_ok=True)
                    os.replace(sidecar, parked)
                    moved_sidecars.append((sidecar, parked))
            os.replace(temporary, destination)
        except Exception:
            for original, parked in moved_sidecars:
                if parked.exists():
                    os.replace(parked, original)
            raise
        for _original, parked in moved_sidecars:
            parked.unlink(missing_ok=True)

        return {
            "restored_from": str(backup),
            "database": str(destination),
            "sha256": _sha256_file(destination),
            **integrity,
        }
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    backup = commands.add_parser("backup", help="create an online SQLite backup")
    backup.add_argument("database", type=Path)
    backup.add_argument("destination", type=Path)
    backup.add_argument("--overwrite", action="store_true")

    verify = commands.add_parser("verify", help="verify a database or backup")
    verify.add_argument("database", type=Path)

    restore = commands.add_parser(\n        "restore", help="restore a backup while services are stopped"\n    )
    restore.add_argument("backup", type=Path)
    restore.add_argument("database", type=Path)
    restore.add_argument("--confirm-services-stopped", action="store_true")

    args = parser.parse_args()
    try:
        if args.command == "backup":
            result = backup_database(\n                args.database, args.destination, overwrite=args.overwrite\n            )
        elif args.command == "verify":
            result = verify_database(args.database)
        else:
            result = restore_database(
                args.backup,
                args.database,
                confirm_services_stopped=args.confirm_services_stopped,
            )
    except (\n        FileNotFoundError,\n        FileExistsError,\n        OSError,\n        sqlite3.Error,\n        RuntimeError,\n        ValueError,\n    ) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
