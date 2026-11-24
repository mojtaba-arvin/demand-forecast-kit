"""Leakage-aware per-series model selection from historical backtest evidence."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from math import isfinite
from pathlib import Path
from typing import Literal

from demand_forecast_kit.backtesting import ArtifactMetadata, BacktestReport, FoldEvaluation
from demand_forecast_kit.models.base import ForecastAdapter

RoutingMetric = Literal["wql", "mase", "mean_pinball_loss"]


@dataclass(frozen=True, slots=True)
class CandidateScore:
    """A candidate's comparable score and number of historical validation folds."""

    model_id: str
    model_version: str
    score: float
    fold_count: int


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Auditable model choice for one series at one forecast origin."""

    series_id: str
    forecast_origin: str
    history_end_timestamp: str
    dataset_fingerprint: str
    metric: RoutingMetric
    chosen_model_id: str
    chosen_model_version: str
    score: float | None
    evidence_fold_count: int
    used_fallback: bool
    candidate_scores: tuple[CandidateScore, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation with deterministic candidates."""
        return {
            "series_id": self.series_id,
            "forecast_origin": self.forecast_origin,
            "history_end_timestamp": self.history_end_timestamp,
            "dataset_fingerprint": self.dataset_fingerprint,
            "metric": self.metric,
            "chosen_model_id": self.chosen_model_id,
            "chosen_model_version": self.chosen_model_version,
            "score": self.score,
            "evidence_fold_count": self.evidence_fold_count,
            "used_fallback": self.used_fallback,
            "candidate_scores": [
                {
                    "model_id": item.model_id,
                    "model_version": item.model_version,
                    "score": item.score,
                    "fold_count": item.fold_count,
                }
                for item in self.candidate_scores
            ],
        }


