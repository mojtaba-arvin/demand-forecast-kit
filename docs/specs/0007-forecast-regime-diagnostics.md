# Forecast regime diagnostics

`detect_level_shift` compares the medians of the two most recent, adjacent,
non-overlapping windows. It reports the relative change against the prior
window, with a configurable scale floor for near-zero baselines.

The diagnostic is intentionally a monitoring primitive. It is not a statistical
significance test, does not identify the cause of a change, and does not switch
models automatically. A production caller must pass only observations available
at the forecast origin and should validate any response policy on later,
untouched rolling-origin folds.
