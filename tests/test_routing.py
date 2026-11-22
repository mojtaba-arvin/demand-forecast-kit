from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from demand_forecast_kit.backtesting import (
    BacktestConfig,
    BacktestReport,
    FoldEvaluation,
    ModelSummary,
)
from demand_forecast_kit.contracts import QuantileForecast
from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter
from demand_forecast_kit.routing import ModelRouter, RoutingDecision, write_routing_artifact


class StubAdapter:
    def __init__(self, model_id: str, model_version: str = "1.0") -> None:
        self._model_id = model_id
        self._model_version = model_version

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def model_version(self) -> str:
        return self._model_version

    def predict(
        self,
        series_id: str,
        history: Sequence[float],
        *,
        horizon: int,
        quantile_levels: Sequence[float],
        seed: int,
    ) -> QuantileForecast:
        center = sum(history) / len(history)
        return QuantileForecast(
            series_id,
            {level: tuple(center for _ in range(horizon)) for level in quantile_levels},
        )


def evaluation(
    model_id: str,
    fold: int,
    *,
    series_id: str = "sku-1",
    wql: float | None = 0.2,
    mase: float | None = 0.8,
    pinball: float = 0.1,
    test_end: str | None = None,
    model_version: str = "1.0",
) -> FoldEvaluation:
    day = 2 * fold
    end = test_end or f"2024-01-{day + 2:02d}"
    return FoldEvaluation(
        model_id=model_id,
        model_version=model_version,
        series_id=series_id,
        fold=fold,
        train_size=day,
        train_end_timestamp=f"2024-01-{day:02d}",
        test_start_timestamp=f"2024-01-{day + 1:02d}",
        test_end_timestamp=end,
        actuals=(10.0, 12.0),
        quantile_forecasts={0.1: (8.0, 9.0), 0.5: (10.0, 11.0), 0.9: (12.0, 13.0)},
        mase=mase,
        wql=wql,
        pinball_losses={0.1: pinball, 0.5: pinball, 0.9: pinball},
        interval_coverages={0.8: 0.5},
    )


def make_report(
    evaluations: tuple[FoldEvaluation, ...],
    *,
    ranges: dict[str, tuple[str, str]] | None = None,
) -> BacktestReport:
    return BacktestReport(
        dataset_fingerprint="a" * 64,
        config=BacktestConfig(
            initial_train_size=2,
            horizon=2,
            season_length=1,
            quantile_levels=(0.1, 0.5, 0.9),
            coverage_levels=(0.8,),
        ),
        evaluations=evaluations,
        skipped_series=(),
        model_summaries=(
            ModelSummary(
                model_id="seasonal-naive",
                model_version="0.1.0",
                series_count=1,
                fold_count=1,
                mean_mase=1.0,
                mean_wql=0.3,
                mean_pinball_loss=0.1,
                interval_coverages={0.8: 0.5},
            ),
        ),
        series_history_ranges=ranges or {"sku-1": ("2024-01-01", "2024-01-10")},
    )


def make_router(*, min_folds: int = 2, metric: str = "wql") -> ModelRouter:
    return ModelRouter(
        [
            SeasonalNaiveAdapter(season_length=2),
            StubAdapter("model-a"),
            StubAdapter("model-b"),
        ],
        min_folds=min_folds,
        metric=metric,  # type: ignore[arg-type]
    )


def test_model_router_selects_best_model_independently_per_series() -> None:
    records = (
        evaluation("model-a", 1, wql=0.1),
        evaluation("model-a", 2, wql=0.2),
        evaluation("model-b", 1, wql=0.4),
        evaluation("model-b", 2, wql=0.5),
        evaluation("model-a", 1, series_id="sku-2", wql=0.8),
        evaluation("model-a", 2, series_id="sku-2", wql=0.7),
        evaluation("model-b", 1, series_id="sku-2", wql=0.2),
        evaluation("model-b", 2, series_id="sku-2", wql=0.1),
    )
    report = make_report(
        records,
        ranges={
            "sku-1": ("2024-01-01", "2024-01-10"),
            "sku-2": ("2024-01-01", "2024-01-10"),
        },
    )
    router = make_router()

    first = router.select(report, series_id="sku-1", forecast_origin=date(2024, 1, 11))
    second = router.select(report, series_id="sku-2", forecast_origin="2024-01-11")

    assert first.chosen_model_id == "model-a"
    assert first.score == pytest.approx(0.15)
    assert first.evidence_fold_count == 2
    assert not first.used_fallback
    assert second.chosen_model_id == "model-b"
    assert second.score == pytest.approx(0.15)


def test_router_uses_fallback_when_no_candidate_has_enough_defined_folds() -> None:
    report = make_report(
        (
            evaluation("model-a", 1, wql=None),
            evaluation("model-b", 1, wql=0.2),
        )
    )
    decision = make_router(min_folds=2).select(
        report,
        series_id="sku-1",
        forecast_origin="2024-01-11",
    )

    assert decision.chosen_model_id == "seasonal-naive"
    assert decision.score is None
    assert decision.evidence_fold_count == 0
    assert decision.used_fallback
    assert decision.candidate_scores == ()


