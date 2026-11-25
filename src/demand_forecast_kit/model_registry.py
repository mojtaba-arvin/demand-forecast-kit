"""Persistent, content-addressed model artifacts with explicit activation control.

The registry stores opaque model bytes and their evaluation evidence. It never
unpickles, imports, or executes an artifact; applications provide their own
reviewed loader for a registered media type.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from demand_forecast_kit.artifacts import FileArtifactStore


@dataclass(frozen=True, slots=True)
class ModelArtifactRecord:
    """Immutable metadata for one validated model artifact."""

    model_id: str
    model_version: str
    artifact_sha256: str
    evaluation_sha256: str
    media_type: str
    validation_mae: float
    validation_sample_count: int
    created_at: str
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ModelActivation:
    """Result of an explicit activation or rollback operation."""

    event_id: int | None
    action: str
    model_id: str
    previous_model_version: str | None
    active_model_version: str
    activated_at: str


class ModelArtifactRegistry:
    """SQLite metadata registry backed by immutable SHA-256 artifact files.

    SQLite and the artifact directory must live on durable local storage and
    be backed up together. The registry is single-host; it is not a distributed
    model-serving control plane.
    """

    def __init__(self, database: str | Path, artifact_root: str | Path) -> None:
        self.database = str(database)
        Path(self.database).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self.artifacts = FileArtifactStore(artifact_root)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS model_artifacts (
                    model_id TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    artifact_sha256 TEXT NOT NULL,
                    evaluation_sha256 TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    validation_mae REAL NOT NULL CHECK(validation_mae >= 0),
                    validation_sample_count INTEGER NOT NULL
                      CHECK(validation_sample_count > 0),
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    PRIMARY KEY(model_id, model_version)
                );
                CREATE TABLE IF NOT EXISTS active_models (
                    model_id TEXT PRIMARY KEY,
                    model_version TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(model_id, model_version)
                      REFERENCES model_artifacts(model_id, model_version)
                );
                CREATE TABLE IF NOT EXISTS model_activation_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_id TEXT NOT NULL,
                    action TEXT NOT NULL CHECK(action IN ('activate', 'rollback')),
                    previous_model_version TEXT,
                    active_model_version TEXT NOT NULL,
                    activated_at TEXT NOT NULL,
                    FOREIGN KEY(model_id, active_model_version)
                      REFERENCES model_artifacts(model_id, model_version)
                );
                CREATE TRIGGER IF NOT EXISTS model_artifacts_immutable_update
                BEFORE UPDATE ON model_artifacts
                BEGIN
                    SELECT RAISE(ABORT, 'model artifacts are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS model_artifacts_immutable_delete
                BEFORE DELETE ON model_artifacts
                BEGIN
                    SELECT RAISE(ABORT, 'model artifacts are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS model_activation_events_immutable_update
                BEFORE UPDATE ON model_activation_events
                BEGIN
                    SELECT RAISE(ABORT, 'model activation events are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS model_activation_events_immutable_delete
                BEFORE DELETE ON model_activation_events
                BEGIN
                    SELECT RAISE(ABORT, 'model activation events are immutable');
                END;
                """
            )

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database, timeout=15.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _json(value: dict[str, Any]) -> str:
        try:
            return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata must be finite JSON data") from exc

    @staticmethod
    def _required(value: str, name: str) -> str:
        if not value.strip():
            raise ValueError(f"{name} must not be blank")
        return value.strip()

    def register_artifact(
        self,
        model_id: str,
        model_version: str,
        payload: bytes,
        *,
        evaluation_report: bytes,
        media_type: str,
        validation_mae: float,
        validation_sample_count: int,
        metadata: dict[str, Any] | None = None,
    ) -> ModelArtifactRecord:
        """Register an immutable artifact with out-of-sample evaluation evidence.

        Re-registering an identical version is idempotent. Reusing a version
        with different bytes, evidence, or metadata is rejected.
        """
        identifier = self._required(model_id, "model_id")
        version = self._required(model_version, "model_version")
        content_type = self._required(media_type, "media_type")
        if not payload:
            raise ValueError("payload must contain non-empty bytes")
        if not evaluation_report:
            raise ValueError("evaluation_report must contain non-empty bytes")
        if (
            isinstance(validation_mae, bool)
            or not math.isfinite(validation_mae)
            or validation_mae < 0
        ):
            raise ValueError("validation_mae must be finite and non-negative")
        if type(validation_sample_count) is not int or validation_sample_count < 1:
            raise ValueError("validation_sample_count must be a positive integer")
        metadata_json = self._json(metadata or {})

        # Files are immutable and content-addressed. A failed DB insert can leave
        # an unreferenced blob, but can never publish a partial registry record.
        stored = self.artifacts.put(payload)
        evaluation = self.artifacts.put(evaluation_report)
        created_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO model_artifacts (
                    model_id, model_version, artifact_sha256, evaluation_sha256,
                    media_type, validation_mae, validation_sample_count,
                    created_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(model_id, model_version) DO NOTHING
                """,
                (
                    identifier,
                    version,
                    stored.sha256,
                    evaluation.sha256,
                    content_type,
                    float(validation_mae),
                    validation_sample_count,
                    created_at,
                    metadata_json,
                ),
            )
            row = connection.execute(
                "SELECT * FROM model_artifacts WHERE model_id=? AND model_version=?",
                (identifier, version),
            ).fetchone()
        assert row is not None
        requested = (
            stored.sha256,
            evaluation.sha256,
            content_type,
            float(validation_mae),
            validation_sample_count,
            metadata_json,
        )
        existing = (
            str(row["artifact_sha256"]),
            str(row["evaluation_sha256"]),
            str(row["media_type"]),
            float(row["validation_mae"]),
            int(row["validation_sample_count"]),
            str(row["metadata_json"]),
        )
        if existing != requested:
            raise ValueError(
                "model version is already registered with different content or evidence"
            )
        return self._record(row)

    def get_artifact(self, model_id: str, model_version: str) -> ModelArtifactRecord:
        """Return immutable metadata for a registered model version."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM model_artifacts WHERE model_id=? AND model_version=?",
                (
                    self._required(model_id, "model_id"),
                    self._required(model_version, "model_version"),
                ),
            ).fetchone()
        if row is None:
            raise KeyError("model artifact not found")
        return self._record(row)

    def list_artifacts(self, model_id: str) -> tuple[ModelArtifactRecord, ...]:
        """List registered versions in creation order."""
        identifier = self._required(model_id, "model_id")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM model_artifacts WHERE model_id=? ORDER BY created_at, model_version",
                (identifier,),
            ).fetchall()
        return tuple(self._record(row) for row in rows)

    def read_artifact(self, model_id: str, model_version: str) -> bytes:
        """Read model bytes only after verifying their SHA-256 digest."""
        record = self.get_artifact(model_id, model_version)
        return self.artifacts.get(record.artifact_sha256)

    def read_evaluation_report(self, model_id: str, model_version: str) -> bytes:
        """Read the immutable evaluation evidence after digest verification."""
        record = self.get_artifact(model_id, model_version)
        return self.artifacts.get(record.evaluation_sha256)

    def get_active(self, model_id: str) -> ModelArtifactRecord | None:
        """Return the active version, or None when no version has been activated."""
        identifier = self._required(model_id, "model_id")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT model_version FROM active_models WHERE model_id=?", (identifier,)
            ).fetchone()
        return None if row is None else self.get_artifact(identifier, str(row["model_version"]))

    def activate(
        self,
        model_id: str,
        model_version: str,
        *,
        expected_active_version: str | None,
    ) -> ModelActivation:
        """Explicitly activate a registered version using compare-and-swap fencing."""
        return self._set_active(
            model_id,
            model_version,
            expected_active_version=expected_active_version,
            action="activate",
        )

    def rollback(
        self,
        model_id: str,
        target_version: str,
        *,
        expected_active_version: str,
    ) -> ModelActivation:
        """Explicitly roll back to a chosen registered version.

        The caller must name the target and the version it expects to replace;
        the registry never guesses which historical version should be restored.
        """
        return self._set_active(
            model_id,
            target_version,
            expected_active_version=expected_active_version,
            action="rollback",
        )

    def _set_active(
        self,
        model_id: str,
        model_version: str,
        *,
        expected_active_version: str | None,
        action: str,
    ) -> ModelActivation:
        identifier = self._required(model_id, "model_id")
        version = self._required(model_version, "model_version")
        if expected_active_version is not None:
            self._required(expected_active_version, "expected_active_version")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            candidate = connection.execute(
                "SELECT 1 FROM model_artifacts WHERE model_id=? AND model_version=?",
                (identifier, version),
            ).fetchone()
            if candidate is None:
                raise KeyError("model artifact not found")
            current = connection.execute(
                "SELECT model_version FROM active_models WHERE model_id=?", (identifier,)
            ).fetchone()
            current_version = None if current is None else str(current["model_version"])
            if current_version != expected_active_version:
                raise ValueError("active model version changed; activation was not applied")
            if current_version == version:
                return ModelActivation(
                    event_id=None,
                    action="unchanged",
                    model_id=identifier,
                    previous_model_version=current_version,
                    active_model_version=version,
                    activated_at=datetime.now(UTC).isoformat(),
                )
            activated_at = datetime.now(UTC).isoformat()
            connection.execute(
                """
                INSERT INTO active_models(model_id, model_version, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(model_id) DO UPDATE SET
                  model_version=excluded.model_version, updated_at=excluded.updated_at
                """,
                (identifier, version, activated_at),
            )
            cursor = connection.execute(
                """
                INSERT INTO model_activation_events (
                    model_id, action, previous_model_version,
                    active_model_version, activated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (identifier, action, current_version, version, activated_at),
            )
            event_id = cursor.lastrowid
            if event_id is None:
                raise RuntimeError("activation event was not persisted")
            return ModelActivation(
                event_id=event_id,
                action=action,
                model_id=identifier,
                previous_model_version=current_version,
                active_model_version=version,
                activated_at=activated_at,
            )

    def activation_history(self, model_id: str) -> tuple[ModelActivation, ...]:
        """Return append-only activation and rollback history."""
        identifier = self._required(model_id, "model_id")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM model_activation_events
                WHERE model_id=? ORDER BY event_id
                """,
                (identifier,),
            ).fetchall()
        return tuple(
            ModelActivation(
                event_id=int(row["event_id"]),
                action=str(row["action"]),
                model_id=str(row["model_id"]),
                previous_model_version=(
                    None
                    if row["previous_model_version"] is None
                    else str(row["previous_model_version"])
                ),
                active_model_version=str(row["active_model_version"]),
                activated_at=str(row["activated_at"]),
            )
            for row in rows
        )

    @staticmethod
    def _record(row: sqlite3.Row) -> ModelArtifactRecord:
        return ModelArtifactRecord(
            model_id=str(row["model_id"]),
            model_version=str(row["model_version"]),
            artifact_sha256=str(row["artifact_sha256"]),
            evaluation_sha256=str(row["evaluation_sha256"]),
            media_type=str(row["media_type"]),
            validation_mae=float(row["validation_mae"]),
            validation_sample_count=int(row["validation_sample_count"]),
            created_at=str(row["created_at"]),
            metadata=json.loads(str(row["metadata_json"])),
        )
