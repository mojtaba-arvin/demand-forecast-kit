# SPDX-FileCopyrightText: 2026 Mojtaba Arvin
# SPDX-License-Identifier: MIT
"""Tests for the public Zenodo retail source inspector."""

from datetime import date
from pathlib import Path

import polars as pl

from scripts.inspect_zenodo_retail_source import _read_frame, inspect_frame


def test_csv_empty_values_are_normalized_to_null(tmp_path: Path) -> None:
    csv_path = tmp_path / "sales_txn.csv"
    csv_path.write_text(
        "TXN_DT,STORE,PRODUCT_NO,LAST_RCPT_DT,QTY_SOLD\n"
        "2024-01-01,A,P-1,,1\n"
        "2024-01-02,A,P-1,2024-01-01,-1\n",
        encoding="utf-8",
    )

    csv_frame = _read_frame(csv_path)

    assert csv_frame["LAST_RCPT_DT"].null_count() == 1
    assert csv_frame["TXN_DT"].dtype == pl.Date


def test_csv_and_parquet_preserve_equivalent_missing_values(tmp_path: Path) -> None:
    source = pl.DataFrame(
        {
            "TXN_DT": [date(2024, 1, 1), date(2024, 1, 2)],
            "STORE": ["A", "A"],
            "PRODUCT_NO": ["P-1", "P-1"],
            "LAST_RCPT_DT": [None, date(2024, 1, 1)],
            "QTY_SOLD": [1, -1],
        }
    )
    csv_path = tmp_path / "sales_txn.csv"
    parquet_path = tmp_path / "sales_txn.parquet"
    source.write_csv(csv_path)
    source.write_parquet(parquet_path)

    csv_frame = _read_frame(csv_path)
    parquet_frame = _read_frame(parquet_path)

    assert csv_frame["LAST_RCPT_DT"].null_count() == 1
    assert parquet_frame["LAST_RCPT_DT"].null_count() == 1
    assert csv_frame["QTY_SOLD"].to_list() == parquet_frame["QTY_SOLD"].to_list()


def test_inspect_frame_reports_daily_key_and_signed_sales() -> None:
    frame = pl.DataFrame(
        {
            "TXN_DT": [
                date(2024, 1, 1),
                date(2024, 1, 2),
                date(2024, 1, 2),
            ],
            "STORE": ["A", "A", "A"],
            "PRODUCT_NO": ["P-1", "P-1", "P-1"],
            "QTY_SOLD": [2, -1, 0],
            "LAST_RCPT_DT": [None, date(2024, 1, 1), None],
            "IS_RETURN": [0, -1, 1],
        }
    )

    report = inspect_frame("fixture", frame)

    assert report["candidate_key_diagnostics"]["TXN_DT+STORE+PRODUCT_NO"] == {
        "rows": 3,
        "unique_keys": 2,
        "duplicate_rows": 1,
    }
    assert report["numeric_diagnostics"]["QTY_SOLD"]["negative_rows"] == 1
    assert report["nonzero_null_counts"]["LAST_RCPT_DT"] == 2
    assert report["series_coverage"]["store_product_series"] == 1
