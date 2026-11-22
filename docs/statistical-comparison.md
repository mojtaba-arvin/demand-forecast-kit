# Statistical comparison of forecasting models

`compare_paired_series_metrics` accepts one already-aggregated metric value per series for a baseline and candidate. It reports the candidate-minus-baseline mean, a percentile bootstrap confidence interval, and a paired sign-flip permutation p-value. Series are the resampling clusters: do not pass individual overlapping rolling-origin folds as independent rows. Aggregate folds within each series first, and interpret the test cautiously when the number of independent series is small.

`aggregate_macro_and_volume_weighted` reports both an unweighted per-series mean and a mean weighted by a caller-supplied volume (for example, total actual demand). The two metrics answer different business questions and should be shown together. These utilities do not select models or tune calibration on holdout data.
