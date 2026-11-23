from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from demand_forecast_kit.cli import main as forecast_main
from demand_forecast_kit.evaluation_cli import main as evaluation_main


def _history_file(path: Path, count: int = 42) -> Path:
    frame = pl.DataFrame(
        {
            "series_id": ["sku-1"] * count,
            "timestamp": [date(2024, 1, 1) + timedelta(days=index) for index in range(count)],
            "demand": [float(index % 7 + 1) for index in range(count)],
        }
    )
    frame.write_csv(path)
    return path


def test_forecast_cli_persists_runs_and_artifact_metadata(tmp_path, capsys) -> None:
    source = _history_file(tmp_path / "history.csv")

    assert forecast_main(
        [str(source), "--horizon", "3", "--state-dir", str(tmp_path / "forecast-state")]
    ) == 0

    result = json.loads(capsys.readouterr().out)
    forecast = result["forecasts"][0]
    assert forecast["run"]["status"] == "completed"
    assert len(forecast["run"]["artifact_sha256"]) == 64


def test_evaluation_cli_persists_rolling_origin_report(tmp_path) -> None:
    source = _history_file(tmp_path / "history.csv")
    output = tmp_path / "evaluation.json"

    assert evaluation_main(
        [
            str(source),
            "--initial-train-size",
            "14",
            "--horizon",
            "7",
            "--step",
            "7",
            "--output",
            str(output),
            "--state-dir",
            str(tmp_path / "evaluation-state"),
        ]
    ) == 0

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["evaluations"]
    assert result["run"]["status"] == "completed"
    assert len(result["run"]["artifact_sha256"]) == 64
