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
from demand_forecast_kit.routing import (
    CandidateScore,
    ModelRouter,
    RoutingDecision,
    write_routing_artifact,
)
from demand_forecast_kit.models import (
    AutoARIMAAdapter,
    AutoETSAdapter,
    CrostonAdapter,
    ForecastAdapter,
    SeasonalNaiveAdapter,
    ThetaAdapter,
    TSBAdapter,
)

__version__ = "0.1.0"

__all__ = [
    "ArtifactMetadata",
    "AutoARIMAAdapter",
    "AutoETSAdapter",
    "BacktestConfig",
    "BacktestReport",
    "CandidateScore",
    "CrostonAdapter",
    "ForecastAdapter",
    "FoldEvaluation",
    "ModelRouter",
    "ModelSummary",
    "OrderRecommendation",
    "QuantileForecast",
    "RollingOriginSplit",
    "RoutingDecision",
    "SeasonalNaiveAdapter",
    "SkippedSeries",
    "TSBAdapter",
    "ThetaAdapter",
    "interval_coverage",
    "mean_absolute_scaled_error",
    "newsvendor_order",
    "pinball_loss",
    "rolling_origin_splits",
    "run_backtest",
    "weighted_quantile_loss",
    "write_evaluation_artifact",
    "write_routing_artifact",
]
