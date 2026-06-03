# Trim two recurring time sinks from the first-run onboarding

- **Status:** Accepted
- **Date:** 2026-06-03
- **Author:** Luca Mastrostefano

## Context

The first onboarding retrospective (`scaffold-review.md` §2) put active work at ~12–15
min, with wall-clock dominated by one-time installs, CI round-trips, and a one-off
remote-ambiguity clarification loop (not a scaffold issue). The biggest *active* chunk —
hand-wiring Python lint/format/test for the shipped `tools/checks/*.py` — is now
eliminated: the scaffold ships that tooling itself (the ruff guard plus the test/runner
from `2026-06-03-test-shipped-tools-checks.md`).

Two recurring sinks remain that the runbook can cheaply trim:

- **Recon over-reading.** The retrospective spent ~3–4 min reading *every*
  config/doc/workflow/tool file before starting. Most steps don't need that.
- **A redundant CI wait.** Onboarding ends with a docs-only cleanup commit (delete
  `ONBOARDING.md`, remove the banner / `/onboard`). Watching CI for it is a wasted
  round-trip — removing setup scaffolding can't break the build.

## Decision

Two runbook wording changes in `generators/onboarding.py`:

1. **Scope the recon.** The first step says `AGENTS.md` + the runbook are all you need to
   start — don't pre-read the whole repo; open other files only when a step calls for them.
2. **Skip the cleanup commit's CI watch.** The final cleanup step (when CI exists) says to
   commit and push it but notes it only removes setup scaffolding, so no `gh run watch` is
   needed. The single CI confirmation stays on the first push.

Both are guidance in the generated `ONBOARDING.md`; the existing "background the installs,
parallelize independent steps, keep the baseline→commit→push→CI chain serial" note already
covers the install/CI overlap.

## Consequences

- Removes a full CI round-trip and curbs the recon read, on top of the step-6 work the
  scaffold now does itself — a normal run is meaningfully shorter.
- Tiny wording cost; no behavior change to the tooling, only to the runbook's advice.

## Alternatives considered

- **Collapse the two onboarding commits into one.** Saves a whole commit→push→CI cycle,
  but the cleanup is deliberately separate so CI is confirmed green *before* the runbook is
  deleted. Kept the two-commit ordering: the safety margin is worth one commit, and the
  win here (no second CI watch) captures most of the time anyway.
- **Pre-authorize the direct-to-`main` push** in `.claude/settings.json` to skip the
  approval prompt: rejected — it bakes an un-prompted push-to-`main` default into every
  scaffolded repo (see `2026-06-03-test-shipped-tools-checks.md`, which only *flags* the
  prompt).
- **Drop hooks or the `code-reviewer` step for speed:** trades quality/security for
  seconds. No.
