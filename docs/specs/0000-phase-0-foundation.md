# SPEC 0000: Phase 0 foundation

- Status: implemented on the phase-0 branch; CI verification pending.
- Scope: establish a small, installable, typed, testable core without claiming production forecasting quality.
- Non-goals: API server, CLI, automatic model selection, external model weights, calendar providers, calibration, hierarchy reconciliation, persistent run ledger, Rust acceleration, or published performance claims.

## Public contracts

1. The canonical history shape is \`series_id: string\`, \`timestamp: datetime\`, and \`demand: finite non-negative float\`.
2. Series/timestamp pairs must be unique. Null required values and blank series identifiers are invalid.
3. Every forecast is quantile-based. Quantile levels are finite, unique, strictly between zero and one; all levels share a non-empty horizon; values are finite, non-negative, and non-decreasing across quantile levels at each step.
4. Every model implementation conforms to \`ForecastAdapter\` and accepts an explicit seed. Deterministic adapters document whether and how that seed is consumed.
5. The newsvendor decision accepts a quantile curve for cumulative lead-time demand. It must not sum marginal per-step quantiles to approximate that distribution.
6. All tests use generated/in-memory fixtures; no network dataset download is allowed in CI.

## Acceptance criteria

- \`ruff check .\` and \`ruff format --check .\` pass.
- \`pyright\` passes in strict mode for \`src/\`.
- \`pytest\` passes with at least 90% branch-aware package coverage.
- Tests cover valid and invalid quantile contracts, deterministic seasonal-naive output, decision interpolation and pack sizing, CSV/Parquet scans, data-quality defects, and repeatable synthetic generation.
- README labels the project as early development and makes no unverified accuracy or speed claim.

## Measurement constraints

This phase does not attempt to validate the hardware performance targets from the engineering brief. A later benchmark specification must name the hardware, dataset shape, warm/cold state, command, repetitions, and artifact location before a target can be reported as achieved.
