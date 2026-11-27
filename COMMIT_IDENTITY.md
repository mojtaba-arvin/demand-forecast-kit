# Commit identity and attribution policy

For maintainer-directed AI-assisted implementation, use Git author `Mojtaba Arvin <m.arvin@live.com>` only when GitHub links that exact commit email to the maintainer account. The linked commit metadata is evidence of account association, not proof of who physically typed the changes. Do not use model, assistant, AI-agent, Copilot, Claude, Cursor, Codex, Gemini, generic agent, or bot identities as implementation authors or committers.

Include `<!-- maintainer-directed-ai-work -->` in the PR body for owner-authorized AI-assisted work. The marker requires at least one commit whose Git author and linked GitHub author account both resolve to the exact maintainer identity. Every commit attributed to `mojtaba-arvin` must use the exact maintainer name/email. Other human contributors' original author name/email and linked account are preserved; never relabel another person as the maintainer or rewrite historical commits.

Genuine GitHub Actions/Dependabot commits are permitted only with the explicit `allow-automation-commits` label and matching, linked bot author and committer accounts, exact canonical GitHub no-reply addresses, and the same allowlisted automation identity in both roles. The label alone is insufficient and does not permit agent-written implementation. Bot/AI `Co-authored-by` trailers are always prohibited. A GitHub `web-flow` identity is allowed only as the committer with its canonical no-reply address; it never replaces the actual human author.

Convenience defaults (not enforcement):

```sh
git config --global user.name "Mojtaba Arvin"
git config --global user.email "m.arvin@live.com"
```

`scripts/check_commit_identity.py` validates all PR commit authors, committers, linked GitHub accounts, co-author trailers, and the narrow automation exception. The `Commit identity` workflow uses read-only GitHub permissions and checks out only trusted base-branch code. Configure this check as required in branch protection/rulesets where governance permits; a workflow alone does not block merges.

Git metadata is self-asserted and cannot prove who physically typed code or detect every disguised agent identity. Disclose AI assistance transparently in the PR description. Never amend, rebase, or cherry-pick a contributor's work under the maintainer identity; add a separate maintainer-authored commit for AI-assisted changes.
