"""Optional, offline-first Amazon Chronos-2 foundation-model adapter."""

from __future__ import annotations

from collections.abc import Sequence
from importlib import import_module
from math import isfinite
from typing import Any

from demand_forecast_kit.contracts import QuantileForecast
from demand_forecast_kit.models.registry import CHRONOS2_LICENSE


class Chronos2Adapter:
    """Chronos-2 adapter pinned to an immutable model revision.

    Weight downloads are disabled by default. The exact revision must already
    exist in the local Hugging Face cache unless allow_download=True is explicit.
    A pipeline can be injected for tests or controlled hosting environments.
    """

    def __init__(
        self,
        *,
        revision: str = CHRONOS2_LICENSE.revision,
        model_id: str = CHRONOS2_LICENSE.model_id,
        device_map: str = "cpu",
        allow_download: bool = False,
        pipeline: Any | None = None,
    ) -> None:
        if not revision or len(revision) != 40 or any(
            character not in "0123456789abcdef" for character in revision.lower()
        ):
            raise ValueError("revision must be an immutable 40-character model commit SHA")
        if model_id != CHRONOS2_LICENSE.model_id:
            raise ValueError("this adapter is pinned to the licensed amazon/chronos-2 model")
        if not device_map.strip():
            raise ValueError("device_map must not be blank")
        self.revision = revision.lower()
        self.model_id = model_id
        self.device_map = device_map
        self.allow_download = allow_download
        self._pipeline = pipeline

    @property
    def model_version(self) -> str:
        return f"{self.model_id}@{self.revision}"

    def _get_pipeline(self) -> Any:
        if self._pipeline is None:
            try:
                chronos = import_module("chronos")
            except ImportError as exc:
                raise ImportError(
                    'Chronos2Adapter requires the optional dependency. Install it with: '
                    'pip install "demand-forecast-kit[chronos]"'
                ) from exc
            try:
                self._pipeline = chronos.Chronos2Pipeline.from_pretrained(
                    self.model_id,
                    revision=self.revision,
                    device_map=self.device_map,
                    local_files_only=not self.allow_download,
                )
            except OSError as exc:
                if not self.allow_download:
                    raise RuntimeError(
                        "Chronos-2 weights are not cached for the pinned revision. "
                        "Install/cache them explicitly, or construct with allow_download=True."
                    ) from exc
                raise
        return self._pipeline

    def predict(
        self,
        series_id: str,
        history: Sequence[float],
        *,
        horizon: int,
        quantile_levels: Sequence[float],
        seed: int,
    ) -> QuantileForecast:
        """Return Chronos-2 marginal quantiles; fixed inputs/revision are deterministic."""
        if not series_id.strip():
            raise ValueError("series_id must not be blank")
        if type(horizon) is not int or horizon < 1:
            raise ValueError("horizon must be a positive integer")
        if type(seed) is not int or seed < 0:
            raise ValueError("seed must be a non-negative integer")
        values = tuple(float(value) for value in history)
        if not values or any(not isfinite(value) or value < 0.0 for value in values):
            raise ValueError("history must contain finite non-negative demand")
        levels = tuple(sorted(float(value) for value in quantile_levels))
        if not levels or len(set(levels)) != len(levels):
            raise ValueError("quantile_levels must be non-empty and unique")
        if any(not isfinite(level) or not 0.0 < level < 1.0 for level in levels):
            raise ValueError("quantile levels must be finite and in (0, 1)")

        raw = self._get_pipeline().predict(
            context=[list(values)],
            prediction_length=horizon,
            quantile_levels=list(levels),
        )
        if hasattr(raw, "detach"):
            raw = raw.detach().cpu().tolist()
        elif hasattr(raw, "tolist"):
            raw = raw.tolist()
        if not isinstance(raw, (list, tuple)) or len(raw) != 1:
            raise RuntimeError("Chronos-2 returned an invalid batch dimension")
        rows = raw[0]
        if not isinstance(rows, (list, tuple)) or len(rows) != horizon:
            raise RuntimeError("Chronos-2 returned an invalid forecast horizon")
        values_by_level: dict[float, list[float]] = {level: [] for level in levels}
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) != len(levels):
                raise RuntimeError("Chronos-2 returned an invalid quantile dimension")
            converted = tuple(float(value) for value in row)
            if any(not isfinite(value) for value in converted):
                raise RuntimeError("Chronos-2 returned non-finite forecasts")
            non_negative = tuple(max(0.0, value) for value in converted)
            if any(left > right for left, right in zip(non_negative, non_negative[1:], strict=False)):
                raise RuntimeError("Chronos-2 returned crossing quantiles")
            for level, value in zip(levels, non_negative, strict=True):
                values_by_level[level].append(value)
        forecasts = {level: tuple(values) for level, values in values_by_level.items()}
        return QuantileForecast(series_id=series_id, quantiles=forecasts)
