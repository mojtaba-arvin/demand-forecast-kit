# SPEC 0005: Lead-time demand calibration from residual paths

- Status: implemented on `work/lead-time-demand-calibration`; CI verification pending.
- Scope: estimate cumulative lead-time demand quantiles from rolling-origin out-of-sample forecast residual paths and assess them prequentially.
- Non-goals: infer dependence from marginal quantiles, pool unrelated SKUs, claim universal calibration, optimize inventory costs, or claim business savings.

## Statistical contract

1. A target forecast supplies a non-negative median daily baseline for the requested lead time.
2. Calibration residual paths are actual minus median forecast from completed rolling-origin folds for the exact same series and model.
3. A calibration fold is eligible only when its `test_end_timestamp` is strictly earlier than the target forecast origin.
4. Overlapping evaluation windows are greedily excluded, so shared actual periods do not count as independent calibration paths.
5. Bootstrap samples resample complete residual trajectories. The residuals inside a path are never shuffled or sampled independently.
6. Daily demand samples are clipped at zero before cumulative summation.
7. The caller must request a lead time no longer than the backtest horizon and provide enough non-overlapping historical paths.
8. A prequential diagnostic calibrates each target fold only from completed earlier folds and reports empirical cumulative-quantile coverage and pinball loss.

## Limitations

- Whole-path bootstrap assumes selected historical residual paths are representative/exchangeable for the target origin; it does not model regime changes or conditional heteroskedasticity.
- Non-overlapping path selection is conservative and may leave little evidence when rolling-origin step sizes are short relative to the horizon.
- The bootstrap distribution is conditional on the caller-supplied median baseline and historical residual paths; it is not a full joint predictive model.
- Synthetic CI results verify deterministic plumbing and leakage guards, not statistical quality on a real SKU dataset.

## Acceptance

- Unit tests cover strict temporal cutoffs, series/model isolation, overlap removal, deterministic bootstrap, minimum evidence, invalid horizons, and inventory integration.
- A prequential rolling-origin diagnostic reports cumulative quantile coverage and pinball loss using only earlier completed folds.
- Base CI runs a synthetic calibration-to-inventory smoke and uploads its JSON artifact.
