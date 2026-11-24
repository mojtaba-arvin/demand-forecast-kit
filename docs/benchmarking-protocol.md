# Benchmarking protocol

## Required report metadata

Every benchmark report must identify:

- dataset name, creator, source URL, DOI, license, and source-file SHA-256;
- preprocessing rules and canonical frequency;
- selected series and cohort assignment policy;
- initial training window, horizon, origin step, and any purged windows;
- model identifiers and versions, quantile levels, and random seeds;
- per-series and macro metrics, including undefined/skipped evaluations.

## Evaluation rules

1. Use chronological rolling-origin splits.
2. Fit model selection and calibration only on data available before each
   forecast origin.
3. Compare all candidate models on identical folds.
4. Report per-series outcomes and equal-series macro summaries; report
   volume-weighted summaries separately when useful.
5. Report pinball loss at each quantile, WQL, MASE, interval coverage, and
   interval width.
6. For inventory policies, report holding cost, shortage cost, unit fill rate,
   and cycle service level separately.
7. Keep a later untouched temporal holdout for any fitted adjustment.
8. Treat a benchmark from one retailer or one domain as domain-specific evidence.

## Dataset separation

UCI Online Retail measures gross outbound unit demand after excluding
cancellations and non-positive quantities. UCI Electricity Load Diagrams
measures quarter-hourly energy consumption for 370 clients. The latter is a
useful independent multi-series load benchmark but is not a retail SKU dataset.
Cross-domain results must not be presented as retail replenishment validation.


## Performance baseline calibration

Smoke artifacts validate the benchmark plumbing; they are not calibration evidence. A calibrated baseline requires at least 10 independent **full-profile** artifacts from 10 distinct GitHub Actions workflow run IDs, all from the same source revision, workload fingerprint, seed, and reference-runner environment. Re-running or retrying jobs in the same workflow run does not create another independent sample. Each artifact records both its per-execution UUID and GitHub workflow run ID; the calibrator rejects duplicate or missing workflow run IDs. The runner metadata is compared exactly, including CPU model, machine architecture, operating system, Python, benchmark dependencies, and runner identity. Incompatible runs must be collected separately.

Configure a dedicated GitHub Actions self-hosted runner with labels `self-hosted`, `linux`, `x64`, and `demand-forecast-reference`. Dispatch the **Reproducible performance benchmarks** workflow with profile `full`, the same repeat count (at least 3), and runner class `reference-self-hosted`. Run it at least 10 separate times against the same commit. Multiple repetitions inside one workflow run do not count as independent artifacts. Artifacts are retained for 90 days.

Download the JSON artifact from each successful run into one directory, then calibrate:

```bash
python -m bench.calibrate_baseline artifacts/run-*.json \
  --minimum-runs 10 \
  --minimum-tolerance 0.05 \
  --sigma-multiplier 3 \
  --output artifacts/calibrated-baseline.json
```

The calibrator uses the median of independent run-level measurements and the scaled median absolute deviation (1.4826 × MAD) as a robust noise estimate. Each workload receives its own tolerance: the larger of the 5% floor and three robust standard deviations relative to its median. A noisy workload therefore gets a wider tolerance rather than a false 5% regression gate. Inspect the samples and provenance in the generated baseline before considering enforcement.

Compare a new compatible full-profile artifact with the calibrated baseline:

```bash
python -m bench.compare_baselines artifacts/current.json \
  artifacts/calibrated-baseline.json
```

The comparator continues to reject environment, profile, seed, and workload identity mismatches. A comparison may use a newer source revision than the calibrated baseline; both revisions are retained in the comparison report. This workflow does not automatically enable a CI failure gate: Issue #31 remains open until 10 valid artifacts are reviewed and the resulting baseline is committed and verified on the reference runner.
