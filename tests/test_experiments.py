import pytest

from demand_forecast_kit.experiments import ExperimentManifest, fingerprint


def _manifest(**overrides):
    values = {
        "dataset_fingerprint": "sha256:dataset",
        "split_config": {"horizon": 14, "step": 7},
        "model_versions": {"seasonal-naive": "0.1.0"},
        "metric_config": {"quantiles": [0.1, 0.5, 0.9]},
        "seed": 42,
    }
    values.update(overrides)
    return ExperimentManifest(**values)


def test_manifest_fingerprint_is_order_independent() -> None:
    left = _manifest(split_config={"horizon": 14, "step": 7})
    right = _manifest(split_config={"step": 7, "horizon": 14})

    assert left.manifest_fingerprint == right.manifest_fingerprint


def test_manifest_fingerprint_changes_with_any_experiment_input() -> None:
    baseline = _manifest()
    changed = _manifest(seed=43)

    assert baseline.manifest_fingerprint != changed.manifest_fingerprint


def test_fingerprint_rejects_non_finite_json() -> None:
    with pytest.raises(ValueError, match="finite JSON"):
        fingerprint({"value": float("nan")})


def test_manifest_rejects_invalid_seed_and_empty_model_versions() -> None:
    with pytest.raises(ValueError, match="seed"):
        _manifest(seed=-1)
    with pytest.raises(ValueError, match="model_versions"):
        _manifest(model_versions={})
