# Adaptive interval calibration

`fit_adaptive_interval_calibrator` learns an additive interval correction from a chronological calibration partition. It uses the finite-sample order statistic of the distance outside each base interval, and can learn separate corrections for demand regimes with enough calibration observations. Under-sampled or unseen regimes use the global correction.

Fit only on calibration data that precedes all evaluation/production origins; do not pass holdout actuals into the fit function. Apply the frozen calibrator to later forecasts. Time-series residual dependence and regime drift weaken exchangeability assumptions, so this is an empirical calibration method rather than a universal coverage guarantee. Always report interval width and inventory cost alongside coverage; keep it disabled by default until temporal validation demonstrates a useful trade-off.
