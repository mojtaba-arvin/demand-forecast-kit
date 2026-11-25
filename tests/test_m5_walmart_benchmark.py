from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

from evals.run_m5_walmart_benchmark import run_m5_walmart_benchmark


def _write_m5_fixture(directory: Path, *, day_count: int = 360) -> tuple[Path, Path]:
    sales_path = directory / "sales_train_evaluation.csv"
    calendar_path = directory / "calendar.csv"
    day_columns = [f"d_{index}" for index in range(1, day_count + 1)]
    rows: list[dict[str, object]] = []

    dense = [1 if index < 90 else 0 for index in range(180)] + [2] * (day_count - 180)
    intermittent = [
        1 if index % 10 == 0 else 0 for index in range(180)
    ] + [1] * (day_count - 180)
    very_intermittent = [1 if index < 8 else 0 for index in range(180)] + [
        0
    ] * (day_count - 180)
    for item_id, store_id, values in (
        ("ITEM_DENSE", "CA_1", dense),
        ("ITEM_INTERMITTENT", "TX_1", intermittent),
        ("ITEM_VERY_SPARSE", "WI_1", very_intermittent),
    ):
        row: dict[str, object] = {
            "id": f"{item_id}_{store_id}_evaluation",
            "item_id": item_id,
            "dept_id": "FOODS_1",
            "cat_id": "FOODS",
            "store_id": store_id,
            "state_id": store_id.split("_")[0],
        }
        row.update({column: value for column, value in zip(day_columns, values, strict=True)})
        rows.append(row)

    with sales_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    first_day = date(2011, 1, 29)
    with calendar_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "wm_yr_wk", "weekday", "d"])
        writer.writeheader()
        for index, day_id in enumerate(day_columns):
            current = first_day + timedelta(days=index)
            writer.writerow(
                {
                    "date": current.isoformat(),
                    "wm_yr_wk": index // 7 + 1,
                    "weekday": current.strftime("%A"),
                    "d": day_id,
                }
            )
    return sales_path, calendar_path


def test_m5_runner_keeps_final_28_days_out_of_training_and_writes_policy_report(
    tmp_path: Path,
) -> None:
    sales_path, calendar_path = _write_m5_fixture(tmp_path)
    output = tmp_path / "benchmark.json"

    result = run_m5_walmart_benchmark(
        sales_path,
        calendar_path,
        max_series_per_cohort=1,
        holdout_days=28,
        output=output,
    )

    assert result["cohort_counts"] == {
        "dense": 1,
        "intermittent": 1,
        "very-intermittent": 1,
    }
    windows = result["windows"]
    assert windows["holdout_days"] == 28
    assert windows["training_end"] < windows["holdout_start"]
    assert windows["holdout_end"] >= windows["holdout_start"]
    assert result["configuration"]["global_calibration_correction_enabled"] is False
    assert result["training_model_summaries"]
    assert result["training_lead_time_calibration"]
    assert result["holdout_inventory_scenarios"]
    assert result["holdout_policy_results"]
    assert output.exists()


def test_m5_runner_rejects_holdout_not_divisible_by_14(tmp_path: Path) -> None:
    sales_path, calendar_path = _write_m5_fixture(tmp_path)
    try:
        run_m5_walmart_benchmark(
            sales_path,
            calendar_path,
            max_series_per_cohort=1,
            holdout_days=21,
            output=tmp_path / "invalid.json",
        )
    except ValueError as exc:
        assert "multiple of 14" in str(exc)
    else:
        raise AssertionError("expected invalid holdout window to be rejected")
