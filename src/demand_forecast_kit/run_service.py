"""Shared orchestration for persisted runs, immutable decisions, and telemetry."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from demand_forecast_kit.artifacts import FileArtifactStore
from demand_forecast_kit.observability import InMemoryMetrics, JsonLogFormatter, MetricsSnapshot
from demand_forecast_kit.registry import SQLiteRunRegistry


@dataclass(frozen=True, slots=True)
class RunArtifact:
    """Stable run and content-addressed artifact reference returned to callers."""

    run_id: int
    status: str
    artifact_sha256: str
    artifact_size_bytes: int

    def to_dict(self) -> dict[str, int | str]:
        """Return a JSON-compatible metadata mapping."""
        return asdict(self)


class RunService:
    """Connect API/CLI operations to the SQLite registry and SHA-256 artifact store."""

    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir).expanduser()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.registry = SQLiteRunRegistry(self.state_dir / "runs.sqlite")
        self.artifacts = FileArtifactStore(self.state_dir / "artifacts")
        self.metrics = InMemoryMetrics()
        self.logger = logging.getLogger("demand_forecast_kit.runs")
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(JsonLogFormatter())
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
            self.logger.propagate = False

    @classmethod
    def from_environment(cls) -> RunService:
        """Create a service using the caller-configurable persistent state directory."""
        return cls(os.environ.get("DEMAND_FORECAST_STATE_DIR", ".demand-forecast-kit"))

    @staticmethod
    def fingerprint(payload: bytes) -> str:
        """Return the canonical lowercase SHA-256 digest for input bytes."""
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def idempotency_key(
        *,
        dataset_fingerprint: str,
        model_id: str,
        model_version: str,
        config: dict[str, Any],
    ) -> str:
        """Derive a stable run key from dataset, model, version, and configuration."""
        identity = json.dumps(
            {
                "dataset_fingerprint": dataset_fingerprint,
                "model_id": model_id,
                "model_version": model_version,
                "config": config,
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(identity).hexdigest()

    def record_run(
        self,
        *,
        idempotency_key: str,
        dataset_fingerprint: str,
        model_id: str,
        model_version: str,
        config: dict[str, Any],
        result: dict[str, Any],
        artifact_payload: bytes,
    ) -> RunArtifact:
        """Persist a reproducible run and verify its immutable artifact before completion."""
        run = self.registry.create_run(
            idempotency_key=idempotency_key,
            dataset_fingerprint=dataset_fingerprint,
            model_id=model_id,
            model_version=model_version,
            config=config,
        )
        try:
            artifact = self.artifacts.put(artifact_payload)
            if self.artifacts.get(artifact.sha256) != artifact_payload:
                raise OSError("artifact store retrieval did not match the submitted payload")
            persisted_result = {
                **result,
                "artifact_sha256": artifact.sha256,
                "artifact_size_bytes": artifact.size_bytes,
            }
            completed = self.registry.complete_run(run.run_id, persisted_result)
        except Exception as exc:
            if run.status == "created":
                self.registry.fail_run(run.run_id, f"{type(exc).__name__}: {exc}")
            self.metrics.increment("runs.failed")
            self.logger.exception(
                "run.failed",
                extra={"run_id": run.run_id, "model_id": model_id},
            )
            raise

        self.metrics.increment("runs.completed")
        self.metrics.observe("run.artifact_bytes", float(artifact.size_bytes))
        self.logger.info(
            "run.completed",
            extra={
                "run_id": completed.run_id,
                "model_id": model_id,
                "model_version": model_version,
                "dataset_fingerprint": dataset_fingerprint,
                "artifact_sha256": artifact.sha256,
                "artifact_size_bytes": artifact.size_bytes,
            },
        )
        return RunArtifact(
            run_id=completed.run_id,
            status=completed.status,
            artifact_sha256=artifact.sha256,
            artifact_size_bytes=artifact.size_bytes,
        )

    def record_inventory_decision(
        self,
        run_id: int,
        *,
        decision_key: str,
        decision: dict[str, Any],
    ) -> dict[str, int | str]:
        """Persist an immutable inventory decision and emit structured telemetry."""
        stored = self.registry.record_inventory_decision(
            run_id,
            decision_key=decision_key,
            decision=decision,
        )
        self.metrics.increment("inventory_decisions.recorded")
        self.logger.info(
            "inventory_decision.recorded",
            extra={
                "run_id": stored.run_id,
                "decision_id": stored.decision_id,
                "decision_key": stored.decision_key,
            },
        )
        return {
            "decision_id": stored.decision_id,
            "run_id": stored.run_id,
            "decision_key": stored.decision_key,
        }

    def metrics_snapshot(self) -> MetricsSnapshot:
        """Return a detached snapshot suitable for an authenticated metrics endpoint."""
        return self.metrics.snapshot()
