# Persistent model artifacts and activation

ModelArtifactRegistry stores opaque model bytes in a SHA-256 content-addressed
directory and immutable metadata/evaluation references in SQLite. It is a
single-host persistence primitive, not a distributed serving registry.

## Register a candidate

A candidate version is immutable and must be accompanied by non-empty
out-of-sample evaluation evidence, a finite non-negative validation MAE, and
a positive validation sample count:

    from demand_forecast_kit.model_registry import ModelArtifactRegistry

    registry = ModelArtifactRegistry("state/models.sqlite", "state/model-artifacts")
    candidate = registry.register_artifact(
        "my-forecast-model",
        "2026.11.1",
        model_bytes,
        evaluation_report=evaluation_json_bytes,
        media_type="application/vnd.example.forecast-model",
        validation_mae=2.41,
        validation_sample_count=840,
        metadata={"dataset_fingerprint": "sha256:...", "seed": 42},
    )

The registry does not assume a serialization format and never unpickles or
executes stored bytes. The application must provide a reviewed loader for its
own media type. Model bytes and evaluation reports are verified against their
SHA-256 digests every time they are read. Keep the SQLite database and artifact
directory on durable storage and back them up together.

## Explicit activation and rollback

Activation is an explicit operator/application decision, not a side effect of
successful training. Supply the version expected to be active to prevent a
stale controller from overwriting a newer decision:

    registry.activate("my-forecast-model", "2026.11.1", expected_active_version=None)
    registry.rollback(
        "my-forecast-model", "2026.10.4",
        expected_active_version="2026.11.1",
    )

Rollback names its target version; the registry does not guess which version
should be restored. Both operations append immutable history. A candidate must
already be registered, and its artifact/evaluation evidence remains available
after process restart. Activation state is not automatically wired into the
forecast worker: deployments must deliberately resolve the active version and
load it with their reviewed adapter factory. The default worker therefore
continues to use its existing deterministic fallback until that integration
and its deployment-specific tests are implemented.

## Boundaries

- SQLite and the local artifact directory are single-host components.
- This is not a multi-host consensus or distributed rollout service.
- Evaluation metrics are provenance supplied by the registering caller; the
  registry validates their shape, not the statistical validity of the experiment.
- No model is automatically activated because its validation MAE is lower.
