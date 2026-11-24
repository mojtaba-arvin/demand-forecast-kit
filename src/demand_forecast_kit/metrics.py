"""Deterministic probabilistic forecasting metrics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import isfinite


def _finite_values(values: Sequence[float], name: str) -> tuple[float, ...]:
    normalized = tuple(float(value) for value in values)
    if any(not isfinite(value) for value in normalized):
        raise ValueError(f"{name} must contain only finite values")
    return normalized


def _paired_values(
    actuals: Sequence[float], predictions: Sequence[float]
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    observed = _finite_values(actuals, "actuals")
    forecast = _finite_values(predictions, "predictions")
    if not observed:
        raise ValueError("actuals must not be empty")
    if len(observed) != len(forecast):
        raise ValueError("actuals and predictions must have the same length")
    return observed, forecast


def pinball_loss(
    actuals: Sequence[float],
    predictions: Sequence[float],
    quantile_level: float,
) -> float:
    """Return mean pinball loss for one quantile forecast.

    Uses max(q * error, (q - 1) * error), where error is actual minus prediction.
    Lower values are better.
    """
    level = float(quantile_level)
    if not isfinite(level) or not 0.0 < level < 1.0:
        raise ValueError("quantile_level must be finite and strictly between 0 and 1")

    observed, forecast = _paired_values(actuals, predictions)
    losses = [
        max(level * (actual - predicted), (level - 1.0) * (actual - predicted))
        for actual, predicted in zip(observed, forecast, strict=True)
    ]
    return sum(losses) / len(losses)


def weighted_quantile_loss(
    actuals: Sequence[float],
    quantile_predictions: Mapping[float, Sequence[float]],
) -> float | None:
    """Return normalized WQL, or None when its actual-demand denominator is zero.

    WQL = 2 * sum(pinball losses across quantiles and observations)
    divided by sum(abs(actuals)). Scores are comparable only when quantile
    sets and evaluation windows match.
    """
    if not quantile_predictions:
        raise ValueError("at least one quantile prediction is required")

    observed = _finite_values(actuals, "actuals")
    if not observed:
        raise ValueError("actuals must not be empty")

    normalized: dict[float, tuple[float, ...]] = {}
    for raw_level, raw_predictions in quantile_predictions.items():
        level = float(raw_level)
        if not isfinite(level) or not 0.0 < level < 1.0:
            raise ValueError("quantile levels must be finite and strictly between 0 and 1")
        if level in normalized:
            raise ValueError("quantile levels must be unique")
        predictions = _finite_values(raw_predictions, "predictions")
        if len(predictions) != len(observed):
            raise ValueError("all quantile predictions must have the same length as actuals")
        normalized[level] = predictions

    levels = tuple(sorted(normalized))
    for index in range(len(observed)):
        values_at_step = tuple(normalized[level][index] for level in levels)
        if any(
            lower > upper for lower, upper in zip(values_at_step, values_at_step[1:], strict=False)
        ):
            raise ValueError("quantile predictions must be non-decreasing at every step")

    denominator = sum(abs(value) for value in observed)
    if denominator == 0.0:
        return None

    total_loss = sum(
        sum(
            max(
                level * (actual - predicted),
                (level - 1.0) * (actual - predicted),
            )
            for actual, predicted in zip(observed, normalized[level], strict=True)
        )
        for level in levels
    )
    return 2.0 * total_loss / denominator


def mean_absolute_scaled_error(
    actuals: Sequence[float],
    predictions: Sequence[float],
    training_values: Sequence[float],
    *,
    season_length: int = 1,
) -> float | None:
    """Return MASE, or None when its in-sample seasonal scale is zero/undefined.

    The scale is the mean absolute difference between training observations
    separated by season_length. Zero scale is not replaced with an epsilon.
    """
    if type(season_length) is not int or season_length < 1:
        raise ValueError("season_length must be a positive integer")

    observed, forecast = _paired_values(actuals, predictions)
    training = _finite_values(training_values, "training_values")
    if len(training) <= season_length:
        return None

    scale = sum(
        abs(training[index] - training[index - season_length])
        for index in range(season_length, len(training))
    ) / (len(training) - season_length)
    if scale == 0.0:
        return None

    mean_absolute_error = sum(
        abs(actual - predicted) for actual, predicted in zip(observed, forecast, strict=True)
    ) / len(observed)
    return mean_absolute_error / scale


def interval_coverage(
    actuals: Sequence[float],
    lower_bounds: Sequence[float],
    upper_bounds: Sequence[float],
) -> float:
    """Return the empirical fraction of observations inside inclusive bounds."""
    observed, lower = _paired_values(actuals, lower_bounds)
    upper = _finite_values(upper_bounds, "upper_bounds")
    if len(observed) != len(upper):
        raise ValueError("actuals and upper_bounds must have the same length")
    if any(lo > hi for lo, hi in zip(lower, upper, strict=True)):
        raise ValueError("lower bounds must not exceed upper bounds")
    covered = sum(
        1 for actual, lo, hi in zip(observed, lower, upper, strict=True) if lo <= actual <= hi
    )
    return covered / len(observed)
