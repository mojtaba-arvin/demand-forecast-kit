# Retail evidence protocol and global-calibration gate

## Cohorts and evidence lanes

Identify each series at SKU-location grain; do not collapse an item across stores.
Freeze cohort membership using only the initial 180-day training window, with
deterministic source-key sampling: dense (>=50% active days), intermittent
(5% to <50%), and sparse/very intermittent (<5%, at least eight active days).
Publish source hashes, date coverage, candidate/selected counts and exclusions.

Keep three evidence lanes separate:

1. **Daily marginal forecasts:** daily P10/P50/P90 coverage, pinball loss,
   interval width and signed bias by cohort and series.
2. **Cumulative lead-time distributions:** derive 7/14-day distributions from
   same-series/model residual paths. Never sum marginal daily quantiles. Report
   P80 coverage, interval width, signed median bias, per-series dispersion and
   series-cluster bootstrap uncertainty separately for each lead time.
3. **Inventory/service outcomes:** evaluate costs, fill rate, cycle service,
   shortages and ending inventory on identical realized holdout scenarios.
   Distinguish observed stock/receipt evidence from sensitivity simulations
   using assumed inventory, lead times or cost weights.

## Chronological separation

1. Freeze cohorts from training-only activity.
2. Collect completed, same-series/model, non-overlapping residual paths strictly
   before each forecast origin.
3. Fit correction parameters and select correction family on a chronological
   calibration/selection block only.
4. Purge at least the maximum evaluated lead time, freeze all choices, then score
   the untouched final holdout. Never reuse final outcomes for tuning, selection,
   cohort assignment or threshold changes.
5. Replicate the frozen protocol on separately sourced data. A second release,
   mirror, file format or sample from one retailer is not independent replication.

M5/Walmart's final 28 labeled days remain untouched. M5 contains sales but no
observed stock position, purchase orders, receipts or supplier lead times;
inventory positions and costs are assumptions, so policy results are sensitivity
analysis, not empirical replenishment economics. UCI Online Retail and Retail II
are the same retailer. The inspected Zenodo source has unresolved operator
provenance and undocumented stock-snapshot/return semantics; it is not yet
eligible as independent replication or replenishment-cost evidence.

## Uncertainty

Aggregate each series over eligible holdout origins first, then bootstrap
series within cohort (2,000 replicates, fixed seed) for 95% percentile intervals
of coverage, width and signed bias. Publish series count, origin count, min/max
and dispersion. Do not treat overlapping origins as iid.

## Predeclared global-correction gate

Global correction remains **disabled**. A new release may propose it only after
all conditions pass on two independently verified retail data-generating
processes:

- At least 100 eligible SKU-location series in each of dense, intermittent and
  sparse cohorts per source, with at least 30 non-overlapping holdout windows
  per series and lead time.
- P80 coverage point estimate >=0.80 and series-cluster 95% lower bound >=0.80
  in every cohort for both 7- and 14-day lead times.
- The 10th percentile of per-series P80 coverage is >=0.75 in every cohort.
- Mean cumulative interval width is <=1.25x the uncorrected comparator, with no
  material pinball-loss regression.
- On observed-stock/receipt data, no cohort has >5% deterioration in total
  inventory cost, unit fill rate or cycle service versus the predeclared
  baseline. Synthetic assumptions cannot pass this condition.
- The frozen result replicates on the second source without retuning.

Insufficient samples, unavailable files, uncertain provenance, or missing
stock/receipt evidence is a no-go, not permission to relax thresholds.
Electricity is cross-domain evidence and cannot satisfy a retail gate.

## M5 report post-processing

After running the opt-in M5 benchmark on authorized local Kaggle files:

```bash
python evals/analyze_retail_evidence.py artifacts/m5-walmart-benchmark.json \
  --output artifacts/retail-evidence-summary.json
```

This analyzer reports cumulative holdout coverage, series dispersion, interval
width, baseline median bias and series-cluster uncertainty. Daily marginal
training metrics and policy sensitivity results remain separate. It does not
tune, select or enable a correction. Keep raw M5 files and row-level data out
of version control.
