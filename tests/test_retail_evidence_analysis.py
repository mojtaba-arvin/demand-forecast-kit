from __future__ import annotations
import pytest
from evals.analyze_retail_evidence import analyze

def artifact():
    return {"benchmark":"m5-walmart-prequential-lead-time-and-chronological-demand-holdout",
      "configuration":{"global_calibration_correction_enabled":False},
      "training_model_summaries":[{"cohort":"dense","interval_coverages":{"0.8":0.7}}],
      "holdout_policy_results":[{"policy":"baseline","total_cost":12.0}],
      "holdout_inventory_scenarios":[
       {"cohort":"dense","model_id":"m","lead_time":7,"series_id":"a","forecast_origin":"2026-01-01","realized_lead_time_demand":11,"baseline_median_demand":10,"calibrated_quantiles":{"0.1":7,"0.5":10,"0.9":14}},
       {"cohort":"dense","model_id":"m","lead_time":7,"series_id":"b","forecast_origin":"2026-01-01","realized_lead_time_demand":20,"baseline_median_demand":12,"calibrated_quantiles":{"0.1":8,"0.5":12,"0.9":16}}]}

def test_metrics_are_separated_and_clustered():
    p=artifact(); r=analyze(p); g=r["cumulative_lead_time_holdout_metrics"][0]
    assert r["global_calibration_correction_enabled"] is False
    assert r["daily_marginal_training_metrics"] == p["training_model_summaries"]
    assert r["inventory_policy_sensitivity"]["results"] == p["holdout_policy_results"]
    assert g["series_count"] == 2 and g["p80_coverage_macro_series"] == .5
    assert g["mean_cumulative_interval_width"] == 8
    assert g["mean_baseline_median_bias_actual_minus_forecast"] == 4.5
    assert len(g["p80_coverage_cluster_bootstrap_95ci"]) == 2

def test_global_correction_enabled_is_rejected():
    p=artifact(); p["configuration"]["global_calibration_correction_enabled"]=True
    with pytest.raises(ValueError,match="must remain disabled"): analyze(p)

def test_non_m5_data_is_rejected():
    p=artifact(); p["benchmark"]="uci-electricity"
    with pytest.raises(ValueError,match="M5/Walmart"): analyze(p)
