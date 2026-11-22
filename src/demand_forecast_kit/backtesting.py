"""Rolling-origin evaluation for probabilistic demand-forecast adapters."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from math import isclose, isfinite
from pathlib import Path

import polars as pl

from demand_forecast_kit.data import validate_history
from demand_forecast_kit.metrics import (
    interval_coverage,
    mean_absolute_scaled_error,
    pinball_loss,
    weighted_quantile_loss,
)
from demand_forecast_kit.models.base import ForecastAdapter

DEFAULT_QUANTILE_LEVELS = (0.05, 0.1, 0.5, 0.9, 0.95)
DEFAULT_COVERAGE_LEVELS = (0.8, 0.9)


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """Reproducible rolling-origin split and metric configuration."""

    initial_train_size: int
    horizon: int
    step: int = 1
    season_length: int = 7
    max_train_size: int | None = None
    quantile_levels: tuple[float, ...] = DEFAULT_QUANTILE_LEVELS
    coverage_levels: tuple[float, ...] = DEFAULT_COVERAGE_LEVELS
    seed: int = 42

    def __post_init__(self) -> None:
        integer_fields = (
            ("initial_train_size", self.initial_train_size),
            ("horizon", self.horizon),
            ("step", self.step),
            ("season_length", self.season_length),
            ("seed", self.seed),
        )
        for name, value in integer_fields:
            minimum = 0 if name == "seed" else 1
            if type(value) is not int or value < minimum:
                qualifier = "non-negative" if name == "seed" else "positive"
                raise ValueError(f"{name} must be a {qualifier} integer")
        if self.max_train_size is not None and (
            type(self.max_train_size) is not int or self.max_train_size < self.initial_train_size
        ):
            raise ValueError("max_train_size must be an integer >= initial_train_size")

        quantiles = tuple(float(level) for level in self.quantile_levels)
        if not quantiles or any(
            not isfinite(level) or not 0.0 < level < 1.0 for level in quantiles
        ):
            raise ValueError("quantile_levels must be finite values strictly between 0 and 1")
        if tuple(sorted(set(quantiles))) != quantiles:
            raise ValueError("quantile_levels must be unique and strictly increasing")
        if 0.5 not in quantiles:
            raise ValueError("quantile_levels must include 0.5 for MASE point forecasts")

        coverage = tuple(float(level) for level in self.coverage_levels)
        if any(not isfinite(level) or not 0.0 < level < 1.0 for level in coverage):
            raise ValueError("coverage_levels must be finite values strictly between 0 and 1")
        if tuple(sorted(set(coverage))) != coverage:
            raise ValueError("coverage_levels must be unique and strictly increasing")
        for nominal in coverage:
            lower = (1.0 - nominal) / 2.0
            upper = 1.0 - lower
            if not any(isclose(level, lower, abs_tol=1e-10) for level in quantiles):
                raise ValueError(
                    f"quantile_levels must include {lower:g} for {nominal:.0%} coverage"
                )
            if not any(isclose(level, upper, abs_tol=1e-10) for level in quantiles):
                raise ValueError(
                    f"quantile_levels must include {upper:g} for {nominal:.0%} coverage"
                )

        object.__setattr__(self, "quantile_levels", quantiles)
        object.__setattr__(self, "coverage_levels", coverage)


@dataclass(frozen=True, slots=True)
class RollingOriginSplit:
    """One expanding- or sliding-window split; end positions are exclusive."""

    fold: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int


def rolling_origin_splits(
    n_observations: int,
    config: BacktestConfig,
) -> tuple[RollingOriginSplit, ...]:
    """Create deterministic chronological splits without using future observations."""
    if type(n_observations) is not int or n_observations < 1:
        raise ValueError("n_observations must be a positive integer")
    if n_observations < config.initial_train_size + config.horizon:
        raise ValueError("not enough observations for one complete backtest fold")

    splits: list[RollingOriginSplit] = []
    test_start = config.initial_train_size
    while test_start + config.horizon <= n_observations:
        train_end = test_start
        train_start = 0
        if config.max_train_size is not None:
            train_start = max(0, train_end - config.max_train_size)
        splits.append(
            RollingOriginSplit(
                fold=len(splits) + 1,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_start + config.horizon,
            )
        )
        test_start += config.step
    return tuple(splits)


@dataclass(frozen=True, slots=True)
class FoldEvaluation:
    """One model/series/forecast-origin result, including predictions and metrics."""

    model_id: str
    model_version: str
    series_id: str
    fold: int
    train_size: int
    train_end_timestamp: str
    test_start_timestamp: str
    test_end_timestamp: str
    actuals: tuple[float, ...]
    quantile_forecasts: dict[float, tuple[float, ...]]
    mase: float | None
    wql: float | None
    pinball_losses: dict[float, float]
    interval_coverages: dict[float, float]


@dataclass(frozen=True, slots=True)
class SkippedSeries:
    """A series that could not provide one complete training-plus-test window."""

    series_id: str
    observation_count: int
    required_observations: int


@dataclass(frozen=True, slots=True)
class ModelSummary:
    """Macro-averaged metrics over a model's evaluated series and folds."""

    model_id: str
    model_version: str
    series_count: int
    fold_count: int
    mean_mase: float | None
    mean_wql: float | None
    mean_pinball_loss: float
    interval_coverages: dict[float, float]


