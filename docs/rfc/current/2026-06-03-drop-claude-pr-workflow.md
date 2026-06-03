# Drop the @claude PR workflow — out of scope

- **Status:** Accepted
- **Date:** 2026-06-03
- **Author:** Luca Mastrostefano

## Context

The wizard scaffolded `.github/workflows/claude.yml` — a GitHub Actions bot that runs
Claude on `@claude` PR/issue comments — for every Claude-targeted repo with CI, and made
onboarding ask for an `ANTHROPIC_API_KEY` secret. But that's a *runtime* feature of the
target repo (an agent acting in CI), orthogonal to this product's job: scaffolding an
AI-native project *setup*. A fresh project doesn't know it wants an agent in PR checks and
isn't responsible for one, so the workflow doesn't belong in the scaffold — not even as an
opt-in toggle on this product.

This supersedes the briefly-considered "make it opt-in" direction: the issue isn't the
default, it's scope.

## Decision

Remove the `@claude` workflow from the wizard entirely: drop `CLAUDE_WORKFLOW` and its
generation in `ci.py`, the `ANTHROPIC_API_KEY` onboarding step, the `claude_pr_bot` config
flag, and the README/HOW_TO_USE references. The *local* Claude integration stays —
`.claude/` agents and commands, the `CLAUDE.md` symlink, `/onboard` / `/review` / the
`/security-review` pointer — since those configure agentic development *of* the project,
which is exactly this product's job. Also drop this repo's own dogfooded `claude.yml`.

## Consequences

- The scaffold no longer ships a dormant, key-less workflow or an onboarding step for a
  secret a fresh project doesn't need.
- A team that wants an `@claude` PR bot adds it themselves — a separate concern with its
  own docs, not something this scaffolder owns.
- `claude` as an AI tool still drives all the local integration; only the CI bot is gone.

## Alternatives considered

- **Make it opt-in** (a `--claude-pr` flag): rejected — keeping it as a product toggle
  still implies the scaffolder is in the business of deploying agents into CI, which it
  isn't.
- **Keep it, reframe the key as optional:** still ships a workflow the project owns and
  presents the key as a setup concern.
