from __future__ import annotations

import hashlib
import os
from pathlib import Path

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

    with pytest.raises(TypeError, match="encoded"):
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


def test_artifact_store_rejects_symlinked_artifact_file(tmp_path) -> None:
    root = tmp_path / "artifacts"
    store = FileArtifactStore(root)
    artifact = store.put(b"payload")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"payload")
    path = store.root / artifact.path
    path.unlink()
    path.symlink_to(outside)

    with pytest.raises(OSError, match="symbolic link"):
        store.get(artifact.sha256)


def test_artifact_store_handles_concurrent_identical_write(tmp_path, monkeypatch) -> None:
    root = tmp_path / "artifacts"
    store = FileArtifactStore(root)
    payload = b"concurrent"
    digest = hashlib.sha256(payload).hexdigest()
    target = root / digest[:2] / digest[2:]
    target.parent.mkdir(parents=True)

    def concurrent_link(source: str, destination: str) -> None:
        Path(destination).write_bytes(payload)
        raise FileExistsError(destination)

    monkeypatch.setattr(os, "link", concurrent_link)
    artifact = store.put(payload)

    assert artifact.sha256 == digest
    assert store.get(digest) == payload
