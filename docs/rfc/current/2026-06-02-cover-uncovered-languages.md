# Instruct the agent to wire up languages the setup doesn't cover

- **Status:** Accepted
- **Date:** 2026-06-02
- **Author:** Luca Mastrostefano

## Context

The `Language` registry covers python/node/go/rust/html, and the wizard can't even
*detect* a language outside that set. So a project in an uncovered language (Ruby,
Java, C#, Elixir, …) gets the base hooks + gitleaks but **no linter, formatter,
type-check, or test wiring for its actual stack** — and silently, since the wizard
never knew. The wizard can't fix this for languages it doesn't know; the **contract**
can, because the agent working in the repo sees the real stack.

## Decision

Extend the contract's **Mechanical enforcement** bullet to instruct: if a language in
the repo isn't yet wired up for linting, formatting, and tests, add it the way the
existing ones are — a pre-commit hook, a CI step, and a command-surface entry — rather
than leaving it unguarded. The wording is framed by what's *observable in the repo* (a
language with no tooling), not by "what the wizard covered," which the downstream agent
can't know. In a *generated* project the agent edits the
project's own `.pre-commit-config.yaml` / CI / runner (not the wizard's registry, which
it doesn't have). Dogfood the wording into this repo's own `AGENTS.md`.

## Consequences

- Uncovered languages no longer fall through silently — the agent extends enforcement
  to the project's real stack, in the established conventions, leveraging the agent for
  the long tail the registry can't reach.
- It's guidance (the contract), not mechanical enforcement — it relies on the agent
  reading and following the contract, like the other principles.

## Alternatives considered

- **Add more languages to the registry:** doesn't scale to every language; the contract
  handles the long tail with one instruction.
- **Leave it:** uncovered stacks stay unguarded and the gap is invisible at scaffold time.
