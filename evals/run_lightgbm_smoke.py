"""Offline rolling-origin comparison of LightGBM and Seasonal Naive."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from demand_forecast_kit.models.lightgbm import LightGBMAdapter
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter


def _series() -> tuple[list[float], list[float]]:
    prices: list[float] = []
    demand: list[float] = []
    for index in range(140):
        price = 1.0 + (0.25 if index % 14 in (0, 1, 2) else 0.0)
        seasonal = 4.0 * math.sin(2.0 * math.pi * index / 7.0)
        trend = index * 0.015
        noise = ((index * 17) % 7) * 0.2
        prices.append(price)
        demand.append(max(0.0, 18.0 - 8.0 * price + seasonal + trend + noise))
    return demand, prices


def run(output: Path) -> dict[str, object]:
    demand, prices = _series()
    adapter = LightGBMAdapter(
        lags=(1, 7, 14),
        rolling_windows=(7, 14),
        num_boost_round=30,
        num_leaves=7,
        min_data_in_leaf=3,
    )
    baseline = SeasonalNaiveAdapter(season_length=7)
    horizon = 7
    initial_train_size = 56
    step = 7
    folds: list[dict[str, object]] = []
    model_errors: dict[str, list[float]] = {
        adapter.model_id: [],
        baseline.model_id: [],
    }

    for origin in range(initial_train_size, len(demand) - horizon + 1, step):
        train = demand[:origin]
        actuals = demand[origin : origin + horizon]
        historical_known = {"planned_price": prices[:origin]}
        future_known = {"planned_price": prices[origin : origin + horizon]}
        if len(future_known["planned_price"]) != horizon:
            raise RuntimeError("future-known covariates do not cover the forecast horizon")
        forecast = adapter.predict_with_covariates(
            "synthetic-known-covariate",
            train,
            horizon=horizon,
            quantile_levels=(0.1, 0.5, 0.9),
            seed=2026,
            historical_covariates=historical_known,
            future_known_covariates=future_known,
        )
        naive = baseline.predict(
            "synthetic-known-covariate",
            train,
            horizon=horizon,
            quantile_levels=(0.1, 0.5, 0.9),
            seed=2026,
        )
        lightgbm_mae = (
            sum(
                abs(actual - predicted)
                for actual, predicted in zip(actuals, forecast.quantiles[0.5], strict=True)
            )
            / horizon
        )
        naive_mae = (
            sum(
                abs(actual - predicted)
                for actual, predicted in zip(actuals, naive.quantiles[0.5], strict=True)
            )
            / horizon
        )
        model_errors[adapter.model_id].append(lightgbm_mae)
        model_errors[baseline.model_id].append(naive_mae)
        folds.append(
            {
                "origin_index": origin,
                "training_observations": len(train),
                "future_known_covariate_count": len(future_known["planned_price"]),
                "lightgbm_mae": lightgbm_mae,
                "seasonal_naive_mae": naive_mae,
            }
        )

    payload = {
        "schema_version": 1,
        "dataset_fingerprint": hashlib.sha256(
            json.dumps({"demand": demand, "planned_price": prices}, separators=(",", ":")).encode()
        ).hexdigest(),
        "model_version": adapter.model_version,
        "baseline_model_version": baseline.model_version,
        "config": {
            "initial_train_size": initial_train_size,
            "horizon": horizon,
            "step": step,
            "quantiles": [0.1, 0.5, 0.9],
            "seed": 2026,
        },
        "folds": folds,
        "mean_mae": {
            model_id: sum(values) / len(values) for model_id, values in model_errors.items()
        },
        "interpretation": (
            "Synthetic plumbing and origin-availability verification only; "
            "not evidence of real-world model superiority."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/lightgbm-rolling-origin.json")
    )
    args = parser.parse_args()
    result = run(args.output)
    print(f"artifact={args.output}")
    print(f"dataset_fingerprint={result['dataset_fingerprint']}")


if __name__ == "__main__":
    main()
