""""Probabilistic demand forecasting and inventory decision primitives."""

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
from demand_forecast_kit.inventory import (
    InventoryEvaluationReport,
    InventoryScenario,
    ScenarioDecision,
    evaluate_inventory_policy,
)
from demand_forecast_kit.lead_time import (
    LeadTimeCalibrationBacktest,
    LeadTimeDemandDistribution,
    backtest_lead_time_calibration,
    calibrate_lead_time_demand,
    to_inventory_scenario,
)
from demand_forecast_kit.metrics import (
    interval_coverage,
    mean_absolute_scaled_error,
    pinball_loss,
    weighted_quantile_loss,
)
from demand_forecast_kit.model_registry import (
    ModelActivation,
    ModelArtifactRecord,
    ModelArtifactRegistry,
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
from demand_forecast_kit.routing import (
    CandidateScore,
    ModelRouter,
    RoutingDecision,
    write_routing_artifact,
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
    "InventoryEvaluationReport",
    "InventoryScenario",
    "LeadTimeCalibrationBacktest",
    "LeadTimeDemandDistribution",
    "ModelActivation",
    "ModelArtifactRecord",
    "ModelArtifactRegistry",
    "ModelRouter",
    "ModelSummary",
    "OrderRecommendation",
    "QuantileForecast",
    "RollingOriginSplit",
    "RoutingDecision",
    "ScenarioDecision",
    "SeasonalNaiveAdapter",
    "SkippedSeries",
    "TSBAdapter",
    "ThetaAdapter",
    "evaluate_inventory_policy",
    "backtest_lead_time_calibration",
    "calibrate_lead_time_demand",
    "to_inventory_scenario",
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
"