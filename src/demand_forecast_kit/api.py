"""Optional FastAPI surface for forecast, backtest, and replenishment contracts."""

import json
from datetime import date
from math import isfinite
from typing import Any

import polars as pl

from demand_forecast_kit.run_service import RunService


def create_app(run_service: RunService | None = None) -> Any:
    """Create the API application; FastAPI remains an optional dependency."""
    service = run_service or RunService.from_environment()
    try:
        from fastapi import FastAPI, HTTPException, Response
        from pydantic import BaseModel, ConfigDict, Field, field_validator
    except ImportError as exc:
        raise RuntimeError("install demand-forecast-kit[api] to use the HTTP API") from exc

    from demand_forecast_kit.backtesting import BacktestConfig, run_backtest
    from demand_forecast_kit.decisions import newsvendor_order
    from demand_forecast_kit.models.seasonal_naive import SeasonalNaiveAdapter

    class ForecastRequest(BaseModel):
        model_config = ConfigDict(extra="forbid")

        series_id: str = Field(min_length=1)
        history: list[float] = Field(min_length=1, max_length=100_000)
        horizon: int = Field(default=14, ge=1, le=3650)
        season_length: int = Field(default=7, ge=1, le=3650)
        quantiles: list[float] = Field(default_factory=lambda: [0.1, 0.5, 0.9])

        @field_validator("series_id")
        @classmethod
        def non_blank_series(cls, value: str) -> str:
            if not value.strip():
                raise ValueError("series_id must not be blank")
            return value

        @field_validator("history")
        @classmethod
        def finite_non_negative_history(cls, values: list[float]) -> list[float]:
            if any(not isfinite(value) or value < 0.0 for value in values):
                raise ValueError("history must contain finite non-negative demand")
            return values

        @field_validator("quantiles")
        @classmethod
        def valid_quantiles(cls, values: list[float]) -> list[float]:
            if (
                not values
                or any(not isfinite(value) or not 0.0 < value < 1.0 for value in values)
                or len(set(values)) != len(values)
                or 0.5 not in values
            ):
                raise ValueError("quantiles must be unique finite levels in (0, 1), including 0.5")
            return sorted(values)

    class Observation(BaseModel):
        model_config = ConfigDict(extra="forbid")

        timestamp: date
        demand: float = Field(ge=0)

        @field_validator("demand")
        @classmethod
        def finite_demand(cls, value: float) -> float:
            if not isfinite(value):
                raise ValueError("demand must be finite")
            return value

    class BacktestRequest(BaseModel):
        model_config = ConfigDict(extra="forbid")

        series_id: str = Field(min_length=1)
        observations: list[Observation] = Field(min_length=3, max_length=100_000)
        initial_train_size: int = Field(default=30, ge=2)
        horizon: int = Field(default=7, ge=1)
        step: int = Field(default=1, ge=1)
        season_length: int = Field(default=7, ge=1)
        quantiles: list[float] = Field(default_factory=lambda: [0.1, 0.5, 0.9])

        @field_validator("series_id")
        @classmethod
        def non_blank_series(cls, value: str) -> str:
            if not value.strip():
                raise ValueError("series_id must not be blank")
            return value

        @field_validator("quantiles")
        @classmethod
        def valid_quantiles(cls, values: list[float]) -> list[float]:
            if (
                not values
                or any(not isfinite(value) or not 0.0 < value < 1.0 for value in values)
                or len(set(values)) != len(values)
                or 0.5 not in values
            ):
                raise ValueError("quantiles must be unique finite levels in (0, 1), including 0.5")
            return sorted(values)

    class ReplenishmentRequest(BaseModel):
        model_config = ConfigDict(extra="forbid")

        lead_time_demand_quantiles: dict[float, float]
        underage_cost: float = Field(gt=0)
        overage_cost: float = Field(gt=0)
        inventory_position: float
        pack_size: int = Field(default=1, ge=1)
        run_id: int | None = Field(default=None, ge=1)
        decision_key: str | None = Field(default=None, min_length=1, max_length=512)

        @field_validator("underage_cost", "overage_cost", "inventory_position")
        @classmethod
        def finite_costs_and_position(cls, value: float) -> float:
            if not isfinite(value):
                raise ValueError("costs and inventory_position must be finite")
            return value

    app = FastAPI(
        title="Demand Forecast Kit",
        version="0.1.0",
        description="Probabilistic demand forecasting and replenishment primitives.",
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/v1/runs/{run_id}")
    def get_run(run_id: int) -> dict[str, object]:
        """Retrieve persisted execution metadata and its JSON result."""
        try:
            run = service.registry.get_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        return {
            "run_id": run.run_id,
            "status": run.status,
            "dataset_fingerprint": run.dataset_fingerprint,
            "model_id": run.model_id,
            "model_version": run.model_version,
            "created_at": run.created_at,
            "config": run.config,
            "result": run.result,
        }

    @app.get("/v1/runs/{run_id}/decisions")
    def get_run_decisions(run_id: int) -> dict[str, object]:
        """List immutable inventory decisions linked to a persisted run."""
        try:
            decisions = service.registry.list_inventory_decisions(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        return {
            "run_id": run_id,
            "decisions": [
                {
                    "decision_id": item.decision_id,
                    "run_id": item.run_id,
                    "decision_key": item.decision_key,
                    "created_at": item.created_at,
                    "decision": item.decision,
                }
                for item in decisions
            ],
        }

    @app.get("/v1/artifacts/{sha256}")
    def get_artifact(sha256: str) -> Response:
        """Retrieve a content-addressed artifact after verifying its SHA-256 digest."""
        try:
            payload = service.artifacts.get(sha256)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="artifact not found") from exc
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail="artifact integrity verification failed",
            ) from exc
        return Response(
            content=payload,
            media_type="application/json",
            headers={
                "ETag": f'"{sha256}"',
                "Cache-Control": "private, immutable",
            },
        )

    @app.post("/v1/forecasts")
    def forecast(request: ForecastRequest) -> dict[str, object]:
        adapter = SeasonalNaiveAdapter(season_length=request.season_length)
        result = adapter.predict(
            request.series_id,
            request.history,
            horizon=request.horizon,
            quantile_levels=request.quantiles,
            seed=0,
        )
        payload: dict[str, object] = {
            "series_id": result.series_id,
            "model_id": adapter.model_id,
            "model_version": adapter.model_version,
            "horizon": result.horizon,
            "quantiles": {str(level): list(values) for level, values in result.quantiles.items()},
        }
        config = {
            "horizon": request.horizon,
            "season_length": request.season_length,
            "quantiles": request.quantiles,
            "seed": 0,
        }
        dataset_bytes = json.dumps(
            {"series_id": request.series_id, "history": request.history},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        dataset_fingerprint = service.fingerprint(dataset_bytes)
        run = service.record_run(
            idempotency_key=service.idempotency_key(
                dataset_fingerprint=dataset_fingerprint,
                model_id=adapter.model_id,
                model_version=adapter.model_version,
                config=config,
            ),
            dataset_fingerprint=dataset_fingerprint,
            model_id=adapter.model_id,
            model_version=adapter.model_version,
            config=config,
            result=payload,
            artifact_payload=json.dumps(
                payload, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8"),
        )
        return {**payload, "run": run.to_dict()}

    @app.post("/v1/backtests")
    def backtest(request: BacktestRequest) -> dict[str, object]:
        if len(request.observations) < request.initial_train_size + request.horizon:
            raise HTTPException(
                status_code=422,
                detail="observations must cover initial_train_size plus one complete horizon",
            )
        timestamps = [item.timestamp for item in request.observations]
        if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
            raise HTTPException(
                status_code=422,
                detail="observation timestamps must be unique and strictly chronological",
            )
        history = pl.DataFrame(
            {
                "series_id": [request.series_id] * len(request.observations),
                "timestamp": timestamps,
                "demand": [item.demand for item in request.observations],
            }
        )
        backtest_config = BacktestConfig(
            initial_train_size=request.initial_train_size,
            horizon=request.horizon,
            step=request.step,
            season_length=request.season_length,
            quantile_levels=tuple(request.quantiles),
            coverage_levels=(),
        )
        report = run_backtest(
            history,
            [SeasonalNaiveAdapter(season_length=request.season_length)],
            backtest_config,
        )
        payload = report.to_dict()
        run_config = {
            "initial_train_size": request.initial_train_size,
            "horizon": request.horizon,
            "step": request.step,
            "season_length": request.season_length,
            "quantiles": request.quantiles,
        }
        run = service.record_run(
            idempotency_key=service.idempotency_key(
                dataset_fingerprint=report.dataset_fingerprint,
                model_id=report.model_summaries[0].model_id,
                model_version=report.model_summaries[0].model_version,
                config=run_config,
            ),
            dataset_fingerprint=report.dataset_fingerprint,
            model_id=report.model_summaries[0].model_id,
            model_version=report.model_summaries[0].model_version,
            config=run_config,
            result=payload,
            artifact_payload=report.to_json_bytes(),
        )
        return {**payload, "run": run.to_dict()}

    @app.post("/v1/replenishment/recommendations")
    def replenishment(request: ReplenishmentRequest) -> dict[str, object]:
        try:
            result = newsvendor_order(
                request.lead_time_demand_quantiles,
                underage_cost=request.underage_cost,
                overage_cost=request.overage_cost,
                inventory_position=request.inventory_position,
                pack_size=request.pack_size,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        payload: dict[str, object] = {
            "quantity": result.quantity,
            "target_stock_level": result.target_stock_level,
            "inventory_position": result.inventory_position,
            "target_service_level": result.target_service_level,
            "unrounded_quantity": result.unrounded_quantity,
        }
        if (request.run_id is None) != (request.decision_key is None):
            raise HTTPException(
                status_code=422,
                detail="run_id and decision_key must be provided together",
            )
        if request.run_id is not None and request.decision_key is not None:
            try:
                payload["decision"] = service.record_inventory_decision(
                    request.run_id,
                    decision_key=request.decision_key,
                    decision=payload,
                )
            except (KeyError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        return payload

    from demand_forecast_kit.operations_api import build_operations_router, install_api_auth

    install_api_auth(app)
    app.include_router(build_operations_router(service))

    app.state.run_service = service
    return app
