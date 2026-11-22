# ADR 0001: Project identity and license

- Status: partially decided; license choice remains open.
- Date: 2026-11-22

## Context

The repository name is \`demand-forecast-kit\`, matching the project brief. The initial repository commit already contains an MIT license. The brief recommends Apache-2.0 but explicitly leaves MIT versus Apache-2.0 as an open decision.

## Decision

Use **Demand Forecast Kit** as the project name and \`demand-forecast-kit\` as the distribution/repository name.

Preserve the existing MIT license in this foundation change. Do not replace it with Apache-2.0 until the project owner makes that explicit decision. The Python package metadata must match the current LICENSE file.

## Consequences

- The current repository state is MIT-licensed; this ADR does not claim that MIT is the final preferred license.
- A future license change requires a dedicated review of existing contributions and distribution obligations, followed by synchronized updates to \`LICENSE\`, package metadata, SPDX declarations, and documentation.
