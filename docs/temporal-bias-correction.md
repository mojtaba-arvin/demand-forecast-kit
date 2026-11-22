# Temporal bias correction

`estimate_temporal_bias_correction` estimates a robust median residual correction from completed, non-overlapping rolling-origin folds whose test end is strictly before the requested forecast origin. It freezes the correction and applies it to future median forecasts with a zero floor. Model-version consistency is enforced. This is a prequential calibration component: fit it on historical calibration folds only, then report its effect on a later temporal holdout without refitting on that holdout.
