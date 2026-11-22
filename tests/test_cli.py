from datetime import date, timedelta

import json

from demand_forecast_kit.cli import main


def test_cli_writes_deterministic_json_forecast(tmp_path) -> None:
    source = tmp_path / "history.csv"
    start = date(2026, 1, 1)
    rows = ["series_id,timestamp,demand"]
    rows.extend(
        f"sku-a,{start + timedelta(days=index)},{index % 7 + 1}"
        for index in range(21)
    )
    source.write_text("\n".join(rows) + "\n", encoding="utf-8")
    output = tmp_path / "nested" / "forecast.json"

    assert main([str(source), "--horizon", "7", "--output", str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["forecasts"][0]["series_id"] == "sku-a"
    assert payload["forecasts"][0]["horizon"] == 7
    assert set(payload["forecasts"][0]["quantiles"]) == {"0.1", "0.5", "0.9"}
