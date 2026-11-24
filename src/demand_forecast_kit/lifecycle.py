"""Drift response, evidence-based model selection, and pluggable retraining workers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from demand_forecast_kit.operations import OperationalStore


@dataclass(frozen=True, slots=True)
class TrainingResult:
    """Metadata produced by a model-specific training/evaluation implementation."""

    model_version: str
    baseline_mae: float
    sample_count: int


Trainer = Callable[[dict[str, Any], Sequence[float]], TrainingResult]


class ModelLifecycle:
    """Coordinate monitoring and retraining without coupling to a model backend.

    Model adapters in this project have different fitting semantics. A trainer
    must therefore be explicitly registered per model_id; the coordinator never
    pretends that a queued request trained a model when no trainer is available.
    """

    def __init__(
        self, store: OperationalStore, *, trainers: dict[str, Trainer] | None = None
    ) -> None:
        self.store = store
        self.trainers = dict(trainers or {})

    def register_trainer(self, model_id: str, trainer: Trainer) -> None:
        if not model_id.strip():
            raise ValueError("model_id must not be blank")
        self.trainers[model_id] = trainer

    def assess(
        self,
        tenant_id: str,
        *,
        warehouse_id: str,
        sku_id: str,
        model_id: str,
        model_version: str,
        window: int = 30,
        min_samples: int = 10,
        degradation_ratio: float = 1.5,
    ) -> dict[str, Any]:
        health = self.store.model_health(
            tenant_id,
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            model_id=model_id,
            model_version=model_version,
            window=window,
            min_samples=min_samples,
            degradation_ratio=degradation_ratio,
        )
        if health["alert"]:
            health["retraining_request"] = self.store.queue_retraining(
                tenant_id,
                warehouse_id=warehouse_id,
                sku_id=sku_id,
                model_id=model_id,
                model_version=model_version,
                reason="rolling_mae_degradation",
            )
        return health

    def select(
        self,
        tenant_id: str,
        *,
        warehouse_id: str,
        sku_id: str,
        min_samples: int = 5,
        window: int = 100,
        fallback_model_id: str = "seasonal-naive",
    ) -> dict[str, Any]:
        candidates = self.store.rank_models(
            tenant_id,
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            min_samples=min_samples,
            window=window,
        )
        if candidates:
            return {"selected": candidates[0], "candidates": candidates, "used_fallback": False}
        return {
            "selected": {
                "model_id": fallback_model_id,
                "model_version": None,
                "mae": None,
                "sample_count": 0,
            },
            "candidates": [],
            "used_fallback": True,
            "reason": "insufficient_out_of_sample_evidence",
        }

    def process_retraining_request(self, tenant_id: str, request_id: str) -> dict[str, Any]:
        """Claim and execute one queued retraining request using its registered trainer."""
        requests = self.store.list_retraining_requests(tenant_id, limit=1000)
        request = next((item for item in requests if item["request_id"] == request_id), None)
        if request is None:
            raise KeyError("retraining request not found")
        trainer = self.trainers.get(str(request["model_id"]))
        if trainer is None:
            return {
                "status": "trainer_unavailable",
                "request_id": request_id,
                "model_id": request["model_id"],
            }
        claimed = self.store.claim_retraining(tenant_id, request_id)
        history_rows = self.store.demand_history(
            tenant_id, str(request["warehouse_id"]), str(request["sku_id"]), limit=100_000
        )
        history = tuple(float(row["demand"]) for row in history_rows)
        if not history:
            self.store.finish_retraining(tenant_id, request_id, success=False)
            raise ValueError("cannot retrain without demand history")
        try:
            result = trainer(claimed, history)
            if not result.model_version.strip():
                raise ValueError("trainer returned a blank model version")
            if result.model_version == request["model_version"]:
                raise ValueError("retraining must return a new model version")
            if result.sample_count < 1:
                raise ValueError("trainer must provide at least one validation sample")
            self.store.set_model_baseline(
                tenant_id,
                warehouse_id=str(request["warehouse_id"]),
                sku_id=str(request["sku_id"]),
                model_id=str(request["model_id"]),
                model_version=result.model_version,
                baseline_mae=result.baseline_mae,
                sample_count=result.sample_count,
            )
        except Exception:
            self.store.finish_retraining(tenant_id, request_id, success=False)
            raise
        finished = self.store.finish_retraining(tenant_id, request_id, success=True)
        return {
            "status": finished["status"],
            "request_id": request_id,
            "model_id": request["model_id"],
            "previous_model_version": request["model_version"],
            "new_model_version": result.model_version,
            "baseline_mae": result.baseline_mae,
            "validation_sample_count": result.sample_count,
        }
