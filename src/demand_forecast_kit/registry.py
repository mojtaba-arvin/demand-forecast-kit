"""SQLite-backed, idempotent persistence for forecast execution metadata."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RunRecord:
    """Immutable metadata for one reproducible execution."""

    run_id: int
    idempotency_key: str
    dataset_fingerprint: str
    model_id: str
    model_version: str
    status: str
    created_at: str
    config: dict[str, Any]
    result: dict[str, Any] | None


class SQLiteRunRegistry:
    """Small local registry using only the Python standard library.

    The registry stores metadata and JSON results, not large forecast arrays.
    Artifact files can be stored separately and referenced from the result.
    """

    def __init__(self, database: str | Path) -> None:
        self.database = str(database)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS forecast_runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    dataset_fingerprint TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('created', 'completed', 'failed')),
                    created_at TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    result_json TEXT
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=10.0)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _json(value: dict[str, Any]) -> str:
        try:
            return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("registry payload must be finite JSON data") from exc

    def create_run(
        self,
        *,
        idempotency_key: str,
        dataset_fingerprint: str,
        model_id: str,
        model_version: str,
        config: dict[str, Any],
    ) -> RunRecord:
        """Create a run once; retries with the same key return the original run."""
        for name, value in (
            ("idempotency_key", idempotency_key),
            ("dataset_fingerprint", dataset_fingerprint),
            ("model_id", model_id),
            ("model_version", model_version),
        ):
            if not value.strip():
                raise ValueError(f"{name} must not be blank")
        config_json = self._json(config)
        created_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO forecast_runs (
                    idempotency_key, dataset_fingerprint, model_id, model_version,
                    status, created_at, config_json
                ) VALUES (?, ?, ?, ?, 'created', ?, ?)
                ON CONFLICT(idempotency_key) DO NOTHING
                """,
                (
                    idempotency_key,
                    dataset_fingerprint,
                    model_id,
                    model_version,
                    created_at,
                    config_json,
                ),
            )
            row = connection.execute(
                "SELECT * FROM forecast_runs WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        assert row is not None
        return self._record(row)

    def complete_run(self, run_id: int, result: dict[str, Any]) -> RunRecord:
        """Mark a run completed and persist its deterministic JSON result."""
        result_json = self._json(result)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE forecast_runs SET status = 'completed', result_json = ?
                WHERE run_id = ? AND status = 'created'
                """,
                (result_json, run_id),
            )
            if cursor.rowcount == 0:
                row = connection.execute(
                    "SELECT * FROM forecast_runs WHERE run_id = ?", (run_id,)
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown run_id: {run_id}")
                if row["status"] != "completed" or row["result_json"] != result_json:
                    raise ValueError("run cannot be completed from its current state")
            row = connection.execute(
                "SELECT * FROM forecast_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        assert row is not None
        return self._record(row)

    def get_run(self, run_id: int) -> RunRecord:
        """Retrieve a run by its stable numeric identifier."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM forecast_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown run_id: {run_id}")
        return self._record(row)

    @staticmethod
    def _record(row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            run_id=int(row["run_id"]),
            idempotency_key=str(row["idempotency_key"]),
            dataset_fingerprint=str(row["dataset_fingerprint"]),
            model_id=str(row["model_id"]),
            model_version=str(row["model_version"]),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            config=json.loads(row["config_json"]),
            result=None if row["result_json"] is None else json.loads(row["result_json"]),
        )