def test_router_prefers_fallback_on_a_statistical_tie() -> None:
    report = make_report(
        (
            evaluation("seasonal-naive", 1, wql=0.2, model_version="0.1.0"),
            evaluation("seasonal-naive", 2, wql=0.2, model_version="0.1.0"),
            evaluation("model-a", 1, wql=0.2),
            evaluation("model-a", 2, wql=0.2),
        )
    )
    decision = make_router().select(
        report,
        series_id="sku-1",
        forecast_origin="2024-01-11",
    )

    assert decision.chosen_model_id == "seasonal-naive"
    assert not decision.used_fallback


def test_router_supports_mase_and_mean_pinball_metrics() -> None:
    report = make_report(
        (
            evaluation("model-a", 1, wql=0.4, mase=0.5, pinball=0.3),
            evaluation("model-a", 2, wql=0.4, mase=0.4, pinball=0.2),
            evaluation("model-b", 1, wql=0.1, mase=0.9, pinball=0.1),
            evaluation("model-b", 2, wql=0.1, mase=0.8, pinball=0.2),
        )
    )

    mase = make_router(metric="mase").select(
        report, series_id="sku-1", forecast_origin="2024-01-11"
    )
    pinball = make_router(metric="mean_pinball_loss").select(
        report, series_id="sku-1", forecast_origin="2024-01-11"
    )

    assert mase.chosen_model_id == "model-a"
    assert pinball.chosen_model_id == "model-b"
    assert pinball.score == pytest.approx(0.15)


@pytest.mark.parametrize("origin", ["2024-01-10", "2024-01-09"])
def test_router_rejects_history_that_is_not_strictly_before_origin(origin: str) -> None:
    router = make_router()
    with pytest.raises(ValueError, match="strictly before forecast_origin"):
        router.select(make_report(()), series_id="sku-1", forecast_origin=origin)


def test_router_rejects_evaluation_that_exceeds_declared_history_range() -> None:
    report = make_report((evaluation("model-a", 1, test_end="2024-01-12"),))
    with pytest.raises(ValueError, match="extends beyond"):
        make_router().select(
            report,
            series_id="sku-1",
            forecast_origin="2024-01-13",
        )


def test_router_rejects_stale_or_mixed_model_versions() -> None:
    stale = make_report(
        (
            evaluation("model-a", 1, model_version="0.9"),
            evaluation("model-a", 2, model_version="0.9"),
        )
    )
    with pytest.raises(ValueError, match="registered adapter"):
        make_router().select(stale, series_id="sku-1", forecast_origin="2024-01-11")

    mixed = make_report(
        (
            evaluation("model-a", 1, model_version="1.0"),
            evaluation("model-a", 2, model_version="2.0"),
        )
    )
    with pytest.raises(ValueError, match="mixes model versions"):
        make_router().select(mixed, series_id="sku-1", forecast_origin="2024-01-11")


def test_router_rejects_duplicate_folds_and_timezone_mismatches() -> None:
    duplicate = make_report(
        (
            evaluation("model-a", 1),
            evaluation("model-a", 1),
        )
    )
    with pytest.raises(ValueError, match="duplicate fold"):
        make_router().select(duplicate, series_id="sku-1", forecast_origin="2024-01-11")

    with pytest.raises(ValueError, match="compatible timezone"):
        make_router().select(
            make_report(()),
            series_id="sku-1",
            forecast_origin="2024-01-11T00:00:00+00:00",
        )


def test_router_validates_registry_policy_and_series_inputs() -> None:
    with pytest.raises(ValueError, match="at least one"):
        ModelRouter([])
    with pytest.raises(ValueError, match="duplicate model_id"):
        ModelRouter([StubAdapter("same"), StubAdapter("same")])
    with pytest.raises(ValueError, match="fallback model"):
        ModelRouter([StubAdapter("model-a")])
    with pytest.raises(ValueError, match="positive integer"):
        ModelRouter([SeasonalNaiveAdapter()], min_folds=0)
    with pytest.raises(ValueError, match="finite and non-negative"):
        ModelRouter([SeasonalNaiveAdapter()], tie_tolerance=-1.0)
    with pytest.raises(ValueError, match="metric must"):
        ModelRouter([SeasonalNaiveAdapter()], metric="unknown")  # type: ignore[arg-type]

    router = make_router()
    report = make_report(())
    with pytest.raises(ValueError, match="series_id"):
        router.select(report, series_id=" ", forecast_origin="2024-01-11")
    with pytest.raises(ValueError, match="not present"):
        router.select(report, series_id="unknown", forecast_origin="2024-01-11")


def test_routing_artifact_is_deterministic_and_rejects_mixed_or_duplicate_series(
    tmp_path: Path,
) -> None:
    report = make_report(
        (
            evaluation("model-a", 1, wql=0.1),
            evaluation("model-a", 2, wql=0.2),
        )
    )
    router = make_router()
    decision = router.select(
        report,
        series_id="sku-1",
        forecast_origin="2024-01-11",
    )
    duplicate = replace(decision, series_id="sku-2")
    path = tmp_path / "nested" / "routing.json"

    first = write_routing_artifact((duplicate, decision), path)
    second = write_routing_artifact((decision, duplicate), path)

    assert first.sha256 == second.sha256
    assert path.stat().st_size == first.size_bytes
    assert path.read_bytes().endswith(b"\n")
    assert not path.with_name("routing.json.tmp").exists()

    with pytest.raises(ValueError, match="unique series_id"):
        write_routing_artifact((decision, decision), path)
    mixed = replace(decision, dataset_fingerprint="b" * 64)
    with pytest.raises(ValueError, match="same dataset"):
        write_routing_artifact((decision, mixed), path)
