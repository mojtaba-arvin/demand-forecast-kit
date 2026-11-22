"""Dependency-free structured logging and process-local metrics primitives."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import UTC, datetime
from math import isfinite
from threading import Lock
from typing import Any, TypedDict


class MetricsSnapshot(TypedDict):
    """Stable shape of the process-local metrics snapshot."""

    counters: dict[str, float]
    observations: dict[str, dict[str, float]]


class JsonLogFormatter(logging.Formatter):
    """Format log records as one JSON object per line."""

    _reserved = frozenset(logging.makeLogRecord({}).__dict__) | {
        "message",
        "asctime",
        "msg",
        "args",
        "exc_info",
        "exc_text",
        "stack_info",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in self._reserved and not key.startswith("_"):
                try:
                    json.dumps(value, allow_nan=False)
                except (TypeError, ValueError):
                    continue
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


class InMemoryMetrics:
    """Thread-safe counters and distribution summaries for one process.

    This deliberately avoids unbounded label dimensions. Export the snapshot
    through an application-specific endpoint or monitoring adapter.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[str, float] = defaultdict(float)
        self._observations: dict[str, list[float]] = defaultdict(
            lambda: [0.0, 0.0, float("inf"), float("-inf")]
        )

    @staticmethod
    def _name(name: str) -> str:
        normalized = name.strip()
        if not normalized or any(character.isspace() for character in normalized):
            raise ValueError("metric name must be non-blank and contain no whitespace")
        return normalized

    def increment(self, name: str, amount: float = 1.0) -> None:
        """Increase a counter by a finite, non-negative amount."""
        metric = self._name(name)
        if not isfinite(amount) or amount < 0.0:
            raise ValueError("counter amount must be finite and non-negative")
        with self._lock:
            self._counters[metric] += amount

    def observe(self, name: str, value: float) -> None:
        """Record one finite measurement as count, sum, min, and max."""
        metric = self._name(name)
        if not isfinite(value):
            raise ValueError("metric observation must be finite")
        with self._lock:
            summary = self._observations[metric]
            summary[0] += 1.0
            summary[1] += value
            summary[2] = min(summary[2], value)
            summary[3] = max(summary[3], value)

    def snapshot(self) -> MetricsSnapshot:
        """Return a detached, deterministic snapshot of current measurements."""
        with self._lock:
            counters = dict(sorted(self._counters.items()))
            observations = {
                name: {
                    "count": values[0],
                    "sum": values[1],
                    "min": values[2],
                    "max": values[3],
                }
                for name, values in sorted(self._observations.items())
            }
        return {"counters": counters, "observations": observations}
