# ADR 0005: Statistical adapter backend

- Status: accepted for the first statistical adapter set.
- Date: 2026-11-22

## Context

Demand Forecast Kit needs production-meaningful AutoETS, AutoARIMA, Theta, Croston, and TSB implementations while keeping the base package small and its CI path independent of model-specific native/scientific dependencies.

Hand-implementing several model-selection algorithms and their prediction distributions would duplicate mature numerical work and create an unacceptably large correctness surface.

## Decision

Use Nixtla StatsForecast as an optional backend, pinned by a compatible major-version range in the `stats` extra. Keep imports lazy and leave Polars as the only required runtime dependency.

Use model-native prediction intervals for AutoETS, AutoARIMA, and Theta. Use StatsForecast conformal intervals for Croston and TSB, whose future prediction intervals require an explicit calibration-window configuration. Retain the project's existing seasonal-naive adapter as the dependency-free baseline.

## Consequences

- Users can install only the core package when they need ingestion, contracts, backtesting, or the baseline model.
- Users opt in to the scientific/statistical dependency stack when running statistical adapters.
- Model version metadata records the installed StatsForecast version.
- The adapters expose marginal forecasts only. They do not imply temporal dependence or cumulative lead-time distributions.
- Synthetic CI outputs validate software execution and serialization only; they are not accuracy or performance claims.
