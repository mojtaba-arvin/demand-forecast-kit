# Evidence-gated PR review and merge

The implementer may review and merge their own code. Self-review is not independent peer review, and GitHub does not allow the PR author to submit a formal approval of their own PR.

## Exact-head merge evidence

1. Record the intended base branch and verify merge-base freshness.
2. Review the complete diff, including data ingestion, model artifacts, benchmark protocols, dependency/license changes, and workflow permissions.
3. Link the Issue acceptance criteria and exact commands executed.
4. Verify targeted tests and the full relevant suite: Ruff, format, Pyright, pytest, pip-audit, REUSE, and required integrations.
5. For benchmark or accuracy claims, attach the immutable CI artifact, dataset fingerprint, split, seeds, model version, and runner metadata. Never substitute local numbers or synthetic data for independent evidence.
6. Confirm all required status checks pass on the exact head SHA.
7. Resolve material review threads or document accepted limitations.
8. Confirm the PR is mergeable under the repository's actual GitHub rules.

The implementer may author the self-review record and merge when these gates pass. Specialist review is optional and risk-based, not a universal merge prerequisite. Do not fabricate an approval or describe self-review as independent.

## Branch protection

Never bypass branch protection, rulesets, required checks, required reviews, or merge queues. If a ruleset still requires an independent approver solely because of author identity, an authorized owner must update that administrative setting. No fake account or simulated review is permitted.

## Separate acceptance gates

Merge does not mean that a model is activated, a benchmark claim is validated, an independent retailer replication exists, or an external ERPNext/production exercise passed. Preserve immutable holdouts, source licenses/provenance, independent benchmark requirements, external operational evidence, and release criteria.
