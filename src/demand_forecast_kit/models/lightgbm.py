"""Optional LightGBM quantile adapter with origin-safe known covariates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from math import isfinite
from typing import Any

from demand_forecast_kit.contracts import QuantileForecast


def _load_lightgbm() -> tuple[Any, Any]:
    try:
        lightgbm = import_module("lightgbm")
        numpy = import_module("numpy")
        return lightgbm, numpy
    except ImportError as exc:
        raise ImportError(
            'LightGBMAdapter requires the optional dependency. Install it with: '
            'pip install "demand-forecast-kit[lightgbm]"'
        ) from exc


class LightGBMAdapter:
    """Recursive quantile LightGBM forecaster with strictly known-future features.

    Historical covariates must have a matching future_known_covariates entry.
    This deliberately excludes past-only covariates from direct future features:
    a value unavailable at the forecast origin is never carried forward or guessed.
    """

    def __init__(
        self,
        *,
        lags: Sequence[int] = (1, 7, 14, 28),
        rolling_windows: Sequence[int] = (7, 28),
        num_boost_round: int = 100,
        num_leaves: int = 15,
        min_data_in_leaf: int = 5,
        intermittent_zero_fraction: float = 0.8,
    ) -> None:
        raw_lags = tuple(lags)
        raw_windows = tuple(rolling_windows)
        if any(type(value) is not int for value in (*raw_lags, *raw_windows)):
            raise ValueError("lags and rolling_windows must contain integers")
        self.lags = tuple(sorted(set(raw_lags)))
        self.rolling_windows = tuple(sorted(set(raw_windows)))
        if not self.lags or any(value < 1 for value in self.lags):
            raise ValueError("lags must contain positive integers")
        if any(value < 2 for value in self.rolling_windows):
            raise ValueError("rolling_windows must contain integers >= 2")
        for name, value in (
            ("num_boost_round", num_boost_round),
            ("num_leaves", num_leaves),
            ("min_data_in_leaf", min_data_in_leaf),
        ):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if (
            not isfinite(intermittent_zero_fraction)
            or not 0.0 < intermittent_zero_fraction < 1.0
        ):
            raise ValueError("intermittent_zero_fraction must be finite and in (0, 1)")
        self.num_boost_round = num_boost_round
        self.num_leaves = num_leaves
        self.min_data_in_leaf = min_data_in_leaf
        self.intermittent_zero_fraction = float(intermittent_zero_fraction)

    @property
    def model_id(self) -> str:
        return "lightgbm-quantile"

    @property
    def model_version(self) -> str:
        try:
            return f"lightgbm-{version('lightgbm')}"
        except PackageNotFoundError as exc:
            raise ImportError(
                'LightGBMAdapter requires the optional dependency. Install it with: '
                'pip install "demand-forecast-kit[lightgbm]"'
            ) from exc

    def predict(
        self,
        series_id: str,
        history: Sequence[float],
        *,
        horizon: int,
        quantile_levels: Sequence[float],
        seed: int,
    ) -> QuantileForecast:
        return self.predict_with_covariates(
            series_id,
            history,
            horizon=horizon,
            quantile_levels=quantile_levels,
            seed=seed,
        )

    def predict_with_covariates(
        self,
        series_id: str,
        history: Sequence[float],
        *,
        horizon: int,
        quantile_levels: Sequence[float],
        seed: int,
        historical_covariates: Mapping[str, Sequence[float]] | None = None,
        future_known_covariates: Mapping[str, Sequence[float]] | None = None,
    ) -> QuantileForecast:
        """Fit direct one-step quantile models and recursively forecast the horizon.

        Covariate names must match across history and forecast periods. Historical
        values are aligned to each target timestamp; future values must genuinely
        be known at the forecast origin (e.g. calendar or committed promotion plan).
        """
        if not series_id.strip():
            raise ValueError("series_id must not be blank")
        if type(horizon) is not int or horizon < 1:
            raise ValueError("horizon must be a positive integer")
        if type(seed) is not int or seed < 0:
            raise ValueError("seed must be a non-negative integer")
        values = tuple(float(value) for value in history)
        if any(not isfinite(value) or value < 0.0 for value in values):
            raise ValueError("history must contain finite non-negative demand")
        zero_fraction = sum(value == 0.0 for value in values) / len(values)
        if zero_fraction >= self.intermittent_zero_fraction:
            raise ValueError(
                f"intermittent history has {zero_fraction:.1%} zero demand; "
                "route this series to an intermittent-demand adapter such as Croston or TSB"
            )
        minimum_history = max(self.lags) + max(20, self.min_data_in_leaf * 2)
        if len(values) < minimum_history:
            raise ValueError(
                f"history must contain at least {minimum_history} observations "
                "to form a useful training matrix"
            )
        levels = tuple(sorted(float(value) for value in quantile_levels))
        if not levels or len(set(levels)) != len(levels):
            raise ValueError("quantile_levels must be non-empty and unique")
        if any(not isfinite(level) or not 0.0 < level < 1.0 for level in levels):
            raise ValueError("quantile levels must be finite and in (0, 1)")

        historical = {
            str(name): tuple(float(value) for value in sequence)
            for name, sequence in (historical_covariates or {}).items()
        }
        future = {
            str(name): tuple(float(value) for value in sequence)
            for name, sequence in (future_known_covariates or {}).items()
        }
        if set(historical) != set(future):
            raise ValueError(
                "every historical covariate must have matching future-known values; "
                "past-only covariates cannot be used as future predictors"
            )
        if any(not name.strip() for name in historical):
            raise ValueError("covariate names must not be blank")
        if any(len(sequence) != len(values) for sequence in historical.values()):
            raise ValueError("historical covariates must align with history")
        if any(len(sequence) != horizon for sequence in future.values()):
            raise ValueError("future-known covariates must align with horizon")
        if any(
            not isfinite(value)
            for sequence in (*historical.values(), *future.values())
            for value in sequence
        ):
            raise ValueError("covariates must contain only finite numeric values")

        lightgbm, numpy = _load_lightgbm()
        feature_names = tuple(sorted(historical))
        first_index = max(self.lags)
        training_features = [
            self._features(values, index, {name: historical[name][index] for name in feature_names})
            for index in range(first_index, len(values))
        ]
        training_targets = values[first_index:]
        matrix = numpy.asarray(training_features, dtype=numpy.float64)
        labels = numpy.asarray(training_targets, dtype=numpy.float64)
        forecasts: dict[float, tuple[float, ...]] = {}
        for level in levels:
            dataset = lightgbm.Dataset(matrix, label=labels, free_raw_data=False)
            booster = lightgbm.train(
                {
                    "objective": "quantile",
                    "alpha": level,
                    "metric": "quantile",
                    "verbosity": -1,
                    "seed": seed,
                    "feature_fraction_seed": seed,
                    "bagging_seed": seed,
                    "data_random_seed": seed,
                    "num_threads": 1,
                    "deterministic": True,
                    "force_col_wise": True,
                    "num_leaves": self.num_leaves,
                    "min_data_in_leaf": self.min_data_in_leaf,
                },
                dataset,
                num_boost_round=self.num_boost_round,
            )
            recursive = list(values)
            prediction: list[float] = []
            for step in range(horizon):
                covariate_values = {name: future[name][step] for name in feature_names}
                row = self._features(recursive, len(recursive), covariate_values)
                raw = float(booster.predict(numpy.asarray([row], dtype=numpy.float64))[0])
                if not isfinite(raw):
                    raise RuntimeError("LightGBM returned a non-finite quantile forecast")
                value = max(0.0, raw)
                prediction.append(value)
                recursive.append(value)
            forecasts[level] = tuple(prediction)

        # Quantile regression models can cross; rearrangement restores the public contract.
        ordered_by_step = [
            tuple(sorted(forecasts[level][step] for level in levels))
            for step in range(horizon)
        ]
        ordered_forecasts = {
            level: tuple(ordered_by_step[step][index] for step in range(horizon))
            for index, level in enumerate(levels)
        }
        return QuantileForecast(series_id=series_id, quantiles=ordered_forecasts)

    def _features(
        self,
        history: Sequence[float],
        target_index: int,
        covariates: Mapping[str, float],
    ) -> tuple[float, ...]:
        features = [float(history[target_index - lag]) for lag in self.lags]
        for window in self.rolling_windows:
            start = target_index - window
            features.append(sum(history[start:target_index]) / window)
        features.append(float(target_index))
        features.extend(float(covariates[name]) for name in sorted(covariates))
        return tuple(features)
