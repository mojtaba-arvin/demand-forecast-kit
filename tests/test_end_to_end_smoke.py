from __future__ import annotations

import json

from evals.run_end_to_end_smoke import run_end_to_end


def test_end_to_end_pipeline_writes_a_registered_inventory_decision(tmp_path) -> None:
    output = tmp_path / "end-to-end.json"

    result = run_end_to_end(output)

    assert output.is_file()
    assert json.loads(output.read_text(encoding="utf-8")) == result
    assert result["rolling_origin"]["fold_count"] >= 5
    assert result["lead_time_calibration"]["path_count"] >= 5
    assert result["registry"]["status"] == "completed"
    assert result["registry"]["inventory_decision_id"] > 0
    assert len(result["artifact"]["sha256"]) == 64
    assert set(result["policy_comparison"]) == {"baseline", "high-service"}
