# Versioning and release policy

The package starts at `0.1.0`. Until a stable public API is declared, use
pre-1.0 semantic versioning:

- **PATCH**: backward-compatible fixes and documentation corrections.
- **MINOR**: backward-compatible features and additive public contracts.
- **BREAKING pre-1.0 changes**: document explicitly and increment the minor
  version when consumers may need to adapt.
- **1.0.0**: only after the public Python, CLI, and optional HTTP contracts are
  reviewed and the release checklist is satisfied.

A release tag must match the package version in `pyproject.toml`. The release
candidate workflow builds both wheel and source distribution, runs quality and
security checks, installs each distribution in a separate clean virtual
environment, smoke-tests both CLI entry points, and publishes checksums as
workflow artifacts.

The workflow does not publish to PyPI or create a GitHub Release. Those actions
require an explicit publishing credential and a separate supply-chain review.
