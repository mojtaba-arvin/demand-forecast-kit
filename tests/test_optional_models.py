from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from demand_forecast_kit.models import Chronos2Adapter, LightGBMAdapter
from demand_forecast_kit.models import chronos as chronos_module
from demand_forecast_kit.models import lightgbm as lightgbm_module
from demand_forecast_kit.models.registry import CHRONOS2_LICENSE


class FakeChronosPipeline:
    def __init__(self, output: Any) -> None:
        self.output = output
        self.calls: list[dict[str, Any]] = []

    def predict(self, **kwargs: Any) -> list[list[list[float]]]:
        self.calls.append(kwargs)
        return self.output


def test_chronos_adapter_converts_pinned_quantile_output() -> None:
    pipeline = FakeChronosPipeline([[[1.0, 2.0, 3.0], [2.0, 3.0, 4.0]]])
    adapter = Chronos2Adapter(pipeline=pipeline)
    result = adapter.predict(
        "sku-1",
        [1, 2, 3, 4],
        horizon=2,
        quantile_levels=(0.1, 0.5, 0.9),
        seed=7,
    )
    assert adapter.model_version == "amazon/chronos-2@29ec3766d36d6f73f0696f85560a422f50e8498c"
    assert result.quantiles[0.1] == (1.0, 2.0)
    assert result.quantiles[0.5] == (2.0, 3.0)
    assert result.quantiles[0.9] == (3.0, 4.0)
    assert pipeline.calls[0]["context"] == [[1.0, 2.0, 3.0, 4.0]]
    assert pipeline.calls[0]["prediction_length"] == 2


def test_chronos_clips_negative_demand_and_rejects_crossing_quantiles() -> None:
    clipped = Chronos2Adapter(pipeline=FakeChronosPipeline([[[-2.0, 0.0, 3.0]]])).predict(
        "sku", [1, 2], horizon=1, quantile_levels=(0.1, 0.5, 0.9), seed=0
    )
    assert tuple(clipped.quantiles[level][0] for level in (0.1, 0.5, 0.9)) == (0.0, 0.0, 3.0)
    crossing = Chronos2Adapter(pipeline=FakeChronosPipeline([[[3.0, 2.0, 4.0]]]))
    with pytest.raises(RuntimeError, match="crossing"):
        crossing.predict("sku", [1, 2], horizon=1, quantile_levels=(0.1, 0.5, 0.9), seed=0)


def test_chronos_requires_immutable_revision_and_offline_loading_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="40-character"):
        Chronos2Adapter(revision="main")
    with pytest.raises(ValueError, match="pinned to"):
        Chronos2Adapter(model_id="another/model")
    calls: list[dict[str, object]] = []

    class PipelineFactory:
        @staticmethod
        def from_pretrained(model_id: str, **kwargs: object) -> object:
            calls.append({"model_id": model_id, **kwargs})
            return object()

    monkeypatch.setattr(
        chronos_module,
        "import_module",
        lambda name: SimpleNamespace(Chronos2Pipeline=PipelineFactory),
    )
    Chronos2Adapter()._get_pipeline()
    assert calls == [
        {
            "model_id": CHRONOS2_LICENSE.model_id,
            "revision": CHRONOS2_LICENSE.revision,
            "device_map": "cpu",
            "local_files_only": True,
        }
    ]
    assert CHRONOS2_LICENSE.weight_license == "Apache-2.0"
    assert CHRONOS2_LICENSE.enabled_by_default is False
    assert CHRONOS2_LICENSE.downloads_enabled_by_default is False


class FakeDataset:
    def __init__(self, matrix: object, *, label: object, free_raw_data: bool) -> None:
        self.matrix = matrix
        self.label = label
        self.free_raw_data = free_raw_data


class FakeBooster:
    def __init__(self, alpha: float) -> None:
        self.alpha = alpha

    def predict(self, matrix: object) -> list[float]:
        return [0.0 if self.alpha == 0.9 else 20.0 if self.alpha == 0.1 else 10.0]


