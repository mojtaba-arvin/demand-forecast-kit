# Changelog

All notable changes to this project are documented here.

This project follows Semantic Versioning and Keep a Changelog.

## [Unreleased]

### Added

- Lead-time inventory policy evaluation against realized cumulative demand, with holding/shortage costs, unit fill rate, and cycle service level.
- A deterministic synthetic inventory evaluation smoke and CI artifact.
- Leakage-aware per-SKU model routing from historical rolling-origin evidence, with strict forecast-origin guards, model-version validation, deterministic fallback, and routing artifacts.
- Per-series history timestamp ranges in version 2 of evaluation reports.
- A synthetic model-routing smoke evaluation in the base CI workflow.
- Optional StatsForecast-backed AutoETS, AutoARIMA, and Theta adapters for dense demand series.
- Optional CrostonClassic, CrostonOptimized, CrostonSBA, and TSB adapters with conformal prediction intervals.
- A dedicated statistical-adapter integration workflow and synthetic dense/intermittent rolling-origin evaluation artifacts.
- Rolling-origin expanding/sliding-window evaluation for multiple model adapters and demand series.
- MASE, normalized WQL, per-quantile pinball loss, and central interval coverage metrics.
- Deterministic JSON evaluation reports with dataset fingerprints and artifact SHA-256 digests.
- A synthetic evaluation smoke run uploaded as a GitHub Actions artifact.
- Executable backtesting/evaluation specification and metric-semantics ADR.
- Initial Python package foundation, probabilistic forecast contracts, deterministic seasonal-naive reference adapter, input validation, newsvendor decision primitive, and offline test/CI scaffold.
