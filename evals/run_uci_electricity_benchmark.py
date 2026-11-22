"""Run an opt-in independent benchmark on UCI Electricity Load Diagrams."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import polars as pl

from demand_forecast_kit.backtesting import BacktestConfig, run_backtest
from demand_forecast_kit.data import scan_history
from demand_forecast_kit.datasets import (
    UCI_ELECTRICITY_DOI,
    UCI_ELECTRICITY_SOURCE,
    prepare_uci_electricity,
)
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter
from demand_forecast_kit.models.statistical import AutoETSAdapter, ThetaAdapter


def sha256_file(path: Path) -> str:
    """Hash the raw UCI text file in bounded memory."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_benchmark(
    source: Path,
    *,
    max_series: int = 370,
    output: Path = Path("artifacts/uci-electricity-benchmark.json"),
) -> dict[str, object]:
    """Prepare and evaluate a deterministic subset of UCI client load series."""
    if type(max_series) is not int or not 1 <= max_series <= 370:
        raise ValueError("max_series must be an integer between 1 and 370")
    daily_path = output.with_suffix(".daily.parquet")
    preparation = prepare_uci_electricity(source, daily_path)
    history = scan_history(daily_path)
    selected_ids = (
        history.select("series_id")
        .unique()
        .sort("series_id")
        .limit(max_series)
        .collect()
        .get_column("series_id")
        .to_list()
    )
    selected = history.filter(pl.col("series_id").is_in(selected_ids))
    adapters = [
        SeasonalNaiveAdapter(season_length=7),
        AutoETSAdapter(season_length=7),
        ThetaAdapter(season_length=7, decomposition_type="additive"),
    ]
    config = BacktestConfig(
        initial_train_size=365,
        horizon=7,
        step=90,
        season_length=7,
        quantile_levels=(0.1, 0.5, 0.9),
        coverage_levels=(0.8,),
        seed=42,
    )
    report = run_backtest(selected, adapters, config)
    payload: dict[str, object] = {
        "schema_version": 1,
        "benchmark": "uci-electricity-load-daily",
        "provenance": {
            "dataset": "ElectricityLoadDiagrams20112014",
            "creator": "Artur Trindade",
            "citation": "Trindade, A. (2015). ElectricityLoadDiagrams20112014. UCI Machine Learning Repository.",
            "doi": UCI_ELECTRICITY_DOI,
            "source_url": "https://archive.ics.uci.edu/dataset/321/electricity",
            "download_url": UCI_ELECTRICITY_SOURCE,
            "license": "CC BY 4.0",
            "source_file_sha256": sha256_file(source),
            "preprocessing": (
                "Convert 15-minute kW readings to kWh by dividing by four; "
                "aggregate by client and Portuguese-local calendar day; preserve "
                "source DST semantics and leading zeroes."
            ),
        },
        "preparation": preparation,
        "configuration": {
            "series_count": len(selected_ids),
            "initial_train_size_days": config.initial_train_size,
            "horizon_days": config.horizon,
            "step_days": config.step,
            "season_length_days": config.season_length,
            "quantile_levels": list(config.quantile_levels),
            "coverage_levels": list(config.coverage_levels),
            "seed": config.seed,
        },
        "evaluation": report.to_dict(),
        "interpretation": (
            "This is an independent cross-domain dense multi-series load benchmark, "
            "not a retail SKU or inventory replenishment benchmark. Results must not "
            "be presented as retail accuracy or inventory-savings evidence."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    daily_path.unlink(missing_ok=True)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Extracted LD2011_2014.txt file")
    parser.add_argument("--max-series", type=int, default=370)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/uci-electricity-benchmark.json"),
    )
    args = parser.parse_args()
    result = run_benchmark(args.source, max_series=args.max_series, output=args.output)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
