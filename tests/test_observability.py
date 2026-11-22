from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor

import pytest

from demand_forecast_kit.observability import InMemoryMetrics, JsonLogFormatter


def test_json_log_formatter_preserves_safe_context() -> None:
    record = logging.LogRecord("forecast", logging.INFO, __file__, 10, "run %s", ("42",), None)
    record.run_id = 42
    record.non_serializable = object()

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["logger"] == "forecast"
    assert payload["message"] == "run 42"
    assert payload["run_id"] == 42
    assert "non_serializable" not in payload


def test_metrics_are_thread_safe_and_snapshots_are_detached() -> None:
    metrics = InMemoryMetrics()

    def record(_: int) -> None:
        metrics.increment("forecast.completed")
        metrics.observe("forecast.duration_ms", 12.5)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(record, range(500)))

    snapshot = metrics.snapshot()
    assert snapshot["counters"]["forecast.completed"] == 500
    assert snapshot["observations"]["forecast.duration_ms"] == {
        "count": 500,
        "sum": 6250,
        "min": 12.5,
        "max": 12.5,
    }
    snapshot["counters"]["forecast.completed"] = 0
    assert metrics.snapshot()["counters"]["forecast.completed"] == 500


@pytest.mark.parametrize("amount", [-1.0, float("nan"), float("inf")])
def test_metrics_reject_invalid_values(amount: float) -> None:
    metrics = InMemoryMetrics()

    with pytest.raises(ValueError):
        metrics.increment("requests", amount)
    with pytest.raises(ValueError):
        metrics.observe("latency", amount)


def test_metrics_reject_invalid_names() -> None:
    metrics = InMemoryMetrics()

    with pytest.raises(ValueError, match="metric name"):
        metrics.increment(" ")
