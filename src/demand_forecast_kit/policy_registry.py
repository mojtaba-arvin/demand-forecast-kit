"""Immutable, tenant-scoped replenishment policy versions and activation history."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ReplenishmentPolicyRecord:
    """Immutable validated policy definition."""

    tenant_id: str
    policy_id: str
    policy_version: str
    definition_sha256: str
    created_at: str
    definition: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PolicyActivation:
    """Result of an explicit policy activation or rollback."""

    event_id: int | None
    action: str
    tenant_id: str
    policy_id: str
    previous_policy_version: str | None
    active_policy_version: str
    activated_at: str


class ReplenishmentPolicyRegistry:
    """Single-host SQLite registry for immutable policy versions and active pointers."""

    def __init__(self, database: str | Path) -> None:
        self.database = str(database)
        Path(self.database).expanduser().parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS replenishment_policy_versions (
                    tenant_id TEXT NOT NULL,
                    policy_id TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    definition_sha256 TEXT NOT NULL,
                    definition_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(tenant_id, policy_id, policy_version)
                );
                CREATE TABLE IF NOT EXISTS active_replenishment_policies (
                    tenant_id TEXT NOT NULL,
                    policy_id TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(tenant_id, policy_id),
                    FOREIGN KEY(tenant_id, policy_id, policy_version)
                      REFERENCES replenishment_policy_versions(
                        tenant_id, policy_id, policy_version
                      )
                );
                CREATE TABLE IF NOT EXISTS replenishment_policy_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL,
                    policy_id TEXT NOT NULL,
                    action TEXT NOT NULL CHECK(action IN ('activate', 'rollback')),
                    previous_policy_version TEXT,
                    active_policy_version TEXT NOT NULL,
                    activated_at TEXT NOT NULL,
                    FOREIGN KEY(tenant_id, policy_id, active_policy_version)
                      REFERENCES replenishment_policy_versions(
                        tenant_id, policy_id, policy_version
                      )
                );
                CREATE TRIGGER IF NOT EXISTS policy_versions_immutable_update
                BEFORE UPDATE ON replenishment_policy_versions
                BEGIN
                    SELECT RAISE(ABORT, 'replenishment policy versions are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS policy_versions_immutable_delete
                BEFORE DELETE ON replenishment_policy_versions
                BEGIN
                    SELECT RAISE(ABORT, 'replenishment policy versions are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS policy_events_immutable_update
                BEFORE UPDATE ON replenishment_policy_events
                BEGIN
                    SELECT RAISE(ABORT, 'replenishment policy events are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS policy_events_immutable_delete
                BEFORE DELETE ON replenishment_policy_events
                BEGIN
                    SELECT RAISE(ABORT, 'replenishment policy events are immutable');
                END;
                """
            )

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection]:
        db = sqlite3.connect(self.database, timeout=15.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 15000")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _required(value: str, field: str) -> str:
        if not value.strip():
            raise ValueError(f"{field} must not be blank")
        return value.strip()

    @staticmethod
    def _encode_definition(definition: dict[str, Any]) -> str:
        allowed = {
            "policy_type",
            "underage_cost",
            "overage_cost",
            "pack_size",
            "description",
            "metadata",
        }
        if not isinstance(definition, dict) or set(definition) - allowed:
            raise ValueError("policy definition must be an object with supported fields")
        if definition.get("policy_type") != "newsvendor":
            raise ValueError("policy_type must be 'newsvendor'")
        for field in ("underage_cost", "overage_cost"):
            value = definition.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{field} must be a finite positive number")
            if not math.isfinite(float(value)) or float(value) <= 0:
                raise ValueError(f"{field} must be a finite positive number")
        pack_size = definition.get("pack_size", 1)
        if type(pack_size) is not int or pack_size < 1:
            raise ValueError("pack_size must be a positive integer")
        description = definition.get("description")
        if description is not None and (
            not isinstance(description, str) or not description.strip()
        ):
            raise ValueError("description must be a non-blank string when provided")
        if not isinstance(definition.get("metadata", {}), dict):
            raise ValueError("metadata must be a JSON object")
        normalized = {**definition, "pack_size": pack_size}
        try:
            return json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("policy definition must contain finite JSON data") from exc

    def register_policy(
        self,
        tenant_id: str,
        policy_id: str,
        policy_version: str,
        definition: dict[str, Any],
    ) -> ReplenishmentPolicyRecord:
        tenant = self._required(tenant_id, "tenant_id")
        identifier = self._required(policy_id, "policy_id")
        version = self._required(policy_version, "policy_version")
        encoded = self._encode_definition(definition)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        created_at = datetime.now(UTC).isoformat()
        with self._connect() as db:
            db.execute(
                """INSERT INTO replenishment_policy_versions VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(tenant_id, policy_id, policy_version) DO NOTHING""",
                (tenant, identifier, version, digest, encoded, created_at),
            )
            row = db.execute(
                """SELECT * FROM replenishment_policy_versions
                   WHERE tenant_id=? AND policy_id=? AND policy_version=?""",
                (tenant, identifier, version),
            ).fetchone()
        assert row is not None
        if str(row["definition_sha256"]) != digest or str(row["definition_json"]) != encoded:
            raise ValueError("policy version is already registered with a different definition")
        return self._record(row)

    def get_policy(
        self, tenant_id: str, policy_id: str, policy_version: str
    ) -> ReplenishmentPolicyRecord:
        with self._connect() as db:
            row = db.execute(
                """SELECT * FROM replenishment_policy_versions
                   WHERE tenant_id=? AND policy_id=? AND policy_version=?""",
                (
                    self._required(tenant_id, "tenant_id"),
                    self._required(policy_id, "policy_id"),
                    self._required(policy_version, "policy_version"),
                ),
            ).fetchone()
        if row is None:
            raise KeyError("replenishment policy version not found")
        return self._record(row)

    def list_policies(
        self, tenant_id: str, policy_id: str
    ) -> tuple[ReplenishmentPolicyRecord, ...]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT * FROM replenishment_policy_versions
                   WHERE tenant_id=? AND policy_id=? ORDER BY created_at, policy_version""",
                (self._required(tenant_id, "tenant_id"), self._required(policy_id, "policy_id")),
            ).fetchall()
        return tuple(self._record(row) for row in rows)

    def get_active(self, tenant_id: str, policy_id: str) -> ReplenishmentPolicyRecord | None:
        tenant = self._required(tenant_id, "tenant_id")
        identifier = self._required(policy_id, "policy_id")
        with self._connect() as db:
            row = db.execute(
                """SELECT policy_version FROM active_replenishment_policies
                   WHERE tenant_id=? AND policy_id=?""",
                (tenant, identifier),
            ).fetchone()
        if row is None:
            return None
        return self.get_policy(tenant, identifier, str(row["policy_version"]))

    def activate(
        self,
        tenant_id: str,
        policy_id: str,
        policy_version: str,
        *,
        expected_active_version: str | None,
    ) -> PolicyActivation:
        return self._set_active(
            tenant_id,
            policy_id,
            policy_version,
            expected_active_version=expected_active_version,
            action="activate",
        )

    def rollback(
        self,
        tenant_id: str,
        policy_id: str,
        target_version: str,
        *,
        expected_active_version: str,
    ) -> PolicyActivation:
        return self._set_active(
            tenant_id,
            policy_id,
            target_version,
            expected_active_version=expected_active_version,
            action="rollback",
        )

    def _set_active(
        self,
        tenant_id: str,
        policy_id: str,
        policy_version: str,
        *,
        expected_active_version: str | None,
        action: str,
    ) -> PolicyActivation:
        tenant = self._required(tenant_id, "tenant_id")
        identifier = self._required(policy_id, "policy_id")
        version = self._required(policy_version, "policy_version")
        if expected_active_version is not None:
            self._required(expected_active_version, "expected_active_version")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            exists = db.execute(
                """SELECT 1 FROM replenishment_policy_versions
                   WHERE tenant_id=? AND policy_id=? AND policy_version=?""",
                (tenant, identifier, version),
            ).fetchone()
            if exists is None:
                raise KeyError("replenishment policy version not found")
            current = db.execute(
                """SELECT policy_version FROM active_replenishment_policies
                   WHERE tenant_id=? AND policy_id=?""",
                (tenant, identifier),
            ).fetchone()
            current_version = None if current is None else str(current["policy_version"])
            if current_version != expected_active_version:
                raise ValueError("active policy version changed; activation was not applied")
            if current_version == version:
                return PolicyActivation(
                    None,
                    "unchanged",
                    tenant,
                    identifier,
                    current_version,
                    version,
                    datetime.now(UTC).isoformat(),
                )
            activated_at = datetime.now(UTC).isoformat()
            db.execute(
                """INSERT INTO active_replenishment_policies VALUES (?, ?, ?, ?)
                   ON CONFLICT(tenant_id, policy_id) DO UPDATE SET
                     policy_version=excluded.policy_version, updated_at=excluded.updated_at""",
                (tenant, identifier, version, activated_at),
            )
            cursor = db.execute(
                """INSERT INTO replenishment_policy_events
                   (tenant_id, policy_id, action, previous_policy_version,
                    active_policy_version, activated_at) VALUES (?, ?, ?, ?, ?, ?)""",
                (tenant, identifier, action, current_version, version, activated_at),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("policy activation event was not persisted")
            return PolicyActivation(
                int(cursor.lastrowid),
                action,
                tenant,
                identifier,
                current_version,
                version,
                activated_at,
            )

    def activation_history(self, tenant_id: str, policy_id: str) -> tuple[PolicyActivation, ...]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT * FROM replenishment_policy_events
                   WHERE tenant_id=? AND policy_id=? ORDER BY event_id""",
                (self._required(tenant_id, "tenant_id"), self._required(policy_id, "policy_id")),
            ).fetchall()
        return tuple(
            PolicyActivation(
                int(row["event_id"]),
                str(row["action"]),
                str(row["tenant_id"]),
                str(row["policy_id"]),
                None
                if row["previous_policy_version"] is None
                else str(row["previous_policy_version"]),
                str(row["active_policy_version"]),
                str(row["activated_at"]),
            )
            for row in rows
        )

    @staticmethod
    def _record(row: sqlite3.Row) -> ReplenishmentPolicyRecord:
        return ReplenishmentPolicyRecord(
            str(row["tenant_id"]),
            str(row["policy_id"]),
            str(row["policy_version"]),
            str(row["definition_sha256"]),
            str(row["created_at"]),
            json.loads(str(row["definition_json"])),
        )
