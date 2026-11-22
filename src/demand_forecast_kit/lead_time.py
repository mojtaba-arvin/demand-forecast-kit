# SPDX-FileCopyrightText: 2026 Mojtaba Arvin
# SPDX-License-Identifier: MIT
"""Leakage-aware lead-time demand calibration from rolling-origin residual paths."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from math import floor, isclose, isfinite

from demand_forecast_kit.backtesting import BacktestReport, FoldEvaluation
from demand_forecast_kit.inventory import InventoryScenario


@dataclass(frozen=True, slots=True)
class LeadTimeDemandDistribution:
    """Bootstrap distribution for cumulative demand over one replenishment lead time."""

    series_id: str
    model_id: str
    model_version: str
    forecast_origin: str
    lead_time: int
    quantiles: dict[float, float]
    calibration_path_count: int
    bootstrap_sample_count: int
    earliest_calibration_end: str
    latest_calibration_end: str


@dataclass(frozen=True, slots=True)
class LeadTimeCalibrationBacktest:
    """Prequential out-of-sample calibration diagnostics for cumulative demand."""

    series_id: str
    model_id: str
    lead_time: int
    origin_count: int
    quantile_coverage: dict[float, float]
    mean_pinball_loss: dict[float, float]
    interval_coverage: dict[float, float]


def _parse_timestamp(value: str | date | datetime, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    else:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO date or datetime") from exc
    if parsed.tzinfo is not None:
        raise ValueError(f"{field} must use the same timezone-naive convention as backtest data")
    return parsed


def _validate_quantiles(levels: Sequence[float]) -> tuple[float, ...]:
    normalized = tuple(float(level) for level in levels)
    if not normalized or any(not isfinite(level) or not 0.0 < level < 1.0 for level in normalized):
        raise ValueError("quantile_levels must be finite values strictly between 0 and 1")
    if tuple(sorted(set(normalized))) != normalized:
        raise ValueError("quantile_levels must be unique and strictly increasing")
    return normalized


def _eligible_residual_paths(
    report: BacktestReport,
    *,
    series_id: str,
    model_id: str,
    origin: datetime,
) -> tuple[tuple[FoldEvaluation, tuple[float, ...]], ...]:
    candidates: list[FoldEvaluation] = []
    for item in report.evaluations:
        if item.series_id != series_id or item.model_id != model_id:
            continue
        end = _parse_timestamp(item.test_end_timestamp, "test_end_timestamp")
        if end < origin:
            candidates.append(item)

    candidates.sort(
        key=lambda item: (
            _parse_timestamp(item.test_start_timestamp, "test_start_timestamp"),
            item.fold,
        )
    )
    selected: list[tuple[FoldEvaluation, tuple[float, ...]]] = []
    previous_end: datetime | None = None
    versions: set[str] = set()
    for item in candidates:
        start = _parse_timestamp(item.test_start_timestamp, "test_start_timestamp")
        end = _parse_timestamp(item.test_end_timestamp, "test_end_timestamp")
        if previous_end is not None and start <= previous_end:
            continue
        median = item.quantile_forecasts.get(0.5)
        if median is None:
            raise ValueError("backtest evaluations must contain median (0.5) forecasts")
        if len(item.actuals) != report.config.horizon or len(median) != report.config.horizon:
            raise ValueError("backtest residual paths must match the configured horizon")
        residuals = tuple(
            actual - forecast for actual, forecast in zip(item.actuals, median, strict=True)
        )
        if any(not isfinite(value) for value in residuals):
            raise ValueError("backtest residual paths must contain only finite values")
        selected.append((item, residuals))
        previous_end = end
        versions.add(item.model_version)

    if len(versions) > 1:
        raise ValueError("calibration paths must use one consistent model version")
    return tuple(selected)


def _empirical_quantile(values: Sequence[float], level: float) -> float:
    ordered = sorted(values)
    position = level * (len(ordered) - 1)
    lower = floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def calibrate_lead_time_demand(
    report: BacktestReport,
    *,
    series_id: str,
    model_id: str,
    forecast_origin: str | date | datetime,
    baseline_median: Sequence[float],
    lead_time: int,
    quantile_levels: Sequence[float] = (0.1, 0.5, 0.9),
    bootstrap_samples: int = 1000,
    min_calibration_paths: int = 5,
    seed: int = 42,
) -> LeadTimeDemandDistribution:
    """Calibrate cumulative demand by resampling complete historical residual paths.

    Only completed, same-series/model backtest windows strictly before forecast_origin
    are eligible. Overlapping windows are greedily removed so repeated actual periods
    do not masquerade as independent calibration paths. Residual dependence within
    each forecast horizon is retained by resampling the full path, not daily residuals.
    """
    if not series_id.strip() or not model_id.strip():
        raise ValueError("series_id and model_id must be non-blank")
    if type(lead_time) is not int or not 1 <= lead_time <= report.config.horizon:
        raise ValueError("lead_time must be an integer within the backtest horizon")
    if type(bootstrap_samples) is not int or bootstrap_samples < 1:
        raise ValueError("bootstrap_samples must be a positive integer")
    if type(min_calibration_paths) is not int or min_calibration_paths < 2:
        raise ValueError("min_calibration_paths must be an integer >= 2")
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a non-negative integer")

    levels = _validate_quantiles(quantile_levels)
    baseline = tuple(float(value) for value in baseline_median)
    if len(baseline) != lead_time:
        raise ValueError("baseline_median length must equal lead_time")
    if any(not isfinite(value) or value < 0.0 for value in baseline):
        raise ValueError("baseline_median values must be finite and non-negative")

    origin = _parse_timestamp(forecast_origin, "forecast_origin")
    paths = _eligible_residual_paths(report, series_id=series_id, model_id=model_id, origin=origin)
    if len(paths) < min_calibration_paths:
        raise ValueError(
            f"insufficient non-overlapping calibration paths: {len(paths)}; "
            f"need at least {min_calibration_paths}"
        )

    rng = random.Random(seed)
    cumulative_samples: list[float] = []
    for _ in range(bootstrap_samples):
        _, residual_path = rng.choice(paths)
        daily_demand = (
            max(0.0, baseline[index] + residual_path[index]) for index in range(lead_time)
        )
        cumulative_samples.append(sum(daily_demand))

    first_end = paths[0][0].test_end_timestamp
    last_end = paths[-1][0].test_end_timestamp
    return LeadTimeDemandDistribution(
        series_id=series_id,
        model_id=model_id,
        model_version=paths[-1][0].model_version,
        forecast_origin=origin.isoformat(),
        lead_time=lead_time,
        quantiles={level: _empirical_quantile(cumulative_samples, level) for level in levels},
        calibration_path_count=len(paths),
        bootstrap_sample_count=bootstrap_samples,
        earliest_calibration_end=first_end,
        latest_calibration_end=last_end,
    )


def to_inventory_scenario(
    distribution: LeadTimeDemandDistribution,
    *,
    scenario_id: str,
    realized_lead_time_demand: float,
    inventory_position: float,
) -> InventoryScenario:
    """Adapt a calibrated cumulative distribution to the inventory evaluator contract."""
    return InventoryScenario(
        scenario_id=scenario_id,
        lead_time_demand_quantiles=distribution.quantiles,
        realized_lead_time_demand=realized_lead_time_demand,
        inventory_position=inventory_position,
    )


def backtest_lead_time_calibration(
    report: BacktestReport,
    *,
    series_id: str,
    model_id: str,
    lead_time: int,
    quantile_levels: Sequence[float] = (0.1, 0.5, 0.9),
    bootstrap_samples: int = 1000,
    min_calibration_paths: int = 5,
    seed: int = 42,
) -> LeadTimeCalibrationBacktest:
    """Measure quantile coverage on later folds using only earlier completed folds."""
    levels = _validate_quantiles(quantile_levels)
    if type(lead_time) is not int or not 1 <= lead_time <= report.config.horizon:
        raise ValueError("lead_time must be an integer within the backtest horizon")
    targets = sorted(
        (
            item
            for item in report.evaluations
            if item.series_id == series_id and item.model_id == model_id
        ),
        key=lambda item: (
            _parse_timestamp(item.test_start_timestamp, "test_start_timestamp"),
            item.fold,
        ),
    )
    hits = {level: 0 for level in levels}
    losses = {level: 0.0 for level in levels}
    interval_hits: dict[float, int] = {}
    interval_levels = tuple(
        level
        for level in (0.8, 0.9)
        if any(isclose(value, (1.0 - level) / 2.0, abs_tol=1e-10) for value in levels)
        and any(isclose(value, (1.0 + level) / 2.0, abs_tol=1e-10) for value in levels)
    )
    for nominal in interval_levels:
        interval_hits[nominal] = 0

    evaluated = 0
    for index, target in enumerate(targets):
        median = target.quantile_forecasts.get(0.5)
        if median is None:
            raise ValueError("target folds must contain median (0.5) forecasts")
        origin = _parse_timestamp(target.test_start_timestamp, "test_start_timestamp")
        available = _eligible_residual_paths(
            report, series_id=series_id, model_id=model_id, origin=origin
        )
        if len(available) < min_calibration_paths:
            continue
        distribution = calibrate_lead_time_demand(
            report,
            series_id=series_id,
            model_id=model_id,
            forecast_origin=origin,
            baseline_median=median[:lead_time],
            lead_time=lead_time,
            quantile_levels=levels,
            bootstrap_samples=bootstrap_samples,
            min_calibration_paths=min_calibration_paths,
            seed=seed + index,
        )
        actual = sum(target.actuals[:lead_time])
        evaluated += 1
        for level, predicted in distribution.quantiles.items():
            hits[level] += int(actual <= predicted)
            error = actual - predicted
            losses[level] += max(level * error, (level - 1.0) * error)
        for nominal in interval_levels:
            lower = distribution.quantiles[(1.0 - nominal) / 2.0]
            upper = distribution.quantiles[(1.0 + nominal) / 2.0]
            interval_hits[nominal] += int(lower <= actual <= upper)

    if evaluated == 0:
        raise ValueError("no target folds had enough strictly earlier calibration paths")
    return LeadTimeCalibrationBacktest(
        series_id=series_id,
        model_id=model_id,
        lead_time=lead_time,
        origin_count=evaluated,
        quantile_coverage={level: hits[level] / evaluated for level in levels},
        mean_pinball_loss={level: losses[level] / evaluated for level in levels},
        interval_coverage={level: interval_hits[level] / evaluated for level in interval_levels},
    )
