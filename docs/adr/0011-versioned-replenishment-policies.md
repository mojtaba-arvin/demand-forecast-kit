# ADR 0011: Versioned replenishment policy lifecycle

- Status: accepted.
- Date: 2026-11-25

## Context

The worker can evaluate realized policy outcomes and rank candidates, but a
ranked candidate is not an operator-approved production policy. Schedule
payloads currently carry Newsvendor cost and pack-size parameters, which makes
policy changes difficult to audit and roll back independently from schedules.

## Decision

- Persist tenant-scoped immutable policy definitions and versions in SQLite.
- Initially support a validated Newsvendor contract with positive finite
  underage/overage costs and a positive integer pack size.
- Canonicalize definitions and bind each version to a SHA-256 digest.
- Scope active pointers by tenant and policy ID.
- Require compare-and-swap activation and explicit-target rollback.
- Append immutable activation/rollback history.
- When the worker is configured with the registry, require an active policy
  named by the replenishment schedule; use the registered definition rather
  than conflicting schedule-supplied costs or pack size.
- Include policy ID, version, and definition digest in decision/run provenance.
- Keep policy ranking advisory. Never auto-promote a candidate from observed
  outcomes or a lower simulated cost.
- Preserve legacy schedule-supplied policy parameters when registry mode is
  not configured.

## Consequences

The registry is tenant-scoped but remains a single-host SQLite control plane.
It does not provide distributed activation, automatic policy optimization, or
proof that historical outcomes generalize to future demand. A missing active
policy causes the scheduled job to fail and retry rather than silently choose
a different policy.
