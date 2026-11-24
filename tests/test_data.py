from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from demand_forecast_kit.data import (
    DataColumns,
    count_demand_outliers,
    count_missing_periods,
    scan_history,
    validate_history,
)


def valid_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "series_id": ["sku-1", "sku-1", "sku-2"],
            "timestamp": [
                datetime(2024, 1, 1),
                datetime(2024, 1, 2),
                datetime(2024, 1, 1),
            ],
            "demand": [1.0, 2.0, 3.0],
        }
    )


def test_validate_history_accepts_valid_frame() -> None:
    report = validate_history(valid_frame())
    assert report.is_valid
    assert report.row_count == 3
    assert report.series_count == 2
    assert report.issues == ()


def test_validate_history_reports_multiple_defects() -> None:
    frame = pl.DataFrame(
        {
            "series_id": ["sku-1", "sku-1", "", "sku-4"],
            "timestamp": [
                datetime(2024, 1, 1),
                datetime(2024, 1, 1),
                datetime(2024, 1, 3),
                None,
            ],
            "demand": [1.0, -2.0, float("inf"), 4.0],
        }
    )
    report = validate_history(frame)

    assert not report.is_valid
    assert report.duplicate_keys == 1
    assert report.negative_demand == 1
    assert report.non_finite_demand == 1
    assert report.empty_series_ids == 1
    assert report.null_values == 1
    assert len(report.issues) == 5


def test_validate_history_rejects_missing_columns() -> None:
    with pytest.raises(ValueError, match="missing canonical columns"):
        validate_history(pl.DataFrame({"series_id": ["sku"]}))


def test_validate_history_reports_empty_frame() -> None:
    frame = pl.DataFrame(
        schema={"series_id": pl.String, "timestamp": pl.Datetime, "demand": pl.Float64}
    )
    report = validate_history(frame)
    assert report.row_count == 0
    assert "history is empty" in report.issues


def test_scan_history_reads_csv_and_renames_columns(tmp_path: Path) -> None:
    path = tmp_path / "sales.csv"
    path.write_text(
        "item,date,units\nsku-1,2024-01-01,2\nsku-1,2024-01-02,4\n",
        encoding="utf-8",
    )
    frame = scan_history(
        path,
        columns=DataColumns(series_id="item", timestamp="date", demand="units"),
    )
    assert frame.collect_schema().names() == ["series_id", "timestamp", "demand"]
    assert validate_history(frame).is_valid


def test_scan_history_reads_parquet(tmp_path: Path) -> None:
    path = tmp_path / "history.parquet"
    valid_frame().write_parquet(path)
    assert validate_history(scan_history(path)).is_valid


def test_scan_history_rejects_unsupported_extension(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="extension"):
        scan_history(path)


def test_scan_history_rejects_missing_source_columns(tmp_path: Path) -> None:
    path = tmp_path / "history.csv"
    path.write_text("id,units\nsku-1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required"):
        scan_history(path)


def test_data_columns_reject_duplicate_names() -> None:
    with pytest.raises(ValueError, match="distinct"):
        DataColumns(series_id="id", timestamp="id", demand="units")


def test_data_columns_reject_blank_names() -> None:
    with pytest.raises(ValueError, match="blank"):
        DataColumns(series_id=" ", timestamp="date", demand="units")


def test_count_missing_periods_reports_gaps_without_filling_them() -> None:
    frame = pl.DataFrame(
        {
            "series_id": ["sku-1", "sku-1", "sku-1", "sku-2", "sku-2"],
            "timestamp": [
                datetime(2024, 1, 1),
                datetime(2024, 1, 3),
                datetime(2024, 1, 6),
                datetime(2024, 1, 1),
                datetime(2024, 1, 2),
            ],
        }
    )

    assert count_missing_periods(frame) == {"sku-1": 3, "sku-2": 0}
    assert frame.height == 5


def test_count_missing_periods_rejects_unaligned_timestamps() -> None:
    frame = pl.DataFrame(
        {
            "series_id": ["sku-1", "sku-1"],
            "timestamp": [datetime(2024, 1, 1), datetime(2024, 1, 1, 12)],
        }
    )
    with pytest.raises(ValueError, match="do not align"):
        count_missing_periods(frame)


def test_validate_history_rejects_timezone_aware_timestamps() -> None:
    frame = pl.DataFrame(
        {
            "series_id": ["sku-1"],
            "timestamp": [datetime(2024, 1, 1, tzinfo=UTC)],
            "demand": [1.0],
        }
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        validate_history(frame)


def test_count_missing_periods_validates_interval() -> None:
    frame = pl.DataFrame({"series_id": ["sku-1"], "timestamp": [datetime(2024, 1, 1)]})
    with pytest.raises(ValueError, match="interval must be positive"):
        count_missing_periods(frame, interval=timedelta(0))


def test_count_demand_outliers_flags_extremes_without_mutating_data() -> None:
    frame = pl.DataFrame(
        {
            "series_id": ["sku-1"] * 7 + ["sku-2"] * 4,
            "demand": [10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 100.0, 3.0, 3.0, 3.0, 3.0],
        }
    )
    original = frame.clone()

    assert count_demand_outliers(frame) == {"sku-1": 1, "sku-2": 0}
    assert frame.equals(original)


def test_count_demand_outliers_rejects_invalid_threshold_and_values() -> None:
    frame = pl.DataFrame({"series_id": ["sku-1"], "demand": [1.0]})
    with pytest.raises(ValueError, match="threshold"):
        count_demand_outliers(frame, threshold=0.0)
    invalid = pl.DataFrame({"series_id": ["sku-1"], "demand": [float("nan")]})
    with pytest.raises(ValueError, match="finite"):
        count_demand_outliers(invalid)
