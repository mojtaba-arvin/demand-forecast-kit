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

## Reproduce

Download and extract the official UCI archive, then run:

```bash
python -c "from demand_forecast_kit.datasets import prepare_uci_electricity; print(prepare_uci_electricity('LD2011_2014.txt', 'artifacts/uci-electricity-daily.parquet'))"
```

The raw archive is not committed to this repository. Record the source archive
SHA-256 alongside every benchmark report. Daily aggregation is a deliberate
frequency conversion; do not compare its scores directly with hourly or
quarter-hourly benchmarks.

## Limitations

- This is electricity consumption, not retail sales or intermittent SKU demand.
- The series have different start dates; leading zeroes are part of the source
  representation and must not be silently trimmed.
- The benchmark tests dense multi-series forecasting and data pipeline scale.
  Retail-specific conclusions still require a separate retail dataset.