def _parse_timestamp(value: date | datetime | str, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if value.strip():
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a valid ISO-8601 date or timestamp") from exc
    raise ValueError(f"{field_name} must be a date, datetime, or non-blank ISO-8601 string")


def _metric_value(record: FoldEvaluation, metric: RoutingMetric) -> float | None:
    if metric == "wql":
        value = record.wql
    elif metric == "mase":
        value = record.mase
    else:
        pinball = tuple(record.pinball_losses.values())
        value = sum(pinball) / len(pinball) if pinball else None
    if value is None:
        return None
    numeric = float(value)
    if not isfinite(numeric):
        raise ValueError(f"backtest metric {metric!r} must be finite when defined")
    return numeric


class ModelRouter:
    """Choose a model independently for each SKU using only past validation folds.

    A report is eligible only when the target series' complete observed history
    ends strictly before the requested forecast origin. Candidate scores are
    averaged over the target series' rolling-origin folds. Undefined scores and
    candidates with too few folds are excluded.
    """

    metric: RoutingMetric

    def __init__(
        self,
        adapters: Sequence[ForecastAdapter],
        *,
        metric: RoutingMetric = "wql",
        min_folds: int = 2,
        fallback_model_id: str = "seasonal-naive",
        tie_tolerance: float = 1e-12,
    ) -> None:
        if metric not in {"wql", "mase", "mean_pinball_loss"}:
            raise ValueError("metric must be 'wql', 'mase', or 'mean_pinball_loss'")
        if type(min_folds) is not int or min_folds < 1:
            raise ValueError("min_folds must be a positive integer")
        if not isfinite(tie_tolerance) or tie_tolerance < 0.0:
            raise ValueError("tie_tolerance must be finite and non-negative")
        if not fallback_model_id.strip():
            raise ValueError("fallback_model_id must not be blank")
        if not adapters:
            raise ValueError("at least one forecasting adapter is required")

        registry: dict[str, ForecastAdapter] = {}
        for adapter in adapters:
            model_id = adapter.model_id.strip()
            model_version = adapter.model_version.strip()
            if not model_id or not model_version:
                raise ValueError("every adapter must provide non-blank model_id and model_version")
            if model_id in registry:
                raise ValueError(f"duplicate model_id: {model_id}")
            registry[model_id] = adapter

        if fallback_model_id not in registry:
            raise ValueError(
                f"fallback model {fallback_model_id!r} must be present in the adapter registry"
            )

        self._adapters = registry
        self.metric = metric
        self.min_folds = min_folds
        self.fallback_model_id = fallback_model_id
        self.tie_tolerance = float(tie_tolerance)

    def select(
        self,
        report: BacktestReport,
        *,
        series_id: str,
        forecast_origin: date | datetime | str,
    ) -> RoutingDecision:
        """Select a registered adapter for a series at a future forecast origin."""
        if not series_id.strip():
            raise ValueError("series_id must not be blank")
        if series_id not in report.series_history_ranges:
            raise ValueError(f"series_id {series_id!r} is not present in the backtest report")

        origin = _parse_timestamp(forecast_origin, "forecast_origin")
        history_start_text, history_end_text = report.series_history_ranges[series_id]
        history_start = _parse_timestamp(history_start_text, "history_start_timestamp")
        history_end = _parse_timestamp(history_end_text, "history_end_timestamp")
        try:
            if history_start > history_end:
                raise ValueError("backtest report has an invalid series history range")
            if history_end >= origin:
                raise ValueError(
                    "backtest history must end strictly before forecast_origin; "
                    "rebuild the report using data available at that origin"
                )
        except TypeError as exc:
            raise ValueError(
                "forecast_origin and report timestamps must use compatible timezone semantics"
            ) from exc

        records_by_model: dict[str, list[FoldEvaluation]] = defaultdict(list)
        for record in report.evaluations:
            if record.series_id != series_id:
                continue
            fold_end = _parse_timestamp(record.test_end_timestamp, "test_end_timestamp")
            try:
                if fold_end > history_end:
                    raise ValueError(
                        "backtest evaluation extends beyond the declared series history range"
                    )
                if fold_end >= origin:
                    continue
            except TypeError as exc:
                raise ValueError(
                    "forecast_origin and evaluation timestamps must use compatible "
                    "timezone semantics"
                ) from exc
            records_by_model[record.model_id].append(record)

        for model_id, records in records_by_model.items():
            fold_numbers = tuple(record.fold for record in records)
            if len(set(fold_numbers)) != len(fold_numbers):
                raise ValueError(
                    f"backtest evidence for model {model_id!r} contains duplicate fold numbers"
                )

        scores: list[CandidateScore] = []
        for model_id, adapter in self._adapters.items():
            records = records_by_model.get(model_id, [])
            if not records:
                continue
            versions = {record.model_version for record in records}
            if len(versions) != 1:
                raise ValueError(f"backtest evidence for model {model_id!r} mixes model versions")
            evidence_version = next(iter(versions))
            if evidence_version != adapter.model_version:
                raise ValueError(
                    f"backtest model version for {model_id!r} is {evidence_version!r}, "
                    f"but the registered adapter is {adapter.model_version!r}"
                )

            values = tuple(
                value
                for record in records
                if (value := _metric_value(record, self.metric)) is not None
            )
            if len(values) < self.min_folds:
                continue
            scores.append(
                CandidateScore(
                    model_id=model_id,
                    model_version=evidence_version,
                    score=sum(values) / len(values),
                    fold_count=len(values),
                )
            )

        scores.sort(key=lambda item: (item.score, item.model_id))
        eligible = tuple(scores)
        if eligible:
            best_score = eligible[0].score
            tied = tuple(item for item in eligible if item.score <= best_score + self.tie_tolerance)
            chosen = min(
                tied,
                key=lambda item: (item.model_id != self.fallback_model_id, item.model_id),
            )
            chosen_model_id = chosen.model_id
            chosen_model_version = chosen.model_version
            chosen_score: float | None = chosen.score
            evidence_fold_count = chosen.fold_count
            used_fallback = False
        else:
            fallback = self._adapters[self.fallback_model_id]
            chosen_model_id = fallback.model_id
            chosen_model_version = fallback.model_version
            chosen_score = None
            evidence_fold_count = 0
            used_fallback = True

        return RoutingDecision(
            series_id=series_id,
            forecast_origin=origin.isoformat(),
            history_end_timestamp=history_end.isoformat(),
            dataset_fingerprint=report.dataset_fingerprint,
            metric=self.metric,
            chosen_model_id=chosen_model_id,
            chosen_model_version=chosen_model_version,
            score=chosen_score,
            evidence_fold_count=evidence_fold_count,
            used_fallback=used_fallback,
            candidate_scores=eligible,
        )


def write_routing_artifact(
    decisions: Sequence[RoutingDecision],
    path: str | Path,
) -> ArtifactMetadata:
    """Write a deterministic JSON artifact containing per-series routing decisions."""
    if not decisions:
        raise ValueError("at least one routing decision is required")
    ordered = tuple(sorted(decisions, key=lambda item: item.series_id))
    series_ids = tuple(item.series_id for item in ordered)
    if len(set(series_ids)) != len(series_ids):
        raise ValueError("routing decisions must contain unique series_id values")
    fingerprints = {item.dataset_fingerprint for item in ordered}
    if len(fingerprints) != 1:
        raise ValueError("all routing decisions must originate from the same dataset")
    payload = (
        json.dumps(
            {
                "schema_version": 1,
                "dataset_fingerprint": next(iter(fingerprints)),
                "decisions": [item.to_dict() for item in ordered],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        temporary.write_bytes(payload)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return ArtifactMetadata(
        path=str(destination),
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )
