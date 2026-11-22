import json
from datetime import date, timedelta

import polars as pl
import pytest

from demand_forecast_kit.cli import main


def test_cli_writes_deterministic_json_forecast(tmp_path) -> None:
    source = tmp_path / "history.csv"
    start = date(2026, 1, 1)
    rows = ["series_id,timestamp,demand"]
    rows.extend(f"sku-a,{start + timedelta(days=index)},{index % 7 + 1}" for index in range(21))
    source.write_text("\n".join(rows) + "\n", encoding="utf-8")
    output = tmp_path / "nested" / "forecast.json"

    assert main([str(source), "--horizon", "7", "--output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["forecasts"][0]["series_id"] == "sku-a"
    assert payload["forecasts"][0]["horizon"] == 7
    assert set(payload["forecasts"][0]["quantiles"]) == {"0.1", "0.5", "0.9"}


@pytest.mark.parametrize("output_format", ["csv", "parquet"])
def test_cli_writes_tabular_forecast_formats(tmp_path, output_format: str) -> None:
    source = tmp_path / "history.csv"
    start = date(2026, 1, 1)
    rows = ["series_id,timestamp,demand"]
    rows.extend(f"sku-a,{start + timedelta(days=index)},{index % 7 + 1}" for index in range(21))
    source.write_text("\n".join(rows) + "\n", encoding="utf-8")
    output = tmp_path / f"forecast.{output_format}"

    arguments = [
        str(source),
        "--horizon",
        "3",
        "--format",
        output_format,
        "--output",
        str(output),
    ]
    assert main(arguments) == 0
    frame = pl.read_csv(output) if output_format == "csv" else pl.read_parquet(output)

    assert set(frame.columns) == {
        "series_id",
        "model_id",
        "model_version",
        "horizon_step",
        "quantile",
        "forecast",
    }
    assert frame.height == 9


def test_cli_requires_output_for_tabular_formats(tmp_path) -> None:
    source = tmp_path / "history.csv"
    source.write_text(
        "series_id,timestamp,demand\nsku-a,2026-01-01,1\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as error:
        main([str(source), "--format", "csv"])
    assert error.value.code == 2
