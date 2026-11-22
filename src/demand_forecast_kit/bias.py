"""Prequential bias correction fitted only from completed historical folds."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite


@dataclass(frozen=True, slots=True)
class TemporalBiasCorrection:
    """Frozen additive median correction learned before a forecast origin."""

    series_id: str
    model_id: str
    model_version: str
    forecast_origin: str
    correction: float
    calibration_path_count: int
    latest_calibration_end: str

    def apply(self, median_forecast: Sequence[float]) -> tuple[float, ...]:
        """Apply the frozen correction and preserve non-negative demand support."""
        values = tuple(float(value) for value in median_forecast)
        if any(not isfinite(value) or value < 0.0 for value in values):
            raise ValueError("median forecasts must be finite and non-negative")
        return tuple(max(0.0, value + self.correction) for value in values)


def _parse_origin(value: str | date | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    else:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("forecast_origin must be an ISO date or datetime") from exc
    if parsed.tzinfo is not None:
        raise ValueError("forecast_origin must use timezone-naive backtest timestamps")
    return parsed


def estimate_temporal_bias_correction(
    report: object,
    *,
    series_id: str,
    model_id: str,
    forecast_origin: str | date | datetime,
    expected_model_version: str | None = None,
    min_calibration_paths: int = 2,
) -> TemporalBiasCorrection:
    """Estimate median residual bias from non-overlapping folds before forecast_origin.

    The function accepts a BacktestReport and uses only complete test windows
    whose end timestamp is strictly earlier than the requested origin. The
    evaluation/holdout window is never read or used to fit the correction.
    """
    from demand_forecast_kit.backtesting import BacktestReport

    if not isinstance(report, BacktestReport):
        raise TypeError("report must be a BacktestReport")
    if not series_id.strip() or not model_id.strip():
        raise ValueError("series_id and model_id must be non-blank")
    if expected_model_version is not None and not expected_model_version.strip():
        raise ValueError("expected_model_version must be non-blank when provided")
    if type(min_calibration_paths) is not int or min_calibration_paths < 2:
        raise ValueError("min_calibration_paths must be an integer >= 2")

    origin = _parse_origin(forecast_origin)
    candidates = []
    for item in report.evaluations:
        if item.series_id != series_id or item.model_id != model_id:
            continue
        end = _parse_origin(item.test_end_timestamp)
        if end < origin:
            candidates.append(item)
    candidates.sort(key=lambda item: (_parse_origin(item.test_start_timestamp), item.fold))

    selected = []
    previous_end: datetime | None = None
    versions: set[str] = set()
    for item in candidates:
        start = _parse_origin(item.test_start_timestamp)
        end = _parse_origin(item.test_end_timestamp)
        if previous_end is not None and start <= previous_end:
            continue
        median = item.quantile_forecasts.get(0.5)
        if median is None or len(median) != len(item.actuals) or not median:
            raise ValueError("calibration folds must contain aligned median forecasts and actuals")
        residuals = tuple(
            float(actual) - float(predicted)
            for actual, predicted in zip(item.actuals, median, strict=True)
        )
        if any(not isfinite(value) for value in residuals):
            raise ValueError("calibration residuals must be finite")
        selected.extend(residuals)
        previous_end = end
        versions.add(item.model_version)

    if len(selected) == 0 or len(versions) == 0:
        raise ValueError("no eligible pre-origin calibration paths are available")
    if len(versions) != 1:
        raise ValueError("calibration paths must use one consistent model version")
    if len(candidates) < min_calibration_paths:
        raise ValueError(
            f"insufficient pre-origin calibration paths: {len(candidates)}; "
            f"need at least {min_calibration_paths}"
        )

    model_version = next(iter(versions))
    if expected_model_version is not None and model_version != expected_model_version:
        raise ValueError(
            f"calibration model version mismatch: expected {expected_model_version!r}, "
            f"found {model_version!r}"
        )
    ordered = sorted(selected)
    middle = len(ordered) // 2
    correction = (
        ordered[middle]
        if len(ordered) % 2
        else (ordered[middle - 1] + ordered[middle]) / 2.0
    )
    return TemporalBiasCorrection(
        series_id=series_id,
        model_id=model_id,
        model_version=model_version,
        forecast_origin=origin.isoformat(),
        correction=correction,
        calibration_path_count=len(candidates),
        latest_calibration_end=max(
            (item.test_end_timestamp for item in candidates),
            key=_parse_origin,
        ),
    )
