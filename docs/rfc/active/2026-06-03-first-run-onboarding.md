# First-run onboarding: a self-deleting bootstrap runbook

- **Status:** Active
- **Date:** 2026-06-03
- **Author:** Luca Mastrostefano

## Context

A freshly scaffolded repo needs a handful of *one-time* actions before it's
actually live: install the git hooks, take a baseline `quality` run, adopt the
gate on legacy code, flesh out the architecture stub, confirm the first CI run.
`AGENTS.md` already auto-loads for AI assistants, but it's the **standing
contract** — putting one-time bootstrap steps there would mean re-surfacing them
every session. So the first run was implicit: the user had to know what to do.

## Decision

Generate **`ONBOARDING.md`** — a numbered, config-driven runbook of exactly the
one-time steps for *this* scaffold — whenever there's tooling to activate
(`include_quality or include_ci`). It ends by instructing the agent to delete
itself, so it never lingers as stale documentation.

Kick-off is the lowest-friction option per target:

- **Claude** — a scaffolded `/onboard` slash command (mirrors `/review`) reads
  and executes the file. One token, discoverable; the runbook's final step removes
  the command too, so it doesn't linger pointing at a deleted file.
- **Cursor/Copilot** — the wizard's closing summary prints a one-line "point your
  agent at ONBOARDING.md" pointer.

The summary shows only the line that matches the selected tools, so the user
never parses an if/else.

## Consequences

- Closes the "what now?" gap after the wizard without bloating the contract.
- One new generator (`generators/onboarding.py`) + one command constant; both the
  file and the `/onboard` command self-delete on completion, so it adds no
  long-lived surface to the generated repo.
- Not dogfooded into this repo: it's a *first-run* artifact and this repo is long
  past onboarding — an `ONBOARDING.md` here would be stale on arrival.

## Alternatives considered

- **Print the full instructions to the terminal** (no file): ephemeral, can't be
  re-run, and is the "knowledge left in a chat" anti-pattern the contract warns
  against.
- **Fold the steps into `AGENTS.md`**: pollutes every future session with
  one-time setup noise.
