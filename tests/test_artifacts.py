from __future__ import annotations

import hashlib

import pytest

from demand_forecast_kit.artifacts import FileArtifactStore


def test_artifact_store_is_content_addressed_and_idempotent(tmp_path) -> None:
    store = FileArtifactStore(tmp_path / "artifacts")
    payload = b'{"forecast":[1,2,3]}'

    first = store.put(payload)
    second = store.put(payload)

    assert first == second
    assert first.sha256 == hashlib.sha256(payload).hexdigest()
    assert first.size_bytes == len(payload)
    assert store.get(first.sha256) == payload


def test_artifact_store_rejects_invalid_digest(tmp_path) -> None:
    store = FileArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ValueError, match="64-character"):
        store.get("../escape")


def test_artifact_store_detects_corruption(tmp_path) -> None:
    store = FileArtifactStore(tmp_path / "artifacts")
    artifact = store.put(b"original")
    path = store.root / artifact.path
    path.write_bytes(b"tampered")

    with pytest.raises(OSError, match="integrity"):
        store.get(artifact.sha256)


def test_artifact_store_rejects_non_bytes(tmp_path) -> None:
    store = FileArtifactStore(tmp_path / "artifacts")

    with pytest.raises(TypeError, match="bytes"):
        store.put("not bytes")  # type: ignore[arg-type]


def test_artifact_store_rejects_symlinked_digest_directory(tmp_path) -> None:
    root = tmp_path / "artifacts"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    store = FileArtifactStore(root)
    digest = hashlib.sha256(b"payload").hexdigest()
    (root / digest[:2]).symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError, match="directory"):
        store.put(b"payload")
    with pytest.raises(OSError, match="directory"):
        store.get(digest)
