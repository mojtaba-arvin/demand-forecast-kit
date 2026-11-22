Evaluation is separate from unit tests and model training. The initial repository contains no third-party datasets and performs no network download in CI.

Future evaluations should report MASE against seasonal-naive and an explicit baseline definition; WQL by dataset, horizon, and series segment; empirical coverage for nominal 80% and 90% intervals; inventory decision cost under documented lead-time and cost assumptions; and cold-start/post-release datasets separately when pretraining overlap is plausible.

Record data provenance in datasets/DATASETS.lock. Do not compare results across different splits, frequencies, or leakage policies as if they were equivalent.