class FakeLightGBM:
    Dataset = FakeDataset

    @staticmethod
    def train(
        params: dict[str, object], dataset: FakeDataset, *, num_boost_round: int
    ) -> FakeBooster:
        assert params["objective"] == "quantile"
        assert params["num_threads"] == 1
        assert num_boost_round > 0
        return FakeBooster(float(params["alpha"]))


class FakeNumpy:
    float64 = float

    @staticmethod
    def asarray(values: object, *, dtype: object) -> object:
        return values


def test_lightgbm_adapter_trains_quantiles_and_rearranges_crossing_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lightgbm_module, "_load_lightgbm", lambda: (FakeLightGBM, FakeNumpy))
    result = LightGBMAdapter(num_boost_round=3).predict(
        "sku-1",
        [float(value) for value in range(1, 60)],
        horizon=2,
        quantile_levels=(0.1, 0.5, 0.9),
        seed=13,
    )
    assert result.quantiles[0.1] == (0.0, 0.0)
    assert result.quantiles[0.5] == (10.0, 10.0)
    assert result.quantiles[0.9] == (20.0, 20.0)


def test_lightgbm_uses_only_aligned_future_known_covariates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lightgbm_module, "_load_lightgbm", lambda: (FakeLightGBM, FakeNumpy))
    adapter = LightGBMAdapter(num_boost_round=2)
    history = [float(value) for value in range(1, 50)]
    with pytest.raises(ValueError, match="matching future-known"):
        adapter.predict_with_covariates(
            "sku",
            history,
            horizon=2,
            quantile_levels=(0.5,),
            seed=1,
            historical_covariates={"price": [10.0] * len(history)},
        )
    with pytest.raises(ValueError, match="align with horizon"):
        adapter.predict_with_covariates(
            "sku",
            history,
            horizon=2,
            quantile_levels=(0.5,),
            seed=1,
            historical_covariates={"price": [10.0] * len(history)},
            future_known_covariates={"price": [9.0]},
        )
    result = adapter.predict_with_covariates(
        "sku",
        history,
        horizon=2,
        quantile_levels=(0.5,),
        seed=1,
        historical_covariates={"price": [10.0] * len(history)},
        future_known_covariates={"price": [9.0, 8.0]},
    )
    assert result.horizon == 2


def test_lightgbm_validates_feature_history_before_loading_optional_dependency() -> None:
    with pytest.raises(ValueError, match="at least"):
        LightGBMAdapter().predict(
            "sku",
            [1, 2, 3],
            horizon=1,
            quantile_levels=(0.5,),
            seed=1,
        )


def test_lightgbm_adapter_runs_real_optional_backend() -> None:
    pytest.importorskip("lightgbm")
    adapter = LightGBMAdapter(
        lags=(1, 2, 3),
        rolling_windows=(2, 3),
        num_boost_round=10,
        num_leaves=7,
        min_data_in_leaf=2,
    )
    history = [float((index * 3) % 11) for index in range(50)]
    result = adapter.predict_with_covariates(
        "sku-real-lightgbm",
        history,
        horizon=3,
        quantile_levels=(0.1, 0.5, 0.9),
        seed=42,
        historical_covariates={"planned_price": [10.0 + index / 10 for index in range(50)]},
        future_known_covariates={"planned_price": (15.1, 15.2, 15.3)},
    )
    assert result.horizon == 3
    assert tuple(result.quantiles) == (0.1, 0.5, 0.9)
    for step in range(result.horizon):
        values = [result.quantiles[level][step] for level in (0.1, 0.5, 0.9)]
        assert values == sorted(values)
        assert all(value >= 0.0 for value in values)
    assert adapter.model_version.startswith("lightgbm-")


def test_lightgbm_routes_intermittent_history_to_specialized_adapter() -> None:
    adapter = LightGBMAdapter(intermittent_zero_fraction=0.8)
    history = [0.0] * 45 + [2.0, 1.0, 3.0, 0.0, 0.0]
    with pytest.raises(ValueError, match="route this series to an intermittent-demand adapter"):
        adapter.predict(
            "intermittent-sku",
            history,
            horizon=7,
            quantile_levels=(0.1, 0.5, 0.9),
            seed=42,
        )

