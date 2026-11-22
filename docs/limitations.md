# Statistical and operational limitations

This document records constraints that must remain visible in API responses,
benchmark reports, and release notes.

## Forecast semantics

- Forecasts are marginal quantiles for each horizon step, not joint sample
  paths. Daily quantiles cannot be summed to obtain cumulative lead-time
  quantiles.
- Seasonal Naive is a deterministic reference baseline, not a trained model.
- Statistical adapters expose backend-specific intervals. Their coverage must
  be measured on the target domain and may be poor under distribution shift.
- Per-series routing selects from historical rolling-origin evidence; it does
  not train models or guarantee future superiority.

## Calibration

- Calibration paths must be strictly earlier than the forecast origin.
- Overlapping residual windows are not independent observations and must not
  be counted as independent calibration paths.
- Calibration and holdout windows must be separated so target periods do not
  overlap.
- Coverage estimates based on correlated forecast origins need block-aware
  uncertainty methods; ordinary binomial intervals assume independent trials.
- Calibration parameters must never be tuned on the same origins used to
  report their final performance.

## Inventory decisions

- Inventory position is on-hand plus confirmed inbound minus backorders.
- The current policy evaluator assumes no intra-lead-time replenishment and no
  salvage value.
- Unit fill rate and cycle service level are distinct outcomes and must be
  reported separately.
- Holding and shortage costs depend on caller-supplied cost assumptions.
- Supplier constraints can make a requested order infeasible; unmet quantity
  must remain explicit rather than silently overcommitting capacity.

## Data semantics

- Missing timestamps are not automatically zero demand. A gap can represent
  zero sales, a closed calendar, or a collection outage.
- Timezone-aware data must be normalized explicitly before canonical
  validation. The library does not infer a business timezone.
- Outliers are reported for investigation; automatic clipping or deletion
  changes the target distribution and must be an explicit preprocessing step.
- Dataset licensing, attribution, source hashes, and preprocessing rules must
  accompany public benchmark artifacts.

## Claims policy

Synthetic CI runs prove execution and serialization only. They do not prove
forecast accuracy, interval calibration, inventory savings, service-level
improvement, or production performance. Such claims require independently
sourced data, pre-registered evaluation windows, a declared baseline, and
reproducible artifacts.
