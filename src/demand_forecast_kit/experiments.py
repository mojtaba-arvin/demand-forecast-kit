"""Canonical experiment manifests and stable fingerprints."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


def canonical_json(value: Any) -> str:
    """Serialize JSON-compatible values deterministically and reject NaN."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("experiment metadata must be finite JSON data") from exc


def fingerprint(value: Any) -> str:
    """Return a SHA-256 digest of canonical JSON."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ExperimentManifest:
    """Inputs that identify an evaluation independently of its output."""

    dataset_fingerprint: str
    split_config: dict[str, Any]
    model_versions: dict[str, str]
    metric_config: dict[str, Any]
    seed: int

    def __post_init__(self) -> None:
        if not self.dataset_fingerprint.strip():
            raise ValueError("dataset_fingerprint must not be blank")
        if type(self.seed) is not int or self.seed < 0:
            raise ValueError("seed must be a non-negative integer")
        if not self.model_versions or any(
            not name.strip() or not version.strip() for name, version in self.model_versions.items()
        ):
            raise ValueError("model_versions must contain non-blank model/version pairs")
        canonical_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical manifest payload."""
        return {
            "dataset_fingerprint": self.dataset_fingerprint,
            "split_config": self.split_config,
            "model_versions": self.model_versions,
            "metric_config": self.metric_config,
            "seed": self.seed,
        }

    @property
    def manifest_fingerprint(self) -> str:
        """Stable digest suitable for experiment identity and audit logs."""
        return fingerprint(self.to_dict())
