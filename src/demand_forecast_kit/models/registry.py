"""License and provenance metadata for optional pretrained forecasting models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelLicenseRecord:
    """Auditable model-weight license and loading policy."""

    model_id: str
    revision: str
    weight_license: str
    source_url: str
    license_url: str
    enabled_by_default: bool
    downloads_enabled_by_default: bool
    package: str
    package_version: str


CHRONOS2_LICENSE = ModelLicenseRecord(
    model_id="amazon/chronos-2",
    revision="29ec3766d36d6f73f0696f85560a422f50e8498c",
    weight_license="Apache-2.0",
    source_url="https://huggingface.co/amazon/chronos-2",
    license_url="https://huggingface.co/amazon/chronos-2",
    enabled_by_default=False,
    downloads_enabled_by_default=False,
    package="chronos-forecasting",
    package_version="2.3.2",
)
