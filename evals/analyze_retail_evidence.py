# SPDX-FileCopyrightText: 2026 Mojtaba Arvin
# SPDX-License-Identifier: MIT
"""Summarize M5 retail evidence without mixing marginal and lead-time metrics."""
from __future__ import annotations
import argparse, json, random
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

REPLICATES = 2000
SEED = 42

def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    result = float(value)
    if not result == result or result in (float("inf"), float("-inf")):
        raise ValueError(f"{field} must be finite")
    return result

def _interval(values: dict[str, float], seed: int) -> list[float]:
    samples = list(values.values())
    if len(samples) < 2:
        return [samples[0], samples[0]]
    rng = random.Random(seed)
    estimates = sorted(mean(rng.choices(samples, k=len(samples))) for _ in range(REPLICATES))
    return [estimates[int(.025 * (REPLICATES - 1))], estimates[int(.975 * (REPLICATES - 1))]]

def analyze(payload: dict[str, Any]) -> dict[str, Any]:
    expected = "m5-walmart-prequential-lead-time-and-chronological-demand-holdout"
    if payload.get("benchmark") != expected:
        raise ValueError("input must be an M5/Walmart benchmark artifact")
    if payload.get("configuration", {}).get("global_calibration_correction_enabled") is not False:
        raise ValueError("global calibration correction must remain disabled")
    scenarios = payload.get("holdout_inventory_scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("artifact must contain untouched holdout inventory scenarios")
    grouped: dict[tuple[str,str,int,str], list[dict[str,Any]]] = defaultdict(list)
    for row in scenarios:
        lead = int(row["lead_time"])
        if lead not in (7,14):
            raise ValueError("only predeclared 7- and 14-day lead times are accepted")
        grouped[(str(row["cohort"]),str(row["model_id"]),lead,str(row["series_id"]))].append(row)
    cohorts: dict[tuple[str,str,int],list[dict[str,Any]]] = defaultdict(list)
    for (cohort,model,lead,series), rows in grouped.items():
        hits=[]; widths=[]; biases=[]
        for row in rows:
            qs=row.get("calibrated_quantiles")
            if not isinstance(qs,dict) or not all(k in qs for k in ("0.1","0.5","0.9")):
                raise ValueError("holdout quantiles must contain 0.1, 0.5, and 0.9")
            lo,mid,hi=(_finite(qs[k],f"quantile {k}") for k in ("0.1","0.5","0.9"))
            if not 0 <= lo <= mid <= hi: raise ValueError("holdout quantiles must be non-negative and monotone")
            actual=_finite(row["realized_lead_time_demand"],"realized_lead_time_demand")
            baseline=_finite(row["baseline_median_demand"],"baseline_median_demand")
            hits.append(float(lo <= actual <= hi)); widths.append(hi-lo); biases.append(actual-baseline)
        cohorts[(cohort,model,lead)].append({"series_id":series,"origin_count":len(rows),
            "p80_coverage":mean(hits),"mean_interval_width":mean(widths),
            "mean_baseline_median_bias":mean(biases),
            "mean_absolute_baseline_median_bias":mean(abs(x) for x in biases)})
    lead_metrics=[]
    for (cohort,model,lead), rows in sorted(cohorts.items()):
        coverage={r["series_id"]:r["p80_coverage"] for r in rows}
        widths={r["series_id"]:r["mean_interval_width"] for r in rows}
        bias={r["series_id"]:r["mean_baseline_median_bias"] for r in rows}
        lead_metrics.append({"cohort":cohort,"model_id":model,"lead_time_days":lead,
            "series_count":len(rows),"mean_origins_per_series":mean(r["origin_count"] for r in rows),
            "p80_coverage_macro_series":mean(coverage.values()),"p80_coverage_series_min":min(coverage.values()),
            "p80_coverage_series_max":max(coverage.values()),
            "p80_coverage_series_sd":pstdev(coverage.values()) if len(rows)>1 else 0.0,
            "p80_coverage_cluster_bootstrap_95ci":_interval(coverage,SEED+lead),
            "mean_cumulative_interval_width":mean(widths.values()),
            "interval_width_cluster_bootstrap_95ci":_interval(widths,SEED+100+lead),
            "mean_baseline_median_bias_actual_minus_forecast":mean(bias.values()),
            "bias_cluster_bootstrap_95ci":_interval(bias,SEED+200+lead),
            "series":sorted(rows,key=lambda r:r["series_id"]),
            "interpretation":"Cumulative lead-time holdout metrics; series are bootstrap units."})
    return {"schema_version":1,"analysis":"retail-evidence-separated-summary","source_benchmark":expected,
        "source_provenance":payload.get("provenance",{}),"windows":payload.get("windows",{}),
        "global_calibration_correction_enabled":False,
        "daily_marginal_training_metrics":payload.get("training_model_summaries",[]),
        "cumulative_lead_time_holdout_metrics":lead_metrics,
        "inventory_policy_sensitivity":{"results":payload.get("holdout_policy_results",[]),
          "assumption_boundary":"M5 has no observed inventory, purchase orders, receipts, or supplier lead times. Inventory positions and cost weights are synthetic assumptions, not empirical replenishment costs or service outcomes."},
        "evidence_limitations":["M5 is independent demand evidence relative to UCI Online Retail, but has no observed inventory or receipts.",
          "A 28-day holdout yields few non-overlapping origins and cannot establish independent replication.",
          "Overlapping training origins are not independent bootstrap samples.",
          "This analysis does not tune calibration, select models, or enable global correction."]}

def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input",type=Path)
    parser.add_argument("--output",type=Path,default=Path("artifacts/retail-evidence-summary.json"))
    args=parser.parse_args()
    report=analyze(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"output":str(args.output),"lead_time_groups":len(report["cumulative_lead_time_holdout_metrics"]),"global_calibration_correction_enabled":False},indent=2))
if __name__=="__main__": main()
