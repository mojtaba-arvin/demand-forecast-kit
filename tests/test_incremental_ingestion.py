from datetime import datetime

import polars as pl
import pytest

from demand_forecast_kit.ingestion import merge_history_batches


def _frame(rows: list[tuple[str, datetime, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        rows,
        schema=["series_id", "timestamp", "demand"],
        orient="row",
    )


def test_incremental_merge_keeps_late_rows_and_new_batch_wins() -> None:
    old = _frame([
        ("sku-a", datetime(2026, 1, 1), 2.0),
        ("sku-a", datetime(2026, 1, 3), 4.0),
    ])
    incoming = _frame([
        ("sku-a", datetime(2026, 1, 2), 3.0),
        ("sku-a", datetime(2026, 1, 3), 7.0),
    ])

    result = merge_history_batches(old, incoming)

    assert result["timestamp"].to_list() == [
        datetime(2026, 1, 1),
        datetime(2026, 1, 2),
        datetime(2026, 1, 3),
    ]
    assert result["demand"].to_list() == [2.0, 3.0, 7.0]


def test_incremental_merge_is_deterministic_for_empty_batch() -> None:
    old = _frame([("sku-a", datetime(2026, 1, 1), 2.0)])

    assert merge_history_batches(old, old.head(0)).equals(old)


@pytest.mark.parametrize("demand", [-1.0, float("nan"), float("inf")])
def test_incremental_merge_rejects_invalid_demand(demand: float) -> None:
    empty = _frame([])
    incoming = _frame([("sku-a", datetime(2026, 1, 1), demand)])

    with pytest.raises(ValueError, match="invalid"):
        merge_history_batches(empty, incoming)


def test_incremental_merge_rejects_missing_columns() -> None:
    with pytest.raises(ValueError, match="missing columns"):
        merge_history_batches(pl.DataFrame(), pl.DataFrame({"demand": [1.0]}))
