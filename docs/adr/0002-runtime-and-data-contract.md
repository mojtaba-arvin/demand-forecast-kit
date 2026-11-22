# ADR 0002: Runtime and canonical data contract

- Status: accepted for the initial implementation.
- Date: 2026-11-22

## Context

The package needs to be approachable on a single CPU machine and efficient on columnar data. The full target architecture includes Python, Polars, Arrow, and DuckDB, but introducing dependencies before a code path uses them increases installation cost and maintenance surface.

## Decision

- Require Python 3.13 or newer.
- Use Polars lazy frames for CSV and Parquet scanning and canonical data validation.
- Keep the required dependency set to Polars in the initial package.
- Expose Arrow and DuckDB in the optional \`io\` extra. Promote them to required dependencies only when a supported public workflow needs them.
- Canonical required fields are \`series_id\`, \`timestamp\`, and \`demand\`. Input column names can be mapped through \`DataColumns\`.
- Do not silently drop invalid rows, fill missing demand, or aggregate duplicate keys. Report data defects and let callers decide how to remediate them.

## Consequences

The current validator collects aggregate quality statistics and duplicate-key counts. Streaming memory behavior and ten-million-row performance remain unmeasured and are explicitly deferred to a benchmark specification.
