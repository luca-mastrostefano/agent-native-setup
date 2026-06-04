# Give the gitleaks checks job the PR-read permission it needs

- **Status:** Accepted
- **Date:** 2026-06-04
- **Author:** Luca Mastrostefano

## Context

A scaffolded project's **first PR** failed in CI: `gitleaks-action` returned a 403. Root
cause: the generated `quality.yml` sets `permissions: contents: read` at the workflow
level (the `engineering-baseline-files` least-privilege RFC), and the `checks` job — which
runs gitleaks — inherits only that. But `gitleaks-action` calls the GitHub **PR API on
every `pull_request`** (listing the PR's commits to scan), which needs `pull-requests`
access, and by default also posts findings as PR comments (which needs
`pull-requests: write`). With only `contents: read` it 403s. It never surfaced earlier
because push-to-`main` events don't touch the PR API — only the repo's first PR did.

## Decision

Give the `checks` job a job-scoped `permissions: { contents: read, pull-requests: read }`,
and disable gitleaks PR comments (`GITLEAKS_ENABLE_COMMENTS: "false"`). The PR-API *read*
(list commits) is what the scan needs; disabling comments avoids the `pull-requests: write`
the comment API would require. CI stays **read-only** — consistent with the least-privilege
posture — and a leak still **fails the job** and appears in the run log; it just isn't
posted as an inline PR comment. The main `quality` job is untouched (still `contents: read`).

## Consequences

- gitleaks runs on PRs (not just push) without 403ing — the secret scan actually works on
  the path that matters, the first PR.
- CI never gains write permissions; the `contents: read` posture holds, now job-scoped
  where a job genuinely needs one read beyond it.
- Trade-off: no inline PR comment for a detected secret (it's in the run log/summary).
  Teams that want comments can switch the job to `pull-requests: write` and re-enable
  `GITLEAKS_ENABLE_COMMENTS`.

## Alternatives considered

- **`pull-requests: write` (keep comments):** the action's default and better DX, but
  grants CI PR-write in every generated repo — at odds with the least-privilege RFC.
- **Drop the CI gitleaks step (rely on the pre-commit hook):** loses the CI backstop that
  catches secrets a contributor committed with `--no-verify` or without hooks installed.
