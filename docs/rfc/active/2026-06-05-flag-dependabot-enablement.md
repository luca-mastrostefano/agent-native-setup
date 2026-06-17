# Flag enabling Dependabot security updates in onboarding

- **Status:** Active
- **Date:** 2026-06-05
- **Author:** Luca Mastrostefano

## Context

The wizard writes `.github/dependabot.yml`, which drives **version updates** (the file is
the switch — committing it is enough). But Dependabot **security updates** (the vuln-fix
PRs) are a repo *setting*, not the file: **on by default for public repos**, but a manual
toggle for **private** ones (Settings → Code security, or the REST API). Onboarding never
said so — so on a private repo the security-only config (the wizard's existing-repo default)
silently does nothing, and a maintainer hit exactly that. The existing-repo
`dependabot.yml` comment also said security updates apply *"once enabled in Settings,"*
which overstates it for public repos.

## Decision

Add a maintainer step to onboarding, gated on CI/GitHub Actions (i.e. when `dependabot.yml`
is scaffolded): turn on Dependabot's security updates — on by default for public repos; for
private, `gh api --method PUT repos/{owner}/{repo}/vulnerability-alerts` then
`.../automated-security-fixes` (both need repo admin, both idempotent), else Settings →
Code security. Fix the existing-repo `dependabot.yml` comment to say *public = on by
default, private = a Settings toggle*. Both verified against GitHub's REST docs.

## Consequences

- A maintainer no longer leaves Dependabot's security updates off because nothing told them
  to enable it — closing the gap for private repos especially.
- One onboarding line + a comment fix. On public repos the `gh` calls are confirming
  no-ops (idempotent), so the step is safe to follow everywhere.

## Alternatives considered

- **Have the agent always run the `gh` PUTs silently:** they're idempotent and benign, but
  it's a repo-settings change needing admin — framing it as a visible step (not a hidden
  side effect) is more honest, and degrades to the Settings UI when `gh` lacks admin.
- **Only fix the `dependabot.yml` comment:** studyable but easy to miss; the onboarding step
  makes it actionable.
- **Document in the README only:** onboarding is where one-time first-run setup belongs.
