# Help generated projects catch CI failures (actionlint + verify-the-run)

- **Status:** Accepted
- **Date:** 2026-06-02
- **Author:** Luca Mastrostefano

## Context

We shipped CI referencing a non-existent action tag (`pip-audit@v1`) and a deprecated
runner (Node 20), caught only because the maintainer manually checked GitHub. Local
validation (YAML parse, string-assertion tests) can't see an unresolvable action ref or
a runner deprecation — only the live run can. Generated projects shouldn't depend on a
human watching GitHub either. Both fixes only apply when **GitHub Actions are
scaffolded** (`include_ci and use_github_actions`).

## Decision

When GitHub Actions are scaffolded:

1. **`actionlint` pre-commit hook** via `actionlint-py` (self-installs through
   pre-commit's Python backend — no Go/Docker, unlike the official hook), scoped to
   `.github/workflows/`, so workflow mistakes are caught **before push** and only when a
   workflow actually changes.
2. **A Feedback-loops line in the contract:** after changing a workflow, confirm it
   passed on GitHub — `gh run watch`; if `gh` isn't set up, ask the maintainer to check
   the repo's Actions tab. This is the **only reliable catch** for a missing or
   out-of-date action (local checks can't see it).

Dogfood both here. Dependabot's `github-actions` ecosystem (already scaffolded) covers
stale/deprecated actions over time.

## Consequences

- Generated projects catch a class of workflow bugs author-time (actionlint) and carry
  an explicit instruction to verify the real run — closing the loop without a human.
- `actionlint-py` self-installs via pip; no extra toolchain.
- Honest limit: actionlint doesn't resolve action tags over the network, so it would
  *not* have caught `@v1`; the live-run check (and Dependabot, over time) covers that.

## Alternatives considered

- **Official `rhysd/actionlint` hook:** needs Go or Docker locally — rejected for the
  toolchain dependency; `actionlint-py` self-installs via pip.
- **Contract line only, no actionlint:** leaves author-time workflow bugs uncaught.
- **A new contract bullet for CI:** rejected — folded into the Feedback-loops pillar to
  keep the three-pillar structure.
