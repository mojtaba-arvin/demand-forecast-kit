"""Probabilistic demand forecasting and inventory decision primitives."""

from demand_forecast_kit.backtesting import (
    ArtifactMetadata,
    BacktestConfig,
    BacktestReport,
    FoldEvaluation,
    ModelSummary,
    RollingOriginSplit,
    SkippedSeries,
    rolling_origin_splits,
    run_backtest,
    write_evaluation_artifact,
)
from demand_forecast_kit.contracts import QuantileForecast
from demand_forecast_kit.decisions import OrderRecommendation, newsvendor_order
from demand_forecast_kit.metrics import (
    interval_coverage,
    mean_absolute_scaled_error,
    pinball_loss,
    weighted_quantile_loss,
)
from demand_forecast_kit.models import ForecastAdapter, SeasonalNaiveAdapter

__version__ = "0.1.0"

__all__ = [
    "ArtifactMetadata",
    "BacktestConfig",
    "BacktestReport",
    "ForecastAdapter",
    "FoldEvaluation",
    "ModelSummary",
    "OrderRecommendation",
    "QuantileForecast",
    "RollingOriginSplit",
    "SeasonalNaiveAdapter",
    "SkippedSeries",
    "interval_coverage",
    "mean_absolute_scaled_error",
    "newsvendor_order",
    "pinball_loss",
    "rolling_origin_splits",
    "run_backtest",
    "weighted_quantile_loss",
    "write_evaluation_artifact",
]
