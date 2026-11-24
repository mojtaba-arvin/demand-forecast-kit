# Calibration versus inventory cost

`compare_calibration_inventory_costs` evaluates baseline and frozen-calibrated lead-time quantiles against the same realized scenarios and inventory positions. It reports cost, fill-rate, cycle-service, and average interval-width deltas. This exposes the practical trade-off: wider intervals can improve service while increasing holding and ordering exposure. Fit the calibrator only on an earlier calibration partition; this function is an evaluation step and must not be used to tune the calibrator on the reported temporal holdout.