def test_chronos_validates_request_arguments_before_inference() -> None:
    adapter = Chronos2Adapter(pipeline=FakeChronosPipeline([[[1.0, 2.0, 3.0]]]))
    with pytest.raises(ValueError, match="series_id"):
        adapter.predict("", [1, 2], horizon=1, quantile_levels=(0.1, 0.5, 0.9), seed=0)
    with pytest.raises(ValueError, match="horizon"):
        adapter.predict("sku", [1, 2], horizon=0, quantile_levels=(0.1, 0.5, 0.9), seed=0)
    with pytest.raises(ValueError, match="seed"):
        adapter.predict("sku", [1, 2], horizon=1, quantile_levels=(0.1, 0.5, 0.9), seed=-1)
    with pytest.raises(ValueError, match="history"):
        adapter.predict("sku", [], horizon=1, quantile_levels=(0.1, 0.5, 0.9), seed=0)
    with pytest.raises(ValueError, match="history"):
        adapter.predict("sku", [1, float("nan")], horizon=1, quantile_levels=(0.1, 0.5, 0.9), seed=0)
    with pytest.raises(ValueError, match="non-empty and unique"):
        adapter.predict("sku", [1, 2], horizon=1, quantile_levels=(), seed=0)
    with pytest.raises(ValueError, match="non-empty and unique"):
        adapter.predict("sku", [1, 2], horizon=1, quantile_levels=(0.5, 0.5), seed=0)
    with pytest.raises(ValueError, match="in"):
        adapter.predict("sku", [1, 2], horizon=1, quantile_levels=(1.0,), seed=0)
    with pytest.raises(ValueError, match="device_map"):
        Chronos2Adapter(device_map=" ")


@pytest.mark.parametrize(
    ("output", "message"),
    [
        ([], "batch dimension"),
        ([[]], "forecast horizon"),
        ([[[1.0, 2.0]]], "quantile dimension"),
        ([[["not-a-number", 2.0, 3.0]]], "non-numeric"),
        ([[[float("nan"), 2.0, 3.0]]], "non-finite"),
    ],
)
def test_chronos_rejects_malformed_pipeline_outputs(output: Any, message: str) -> None:
    adapter = Chronos2Adapter(pipeline=FakeChronosPipeline(output))
    with pytest.raises(RuntimeError, match=message):
        adapter.predict("sku", [1, 2], horizon=1, quantile_levels=(0.1, 0.5, 0.9), seed=0)


def test_chronos_missing_dependency_and_offline_cache_fail_actionably(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_dependency(name: str) -> Any:
        raise ImportError(name)

    monkeypatch.setattr(chronos_module, "import_module", missing_dependency)
    with pytest.raises(ImportError, match="demand-forecast-kit\\[chronos\\]"):
        Chronos2Adapter()._get_pipeline()

    class MissingCacheFactory:
        @staticmethod
        def from_pretrained(model_id: str, **kwargs: object) -> object:
            raise OSError("model files are not cached")

    monkeypatch.setattr(
        chronos_module,
        "import_module",
        lambda name: SimpleNamespace(Chronos2Pipeline=MissingCacheFactory),
    )
    with pytest.raises(RuntimeError, match="not cached"):
        Chronos2Adapter()._get_pipeline()


def test_chronos_explicit_download_preserves_upstream_loading_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DownloadFactory:
        @staticmethod
        def from_pretrained(model_id: str, **kwargs: object) -> object:
            raise OSError("upstream download failed")

    monkeypatch.setattr(
        chronos_module,
        "import_module",
        lambda name: SimpleNamespace(Chronos2Pipeline=DownloadFactory),
    )
    with pytest.raises(OSError, match="upstream download failed"):
        Chronos2Adapter(allow_download=True)._get_pipeline()
