from __future__ import annotations

import json

import polars as pl
import pytest

from demand_forecast_kit.evaluation_cli import main


def test_evaluation_cli_emits_reproducible_json(tmp_path, capsys) -> None:
    source = tmp_path / "history.csv"
    pl.DataFrame(
        {
            "series_id": ["sku-a"] * 12,
            "timestamp": pl.date_range(
                pl.date(2024, 1, 1), pl.date(2024, 1, 12), interval="1d", eager=True
            ),
            "demand": [float(value) for value in range(1, 13)],
        }
    ).write_csv(source)

    assert (
        main(
            [
                str(source),
                "--initial-train-size",
                "6",
                "--horizon",
                "2",
                "--step",
                "2",
                "--season-length",
                "2",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["config"]["initial_train_size"] == 6
    assert payload["dataset_fingerprint"]
    assert payload["evaluations"]


def test_evaluation_cli_writes_json_artifact(tmp_path) -> None:
    source = tmp_path / "history.csv"
    output = tmp_path / "nested" / "evaluation.json"
    pl.DataFrame(
        {
            "series_id": ["sku-a"] * 10,
            "timestamp": pl.date_range(
                pl.date(2024, 1, 1), pl.date(2024, 1, 10), interval="1d", eager=True
            ),
            "demand": [1.0] * 10,
        }
    ).write_csv(source)

    assert (
        main([str(source), "--initial-train-size", "6", "--horizon", "2", "--output", str(output)])
        == 0
    )
    assert json.loads(output.read_text(encoding="utf-8"))["model_summaries"]


def test_evaluation_cli_rejects_insufficient_history(tmp_path) -> None:
    source = tmp_path / "history.csv"
    pl.DataFrame(
        {
            "series_id": ["sku-a"] * 3,
            "timestamp": pl.date_range(
                pl.date(2024, 1, 1), pl.date(2024, 1, 3), interval="1d", eager=True
            ),
            "demand": [1.0, 2.0, 3.0],
        }
    ).write_csv(source)

    with pytest.raises(SystemExit) as error:
        main([str(source), "--initial-train-size", "6", "--horizon", "2"])
    assert error.value.code == 2
