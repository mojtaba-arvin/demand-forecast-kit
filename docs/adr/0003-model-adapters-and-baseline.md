# ADR 0003: Model adapters and initial baseline

- Status: accepted for the initial implementation.
- Date: 2026-11-22

## Context

Forecasting research and model availability change quickly. The project must not bind its public API to a single forecasting vendor or assume every optional model can be redistributed.

## Decision

- Define a small \`ForecastAdapter\` protocol independent of model weights and execution framework.
- Ship a deterministic seasonal-naive adapter as a reference implementation and smoke-test baseline, not as a claim of state-of-the-art quality.
- Keep model integrations optional. Every external adapter must document model ID/version, runtime requirements, weight license, download behavior, and conformance tests before registry inclusion.
- Do not build an automatic router until evaluation datasets, leakage controls, and comparable metrics exist.

## Consequences

The seasonal-naive adapter estimates marginal forecast quantiles from its historical seasonal residuals. It does not provide a joint multi-step path distribution, calibrated intervals, or a lead-time demand distribution. Inventory decisions requiring lead-time demand must receive a separately constructed cumulative-demand quantile curve.
