# Wire the code-reviewer into the loop: self-review before "done"

- **Status:** Accepted
- **Date:** 2026-06-02
- **Author:** Luca Mastrostefano

## Context

We scaffold a `code-reviewer` subagent and a `/review` command, but **nothing in the
contract tells the agent to use them** — it's a dormant asset, only invoked if a human
remembers to. A separate review/critique pass before declaring a change done is a
widely-recognized agentic practice: it catches what the author's own pass misses (the
same rationale as adversarial verification). The machinery already exists; we just
aren't closing the loop with it.

## Decision

Add a line to the contract's **Feedback loops** pillar, gated on the agents being
scaffolded: *before calling a non-trivial change done, run the `code-reviewer`
(`/review`) on your diff and resolve its findings.* Dogfood it into this repo's
`AGENTS.md`.

## Consequences

- Activates something we already ship, closing the loop author → self-review → done.
- Costs one contract line; "non-trivial" keeps it from being busywork on tiny edits.
- Rendered only when `.claude/` agents are scaffolded (gated on the existing `agents`
  flag), so it never points at a command that wasn't generated.

## Alternatives considered

- **Leave the reviewer invocable-but-unmentioned** (status quo): the asset stays
  dormant; the loop relies on a human remembering to run `/review`.
- **Mandate review on every change:** too heavy for trivial edits; "non-trivial" scopes
  it sensibly.
