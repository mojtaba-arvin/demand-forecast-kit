# Release checklist

This checklist is required before publishing a tagged release. A green unit-test
job alone is not sufficient evidence of production readiness.

## Source and compatibility

- [ ] Confirm the release commit is based on the intended integration baseline.
- [ ] Review all open and merged pull requests included in the release.
- [ ] Run Ruff lint and format checks.
- [ ] Run strict Pyright checks.
- [ ] Run core tests with the configured branch coverage threshold.
- [ ] Run optional StatsForecast and API integration tests when those extras change.
- [ ] Test installation from the built wheel in a clean Python 3.13 environment.
- [ ] Verify optional extras fail with actionable messages when absent.
- [ ] Confirm the Git tag matches the package version in pyproject.toml.

## Forecast and decision quality

- [ ] Record dataset fingerprints, split configuration, seeds, and model versions.
- [ ] Run chronological backtests on at least two independently sourced datasets.
- [ ] Report macro and volume-weighted metrics separately.
- [ ] Report per-series interval coverage and coverage uncertainty.
- [ ] Keep holdout data untouched during model and calibration selection.
- [ ] Compare inventory cost, fill rate, and cycle service against a declared baseline.
- [ ] Document unsupported dependence assumptions for marginal daily quantiles.

## Security, packaging, and provenance

- [ ] Run pip-audit and REUSE lint.
- [ ] Review MIT license and all optional dependency licenses.
- [ ] Build wheel and source distribution and inspect their contents.
- [ ] Verify package metadata and version consistency.
- [ ] Generate release notes from verified changes only.
- [ ] Publish SHA-256 checksums for release artifacts.
- [ ] Keep raw third-party benchmark datasets out of Git and release artifacts.

## Release decision

A release is blocked by unresolved critical security findings, data leakage,
non-deterministic artifact generation, broken clean installation, or an
unexplained regression in forecast or inventory evaluation.