@dataclass(frozen=True, slots=True)
class BacktestReport:
    """Complete reproducible evaluation output."""

    dataset_fingerprint: str
    config: BacktestConfig
    evaluations: tuple[FoldEvaluation, ...]
    skipped_series: tuple[SkippedSeries, ...]
    model_summaries: tuple[ModelSummary, ...]
    series_history_ranges: dict[str, tuple[str, str]]
    schema_version: int = 2

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation with stable quantile keys."""
        return {
            "schema_version": self.schema_version,
            "dataset_fingerprint": self.dataset_fingerprint,
            "series_history_ranges": {
                series_id: {
                    "start_timestamp": time_range[0],
                    "end_timestamp": time_range[1],
                }
                for series_id, time_range in sorted(self.series_history_ranges.items())
            },
            "config": {
                "initial_train_size": self.config.initial_train_size,
                "horizon": self.config.horizon,
                "step": self.config.step,
                "season_length": self.config.season_length,
                "max_train_size": self.config.max_train_size,
                "quantile_levels": list(self.config.quantile_levels),
                "coverage_levels": list(self.config.coverage_levels),
                "seed": self.config.seed,
            },
            "evaluations": [
                {
                    "model_id": item.model_id,
                    "model_version": item.model_version,
                    "series_id": item.series_id,
                    "fold": item.fold,
                    "train_size": item.train_size,
                    "train_end_timestamp": item.train_end_timestamp,
                    "test_start_timestamp": item.test_start_timestamp,
                    "test_end_timestamp": item.test_end_timestamp,
                    "actuals": list(item.actuals),
                    "quantile_forecasts": {
                        _level_key(level): list(values)
                        for level, values in item.quantile_forecasts.items()
                    },
                    "mase": item.mase,
                    "wql": item.wql,
                    "pinball_losses": {
                        _level_key(level): value for level, value in item.pinball_losses.items()
                    },
                    "interval_coverages": {
                        _level_key(level): value for level, value in item.interval_coverages.items()
                    },
                }
                for item in self.evaluations
            ],
            "skipped_series": [
                {
                    "series_id": item.series_id,
                    "observation_count": item.observation_count,
                    "required_observations": item.required_observations,
                }
                for item in self.skipped_series
            ],
            "model_summaries": [
                {
                    "model_id": item.model_id,
                    "model_version": item.model_version,
                    "series_count": item.series_count,
                    "fold_count": item.fold_count,
                    "mean_mase": item.mean_mase,
                    "mean_wql": item.mean_wql,
                    "mean_pinball_loss": item.mean_pinball_loss,
                    "interval_coverages": {
                        _level_key(level): value for level, value in item.interval_coverages.items()
                    },
                }
                for item in self.model_summaries
            ],
        }

    def to_json_bytes(self) -> bytes:
        """Serialize the report deterministically (no wall-clock metadata)."""
        serialized = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return (serialized + "\n").encode("utf-8")


@dataclass(frozen=True, slots=True)
class ArtifactMetadata:
    """Digest and size of a written deterministic evaluation artifact."""

    path: str
    sha256: str
    size_bytes: int


def _level_key(level: float) -> str:
    return format(level, ".12g")


def _mean_or_none(values: Sequence[float | None]) -> float | None:
    defined = tuple(value for value in values if value is not None)
    if not defined:
        return None
    return sum(defined) / len(defined)


def _iso_timestamp(value: date | datetime) -> str:
    return value.isoformat()


def _normalized_history(history: pl.DataFrame | pl.LazyFrame) -> pl.DataFrame:
    source = history.collect() if isinstance(history, pl.LazyFrame) else history
    available = set(source.columns)
    required = {"series_id", "timestamp", "demand"}
    missing = sorted(required - available)
    if missing:
        raise ValueError(f"missing canonical columns: {', '.join(missing)}")

    normalized = source.select(
        pl.col("series_id").cast(pl.String, strict=False).alias("series_id"),
        pl.col("timestamp").cast(pl.Datetime, strict=False).alias("timestamp"),
        pl.col("demand").cast(pl.Float64, strict=False).alias("demand"),
    ).sort(["series_id", "timestamp"])
    quality = validate_history(normalized)
    if not quality.is_valid:
        raise ValueError("invalid history: " + "; ".join(quality.issues))
    return normalized


def _fingerprint_history(history: pl.DataFrame) -> str:
    digest = hashlib.sha256()
    for series_id, timestamp, demand in history.iter_rows():
        row = json.dumps(
            [series_id, _iso_timestamp(timestamp), float(demand).hex()],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
        digest.update(row)
        digest.update(b"\n")
    return digest.hexdigest()


def _coverage_bounds(
    quantile_levels: Sequence[float],
    nominal_coverage: float,
) -> tuple[float, float]:
    lower_target = (1.0 - nominal_coverage) / 2.0
    upper_target = 1.0 - lower_target
    lower = next(level for level in quantile_levels if isclose(level, lower_target, abs_tol=1e-10))
    upper = next(level for level in quantile_levels if isclose(level, upper_target, abs_tol=1e-10))
    return lower, upper


def _model_summaries(
    evaluations: Sequence[FoldEvaluation],
    model_ids: Sequence[tuple[str, str]],
    coverage_levels: Sequence[float],
) -> tuple[ModelSummary, ...]:
    summaries: list[ModelSummary] = []
    for model_id, model_version in model_ids:
        records = tuple(item for item in evaluations if item.model_id == model_id)
        if not records:
            continue
        pinball_values = tuple(value for item in records for value in item.pinball_losses.values())
        coverage = {
            nominal: sum(item.interval_coverages[nominal] for item in records) / len(records)
            for nominal in coverage_levels
        }
        summaries.append(
            ModelSummary(
                model_id=model_id,
                model_version=model_version,
                series_count=len({item.series_id for item in records}),
                fold_count=len(records),
                mean_mase=_mean_or_none(tuple(item.mase for item in records)),
                mean_wql=_mean_or_none(tuple(item.wql for item in records)),
                mean_pinball_loss=sum(pinball_values) / len(pinball_values),
                interval_coverages=coverage,
            )
        )
    return tuple(summaries)


def run_backtest(
    history: pl.DataFrame | pl.LazyFrame,
    adapters: Sequence[ForecastAdapter],
    config: BacktestConfig,
) -> BacktestReport:
    """Evaluate adapters on identical rolling-origin splits for each demand series.

    Each adapter sees only rows preceding its test window. Short series are
    explicitly reported as skipped rather than silently discarded.
    """
    if not adapters:
        raise ValueError("at least one forecasting adapter is required")

    model_ids: list[tuple[str, str]] = []
    seen_model_ids: set[str] = set()
    for adapter in adapters:
        model_id = adapter.model_id.strip()
        model_version = adapter.model_version.strip()
        if not model_id or not model_version:
            raise ValueError("every adapter must provide non-blank model_id and model_version")
        if model_id in seen_model_ids:
            raise ValueError(f"duplicate model_id: {model_id}")
        seen_model_ids.add(model_id)
        model_ids.append((model_id, model_version))

    normalized = _normalized_history(history)
    fingerprint = _fingerprint_history(normalized)
    evaluations: list[FoldEvaluation] = []
    skipped: list[SkippedSeries] = []
    series_history_ranges: dict[str, tuple[str, str]] = {}
    required_count = config.initial_train_size + config.horizon

    groups = normalized.partition_by("series_id", maintain_order=True)
    for group in groups:
        series_id = str(group.get_column("series_id")[0])
        timestamps = group.get_column("timestamp").to_list()
        values = tuple(float(value) for value in group.get_column("demand").to_list())
        series_history_ranges[series_id] = (
            _iso_timestamp(timestamps[0]),
            _iso_timestamp(timestamps[-1]),
        )
        if len(values) < required_count:
            skipped.append(
                SkippedSeries(
                    series_id=series_id,
                    observation_count=len(values),
                    required_observations=required_count,
                )
            )
            continue

        splits = rolling_origin_splits(len(values), config)
        for adapter, (model_id, model_version) in zip(adapters, model_ids, strict=True):
            for split in splits:
                training_values = values[split.train_start : split.train_end]
                actuals = values[split.test_start : split.test_end]
                forecast = adapter.predict(
                    series_id,
                    training_values,
                    horizon=config.horizon,
                    quantile_levels=config.quantile_levels,
                    seed=config.seed,
                )
                if forecast.series_id != series_id:
                    raise ValueError(
                        f"adapter {model_id} returned series_id {forecast.series_id!r}"
                    )
                if forecast.horizon != config.horizon:
                    raise ValueError(
                        f"adapter {model_id} returned horizon {forecast.horizon}; "
                        f"expected {config.horizon}"
                    )
                if tuple(forecast.quantiles) != config.quantile_levels:
                    raise ValueError(
                        f"adapter {model_id} returned quantile levels "
                        f"{tuple(forecast.quantiles)}; expected {config.quantile_levels}"
                    )

                pinball = {
                    level: pinball_loss(actuals, forecast.quantiles[level], level)
                    for level in config.quantile_levels
                }
                coverages: dict[float, float] = {}
                for nominal in config.coverage_levels:
                    lower, upper = _coverage_bounds(config.quantile_levels, nominal)
                    coverages[nominal] = interval_coverage(
                        actuals,
                        forecast.quantiles[lower],
                        forecast.quantiles[upper],
                    )

                evaluations.append(
                    FoldEvaluation(
                        model_id=model_id,
                        model_version=model_version,
                        series_id=series_id,
                        fold=split.fold,
                        train_size=len(training_values),
                        train_end_timestamp=_iso_timestamp(timestamps[split.train_end - 1]),
                        test_start_timestamp=_iso_timestamp(timestamps[split.test_start]),
                        test_end_timestamp=_iso_timestamp(timestamps[split.test_end - 1]),
                        actuals=actuals,
                        quantile_forecasts=dict(forecast.quantiles),
                        mase=mean_absolute_scaled_error(
                            actuals,
                            forecast.quantiles[0.5],
                            training_values,
                            season_length=config.season_length,
                        ),
                        wql=weighted_quantile_loss(actuals, forecast.quantiles),
                        pinball_losses=pinball,
                        interval_coverages=coverages,
                    )
                )

    if not evaluations:
        raise ValueError("no series had enough observations for a complete backtest fold")

    summaries = _model_summaries(evaluations, model_ids, config.coverage_levels)
    return BacktestReport(
        dataset_fingerprint=fingerprint,
        config=config,
        evaluations=tuple(evaluations),
        skipped_series=tuple(skipped),
        model_summaries=summaries,
        series_history_ranges=dict(sorted(series_history_ranges.items())),
    )


def write_evaluation_artifact(
    report: BacktestReport,
    path: str | Path,
) -> ArtifactMetadata:
    """Write canonical JSON and return its SHA-256 provenance digest."""
    destination = Path(path)
    payload = report.to_json_bytes()
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
