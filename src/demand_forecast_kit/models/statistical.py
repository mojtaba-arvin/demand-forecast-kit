"""Optional statistical forecasting adapters backed by Nixtla StatsForecast.

Install the optional dependency with `pip install "demand-forecast-kit[stats]"`.
Imports remain lazy so the core package does not require StatsForecast.
"""

from __future__ import annotations

from collections.abc import Sequence
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from math import isclose, isfinite
from types import ModuleType
from typing import Any, Literal

from demand_forecast_kit.contracts import QuantileForecast


def _positive_int(name: str, value: int) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _load_statsforecast() -> tuple[ModuleType, ModuleType]:
    """Import the optional backend only when an adapter is used."""
    try:
        return import_module("statsforecast.models"), import_module("statsforecast.utils")
    except ImportError as exc:
        raise ImportError(
            "Statistical adapters require the optional 'stats' dependency. "
            'Install it with: pip install "demand-forecast-kit[stats]"'
        ) from exc


def _statsforecast_version() -> str:
    try:
        return version("statsforecast")
    except PackageNotFoundError as exc:
        raise ImportError(
            "Statistical adapters require the optional 'stats' dependency. "
            'Install it with: pip install "demand-forecast-kit[stats]"'
        ) from exc


def _validated_inputs(
    series_id: str,
    history: Sequence[float],
    horizon: int,
    quantile_levels: Sequence[float],
    seed: int,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    if not isinstance(series_id, str) or not series_id.strip():
        raise ValueError("series_id must not be blank")
    _positive_int("horizon", horizon)
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a non-negative integer")

    values = tuple(float(value) for value in history)
    if not values:
        raise ValueError("history must contain at least one observation")
    if any(not isfinite(value) or value < 0.0 for value in values):
        raise ValueError("history values must be finite and non-negative")

    levels = tuple(float(level) for level in quantile_levels)
    if not levels or len(set(levels)) != len(levels):
        raise ValueError("quantile_levels must contain unique levels")
    if any(not isfinite(level) or not 0.0 < level < 1.0 for level in levels):
        raise ValueError("quantile levels must be finite and strictly between 0 and 1")
    return values, tuple(sorted(levels))


def _central_interval_levels(quantiles: Sequence[float]) -> tuple[int, ...]:
    """Map marginal quantiles to StatsForecast's symmetric central interval levels."""
    levels: set[int] = set()
    for quantile in quantiles:
        if isclose(quantile, 0.5, abs_tol=1e-12):
            continue
        confidence = 100.0 * (1.0 - 2.0 * min(quantile, 1.0 - quantile))
        rounded = round(confidence)
        if not isclose(confidence, rounded, abs_tol=1e-8) or not 1 <= rounded <= 99:
            raise ValueError(
                "StatsForecast adapters require quantile levels that map to integer "
                f"central interval percentages; unsupported quantile: {quantile:g}"
            )
        levels.add(int(rounded))
    return tuple(sorted(levels))


def _forecast_values(raw: Any, *, key: str, horizon: int) -> tuple[float, ...]:
    if raw is None:
        raise RuntimeError(f"StatsForecast did not return the expected {key!r} forecast field")
    values = tuple(float(value) for value in raw)
    if len(values) != horizon:
        raise RuntimeError(
            f"StatsForecast returned {len(values)} values for {key!r}; expected {horizon}"
        )
    if any(not isfinite(value) for value in values):
        raise RuntimeError(f"StatsForecast returned non-finite values for {key!r}")
    # Demand cannot be negative, even when an unconstrained Gaussian interval crosses zero.
    return tuple(max(0.0, value) for value in values)


class _StatsForecastAdapter:
    """Shared adapter logic for StatsForecast's univariate model classes."""

    _model_class_name: str
    _model_id: str
    _requires_conformal_intervals = False

    def __init__(self, *, conformal_windows: int = 2) -> None:
        _positive_int("conformal_windows", conformal_windows)
        if conformal_windows < 2:
            raise ValueError("conformal_windows must be at least 2")
        self.conformal_windows = conformal_windows

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def model_version(self) -> str:
        return f"statsforecast-{_statsforecast_version()}"

    def _model_kwargs(self) -> dict[str, Any]:
        return {}

    def _new_model(self, models_module: ModuleType, utils_module: ModuleType, horizon: int) -> Any:
        model_class = getattr(models_module, self._model_class_name)
        kwargs = self._model_kwargs()
        if self._requires_conformal_intervals:
            conformal_class = getattr(utils_module, "ConformalIntervals")
            kwargs["prediction_intervals"] = conformal_class(
                n_windows=self.conformal_windows,
                h=horizon,
            )
        return model_class(**kwargs)

    def predict(
        self,
        series_id: str,
        history: Sequence[float],
        *,
        horizon: int,
        quantile_levels: Sequence[float],
        seed: int,
    ) -> QuantileForecast:
        """Fit one series and return non-negative marginal quantile forecasts.

        StatsForecast's analytical/conformal interval bounds are interpreted as
        symmetric marginal quantiles around its point forecast. This is an
        explicit adapter convention, not a joint path or cumulative lead-time
        distribution. StatsForecast's model methods are deterministic; seed is
        validated for protocol compatibility and recorded by the backtest engine.
        """
        values, quantiles = _validated_inputs(
            series_id,
            history,
            horizon,
            quantile_levels,
            seed,
        )
        if all(value == 0.0 for value in values):
            zeros = tuple(0.0 for _ in range(horizon))
            return QuantileForecast(
                series_id=series_id,
                quantiles={level: zeros for level in quantiles},
            )

        requested_intervals = _central_interval_levels(quantiles)
        if self._requires_conformal_intervals and len(values) < (2 * horizon + 1):
            minimum = 2 * horizon + 1
            raise ValueError(
                f"{self.model_id} conformal intervals require at least {minimum} "
                f"training observations for horizon={horizon}; received {len(values)}"
            )

        models_module, utils_module = _load_statsforecast()
        model = self._new_model(models_module, utils_module, horizon)
        output = model.forecast(
            y=values,
            h=horizon,
            level=list(requested_intervals) if requested_intervals else None,
        )
        if not isinstance(output, dict):
            raise RuntimeError("StatsForecast returned an invalid forecast result")

        point = _forecast_values(output.get("mean"), key="mean", horizon=horizon)
        forecasts: dict[float, tuple[float, ...]] = {}
        for quantile in quantiles:
            if isclose(quantile, 0.5, abs_tol=1e-12):
                forecasts[quantile] = point
                continue
            interval = int(
                round(100.0 * (1.0 - 2.0 * min(quantile, 1.0 - quantile)))
            )
            bound = "lo" if quantile < 0.5 else "hi"
            key = f"{bound}-{interval}"
            forecasts[quantile] = _forecast_values(
                output.get(key),
                key=key,
                horizon=horizon,
            )

        return QuantileForecast(series_id=series_id, quantiles=forecasts)


class AutoETSAdapter(_StatsForecastAdapter):
    """Automatic error-trend-seasonality model with native prediction intervals."""

    _model_class_name = "AutoETS"
    _model_id = "auto-ets"

    def __init__(self, season_length: int = 1, model: str = "ZZZ") -> None:
        super().__init__()
        _positive_int("season_length", season_length)
        if not isinstance(model, str) or len(model) != 3:
            raise ValueError("model must be a three-character ETS specification")
        self.season_length = season_length
        self.model = model

    def _model_kwargs(self) -> dict[str, Any]:
        return {"season_length": self.season_length, "model": self.model}


class AutoARIMAAdapter(_StatsForecastAdapter):
    """Automatic ARIMA model search with native prediction intervals."""

    _model_class_name = "AutoARIMA"
    _model_id = "auto-arima"

    def __init__(
        self,
        season_length: int = 1,
        *,
        seasonal: bool = True,
        stepwise: bool = True,
        max_p: int = 5,
        max_q: int = 5,
        max_P: int = 2,
        max_Q: int = 2,
        max_order: int = 5,
        nmodels: int = 94,
    ) -> None:
        super().__init__()
        _positive_int("season_length", season_length)
        for name, value in (
            ("max_p", max_p),
            ("max_q", max_q),
            ("max_P", max_P),
            ("max_Q", max_Q),
            ("max_order", max_order),
            ("nmodels", nmodels),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if nmodels < 1:
            raise ValueError("nmodels must be a positive integer")
        if type(seasonal) is not bool or type(stepwise) is not bool:
            raise ValueError("seasonal and stepwise must be booleans")
        self.season_length = season_length
        self.seasonal = seasonal
        self.stepwise = stepwise
        self.max_p = max_p
        self.max_q = max_q
        self.max_P = max_P
        self.max_Q = max_Q
        self.max_order = max_order
        self.nmodels = nmodels

    def _model_kwargs(self) -> dict[str, Any]:
        return {
            "season_length": self.season_length,
            "seasonal": self.seasonal,
            "stepwise": self.stepwise,
            "max_p": self.max_p,
            "max_q": self.max_q,
            "max_P": self.max_P,
            "max_Q": self.max_Q,
            "max_order": self.max_order,
            "nmodels": self.nmodels,
        }


class ThetaAdapter(_StatsForecastAdapter):
    """Standard Theta forecasting model with native prediction intervals."""

    _model_class_name = "Theta"
    _model_id = "theta"

    def __init__(
        self,
        season_length: int = 1,
        decomposition_type: Literal["additive", "multiplicative"] = "additive",
    ) -> None:
        super().__init__()
        _positive_int("season_length", season_length)
        if decomposition_type not in {"additive", "multiplicative"}:
            raise ValueError("decomposition_type must be 'additive' or 'multiplicative'")
        self.season_length = season_length
        self.decomposition_type = decomposition_type

    def _model_kwargs(self) -> dict[str, Any]:
        return {
            "season_length": self.season_length,
            "decomposition_type": self.decomposition_type,
        }


class CrostonAdapter(_StatsForecastAdapter):
    """Intermittent-demand Croston model with conformal prediction intervals.

    The default variant is CrostonOptimized. Set variant to 'classic' or 'sba'
    to use the original or Syntetos-Boylan approximation variants.
    """

    _requires_conformal_intervals = True

    def __init__(
        self,
        variant: Literal["classic", "optimized", "sba"] = "optimized",
        *,
        conformal_windows: int = 2,
    ) -> None:
        super().__init__(conformal_windows=conformal_windows)
        names = {
            "classic": ("CrostonClassic", "croston-classic"),
            "optimized": ("CrostonOptimized", "croston-optimized"),
            "sba": ("CrostonSBA", "croston-sba"),
        }
        if variant not in names:
            raise ValueError("variant must be 'classic', 'optimized', or 'sba'")
        self.variant = variant
        self._model_class_name, self._model_id = names[variant]


class TSBAdapter(_StatsForecastAdapter):
    """Teunter-Syntetos-Babai intermittent-demand model.

    Conformal intervals are fitted from rolling calibration windows within the
    supplied training history. At least two complete calibration windows are
    required; the model never uses the held-out backtest horizon.
    """

    _model_class_name = "TSB"
    _model_id = "tsb"
    _requires_conformal_intervals = True

    def __init__(
        self,
        alpha_d: float = 0.2,
        alpha_p: float = 0.2,
        *,
        conformal_windows: int = 2,
    ) -> None:
        super().__init__(conformal_windows=conformal_windows)
        if not isfinite(alpha_d) or not 0.0 < alpha_d <= 1.0:
            raise ValueError("alpha_d must be finite and in (0, 1]")
        if not isfinite(alpha_p) or not 0.0 < alpha_p <= 1.0:
            raise ValueError("alpha_p must be finite and in (0, 1]")
        self.alpha_d = float(alpha_d)
        self.alpha_p = float(alpha_p)

    def _model_kwargs(self) -> dict[str, Any]:
        return {"alpha_d": self.alpha_d, "alpha_p": self.alpha_p}
