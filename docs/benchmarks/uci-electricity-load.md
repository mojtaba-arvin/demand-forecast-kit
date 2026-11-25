# UCI Electricity Load Diagrams 2011–2014

This is an independent, multi-series demand benchmark adapter. It is an energy-load
dataset, not retail SKU sales; results must be reported as cross-domain forecasting
evidence rather than direct evidence of retail replenishment performance.

## Provenance

- Creator: Artur Trindade
- Citation: Trindade, A. (2015). *ElectricityLoadDiagrams20112014*. UCI Machine
  Learning Repository.
- DOI: https://doi.org/10.24432/C58C86
- Source: https://archive.ics.uci.edu/dataset/321/electricity
- License: Creative Commons Attribution 4.0 International (CC BY 4.0)
- Dataset: 370 client series, 140,256 quarter-hour observations per full series,
  2011–2014; the source file is approximately 678 MB uncompressed.

## Preprocessing contract

The UCI source records power in kW at 15-minute intervals. The adapter divides
each value by four to convert each interval to kWh, then sums interval energy by
client and calendar day. It preserves Portuguese local-time labels as
timezone-naive timestamps because the source does not provide UTC offsets.

The dataset documents daylight-saving-time handling: March transition intervals
are zero-filled and October transition intervals aggregate two hours. The
preprocessor does not fabricate a uniform 96-interval day or reinterpret these
records as UTC. The source reports no missing values; the adapter fails closed
on null, non-finite, or negative measurements.

## Reproduction and evaluation protocol

Install the optional dependencies, download and extract the official UCI archive,
then run:

```bash
python -m pip install -e ".[benchmark,dev]"
python evals/run_uci_electricity_benchmark.py LD2011_2014.txt \
  --max-series 370 \
  --output artifacts/uci-electricity-benchmark.json
```

The benchmark selects the first 370 series in stable lexical order (or a smaller
prefix for a smoke run), fits Seasonal Naive, AutoETS, and additive Theta, and
uses a 365-day expanding initial training window, a 7-day horizon, and a 90-day
origin step. It reports P10/P50/P90 forecasts, P80 interval coverage, MASE,
WQL, and pinball loss through the shared rolling-origin evaluator.

Each JSON report records the raw text file SHA-256, selected series IDs, source
citation and license, preprocessing summary, Python/platform/Polars/StatsForecast
versions, and exact evaluation configuration. The raw archive is not committed.
Daily aggregation is a deliberate frequency conversion; do not compare its scores
directly with hourly or quarter-hourly benchmarks.

## Limitations

- This is electricity consumption, not retail sales or intermittent SKU demand.
- The series have different start dates; leading zeroes are part of the source
  representation and must not be silently trimmed.
- This benchmark tests dense multi-series forecasting and data-pipeline scale.
  It cannot validate retail accuracy, intermittent-demand calibration, inventory
  costs, or replenishment service levels. Those require separate retail evidence.
