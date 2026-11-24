Every adapter must implement the demand_forecast_kit ForecastAdapter protocol and pass the common conformance suite.

Before adding an integration, record its immutable model/version reference, upstream model card, exact weight and code licenses, redistribution and commercial-use terms, CPU/RAM requirements, download behavior, determinism/seed semantics, quantile semantics, calibration limitations, and reproducible benchmark/evaluation artifacts.

Unknown or non-commercial weight licenses must never be enabled by default. Never download weights during package installation or CI.
