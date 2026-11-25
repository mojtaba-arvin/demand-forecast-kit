import sqlite3

import pytest

from demand_forecast_kit.model_registry import ModelArtifactRegistry


def _register(registry: ModelArtifactRegistry, version: str) -> None:
    registry.register_artifact(
        "demand-model",
        version,
        f"opaque-model-bytes:{version}".encode(),
        evaluation_report=f"out-of-sample-report:{version}".encode(),
        media_type="application/vnd.example.model",
        validation_mae=1.25,
        validation_sample_count=120,
        metadata={"dataset_fingerprint": "sha256:dataset", "seed": 7},
    )


def test_artifacts_and_evaluation_evidence_survive_registry_restart(tmp_path) -> None:
    database = tmp_path / "registry.sqlite"
    artifact_root = tmp_path / "artifacts"
    registry = ModelArtifactRegistry(database, artifact_root)
    _register(registry, "v1")

    restarted = ModelArtifactRegistry(database, artifact_root)
    record = restarted.get_artifact("demand-model", "v1")

    assert record.validation_mae == 1.25
    assert record.validation_sample_count == 120
    assert record.metadata == {"dataset_fingerprint": "sha256:dataset", "seed": 7}
    assert restarted.read_artifact("demand-model", "v1") == b"opaque-model-bytes:v1"
    assert restarted.read_evaluation_report("demand-model", "v1") == b"out-of-sample-report:v1"


def test_register_is_idempotent_but_model_versions_are_immutable(tmp_path) -> None:
    registry = ModelArtifactRegistry(tmp_path / "registry.sqlite", tmp_path / "artifacts")
    _register(registry, "v1")
    original = registry.get_artifact("demand-model", "v1")
    _register(registry, "v1")
    assert registry.get_artifact("demand-model", "v1") == original

    with pytest.raises(ValueError, match="different content or evidence"):
        registry.register_artifact(
            "demand-model", "v1", b"different-model-bytes",
            evaluation_report=b"out-of-sample-report:v1",
            media_type="application/vnd.example.model",
            validation_mae=1.25, validation_sample_count=120,
            metadata={"dataset_fingerprint": "sha256:dataset", "seed": 7},
        )


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"payload": b""}, "payload"),
        ({"evaluation_report": b""}, "evaluation_report"),
        ({"validation_mae": float("nan")}, "validation_mae"),
        ({"validation_mae": -1.0}, "validation_mae"),
        ({"validation_sample_count": 0}, "validation_sample_count"),
        ({"metadata": {"invalid": float("inf")}}, "finite JSON"),
    ],
)
def test_registration_rejects_invalid_artifact_evidence(tmp_path, kwargs, message) -> None:
    registry = ModelArtifactRegistry(tmp_path / "registry.sqlite", tmp_path / "artifacts")
    values = {
        "payload": b"model", "evaluation_report": b"report",
        "validation_mae": 1.0, "validation_sample_count": 10, "metadata": {},
    }
    values.update(kwargs)
    with pytest.raises(ValueError, match=message):
        registry.register_artifact(
            "model", "v1", values["payload"],
            evaluation_report=values["evaluation_report"],
            media_type="application/octet-stream",
            validation_mae=values["validation_mae"],
            validation_sample_count=values["validation_sample_count"],
            metadata=values["metadata"],
        )


def test_activation_requires_expected_version_and_supports_rollback(tmp_path) -> None:
    database = tmp_path / "registry.sqlite"
    artifact_root = tmp_path / "artifacts"
    registry = ModelArtifactRegistry(database, artifact_root)
    _register(registry, "v1")
    _register(registry, "v2")

    first = registry.activate("demand-model", "v1", expected_active_version=None)
    assert first.action == "activate"
    assert first.previous_model_version is None
    assert registry.get_active("demand-model").model_version == "v1"

    second = registry.activate("demand-model", "v2", expected_active_version="v1")
    assert second.previous_model_version == "v1"
    assert registry.get_active("demand-model").model_version == "v2"

    with pytest.raises(ValueError, match="version changed"):
        registry.rollback("demand-model", "v1", expected_active_version="v1")
    rolled_back = registry.rollback("demand-model", "v1", expected_active_version="v2")
    assert rolled_back.action == "rollback"
    assert rolled_back.previous_model_version == "v2"

    restarted = ModelArtifactRegistry(database, artifact_root)
    assert restarted.get_active("demand-model").model_version == "v1"
    assert [event.action for event in restarted.activation_history("demand-model")] == [
        "activate", "activate", "rollback",
    ]


def test_activation_is_idempotent_and_requires_registered_version(tmp_path) -> None:
    registry = ModelArtifactRegistry(tmp_path / "registry.sqlite", tmp_path / "artifacts")
    with pytest.raises(KeyError, match="artifact not found"):
        registry.activate("model", "missing", expected_active_version=None)

    _register(registry, "v1")
    first = registry.activate("demand-model", "v1", expected_active_version=None)
    unchanged = registry.activate("demand-model", "v1", expected_active_version="v1")
    assert first.event_id is not None
    assert unchanged.event_id is None
    assert unchanged.action == "unchanged"
    assert len(registry.activation_history("demand-model")) == 1


def test_artifact_bytes_are_verified_on_read(tmp_path) -> None:
    artifact_root = tmp_path / "artifacts"
    registry = ModelArtifactRegistry(tmp_path / "registry.sqlite", artifact_root)
    _register(registry, "v1")
    record = registry.get_artifact("demand-model", "v1")
    path = artifact_root / record.artifact_sha256[:2] / record.artifact_sha256[2:]
    path.write_bytes(b"tampered")

    with pytest.raises(OSError, match="integrity"):
        registry.read_artifact("demand-model", "v1")


def test_artifact_metadata_and_activation_history_are_immutable(tmp_path) -> None:
    database = tmp_path / "registry.sqlite"
    registry = ModelArtifactRegistry(database, tmp_path / "artifacts")
    _register(registry, "v1")
    registry.activate("demand-model", "v1", expected_active_version=None)

    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="model artifacts are immutable"):
            connection.execute(
                "UPDATE model_artifacts SET validation_mae=0 WHERE model_id=?",
                ("demand-model",),
            )
        with pytest.raises(sqlite3.IntegrityError, match="model activation events are immutable"):
            connection.execute(
                "DELETE FROM model_activation_events WHERE model_id=?",
                ("demand-model",),
            )
