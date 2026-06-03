# First-run banner: let the agent self-onboard from AGENTS.md

- **Status:** Accepted
- **Date:** 2026-06-03
- **Author:** Luca Mastrostefano

## Context

`ONBOARDING.md` carries the one-time bootstrap, but reaching it relied on a human
remembering to type `/onboard` or open the file. The thing every AI assistant
*does* read automatically is `AGENTS.md` (Claude via the `CLAUDE.md` symlink,
Cursor/Copilot via their pointer files). So the most reliable trigger is a note
*in `AGENTS.md` itself* — but `AGENTS.md` is the standing contract, and permanent
bootstrap text there would re-fire every session.

## Decision

Optionally inject a **self-removing** banner at the top of `AGENTS.md`: a
delimited `<!-- ai-setup:first-run -->` block telling the agent that the repo was
AI-scaffolded, onboarding hasn't run, and it should complete `ONBOARDING.md`
first. The **last onboarding step removes the banner** (and deletes
`ONBOARDING.md`), so it exists only during the bootstrap window — resolving the
"one-time steps don't belong in the contract" tension by making them transient.

- Gated by a wizard prompt / `--no-first-run-banner` flag, default **on**, offered
  only when onboarding will exist and at least one AI tool is targeted.
- The HTML-comment delimiters make removal mechanical and unambiguous.
- `ONBOARDING.md`'s header now states it was scaffolded by `ai-setup` and speaks to
  an agent on its first session.
- The end-of-run summary, when the banner is on, tells the human to simply open the
  project in their assistant — it self-onboards.

## Consequences

- Closes the loop without human action: open the repo in an agent → it onboards.
- Self-removing, so it never becomes stale standing-contract noise — *provided*
  the agent completes onboarding. A clearly-labelled, delimited block keeps a
  lingering banner obviously transient if onboarding is interrupted.
- Suppressed when no `ONBOARDING.md` is generated, so it never dangles.

## Alternatives considered

- **Permanent line in `AGENTS.md`:** pollutes every future session with bootstrap
  noise — the reason the runbook is a separate file in the first place.
- **Rely on `/onboard` only:** needs a human to remember it, and it's Claude-only.
