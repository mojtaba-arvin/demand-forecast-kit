from datetime import date
from pathlib import Path

import polars as pl
import pytest

from demand_forecast_kit.datasets import prepare_uci_electricity


def test_prepare_uci_electricity_aggregates_quarter_hour_kwh(tmp_path: Path) -> None:
    source = tmp_path / "electricity.txt"
    output = tmp_path / "nested" / "daily.parquet"
    header = "date;" + ";".join(f"client_{index}" for index in range(370))
    rows = []
    for timestamp, value in (
        ("2011-01-01 00:15:00", "4,0"),
        ("2011-01-01 00:30:00", "8,0"),
        ("2011-01-01 00:45:00", "12,0"),
        ("2011-01-01 01:00:00", "16,0"),
        ("2011-01-02 00:15:00", "20,0"),
    ):
        rows.append(";".join([timestamp, value, *["0,0"] * 369]))
    source.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")

    summary = prepare_uci_electricity(source, output)
    daily = pl.read_parquet(output).filter(pl.col("series_id") == "client_0")

    assert summary["series_count"] == 370
    assert summary["row_count"] == 740
    assert daily.get_column("demand").to_list() == [10.0, 5.0]
    assert daily.get_column("timestamp").to_list() == [
        date(2011, 1, 1),
        __import__("datetime").date(2011, 1, 2),
    ]


def test_prepare_uci_electricity_requires_all_370_clients(tmp_path: Path) -> None:
    source = tmp_path / "bad.txt"
    source.write_text("date;client_1\n2011-01-01 00:15:00;1,0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expected 370"):
        prepare_uci_electricity(source, tmp_path / "daily.parquet")


def test_prepare_uci_electricity_requires_existing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        prepare_uci_electricity(tmp_path / "missing.txt", tmp_path / "daily.parquet")
