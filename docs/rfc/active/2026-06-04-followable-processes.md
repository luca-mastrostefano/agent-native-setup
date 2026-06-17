# Tell the agent to make long/background commands followable

- **Status:** Active
- **Date:** 2026-06-04
- **Author:** Luca Mastrostefano

## Context

A recurring, costly, and non-obvious failure: when an agent runs a long-running or
backgrounded command, the program's stdout **block-buffers** (stdout isn't a TTY), so
progress sits in the buffer until it fills or the process exits — the job looks frozen and
you wait blind. Agents add log lines, but they don't surface, because the buffer holds them.

## Decision

Add **one line** to the contract's operational reminders — the "Feedback loops" tail, next
to *"verify CI"* and *"re-stage after `git add`"*, **not** the four principles, to avoid
bloating the core: make long-running or backgrounded commands **followable** — run them
unbuffered (`python -u` / `PYTHONUNBUFFERED=1` / `stdbuf -oL`) and `tee` to a logfile — so
progress streams instead of buffering silently. Dogfood into this repo's `AGENTS.md`. (Also
mirrored, for the maintainer, in a global `~/.claude/CLAUDE.md`.)

## Consequences

- Removes the common "is it still working?" blind-wait when an agent backgrounds a build,
  install, or migration.
- One line, placed with the existing operational reminders, so it doesn't grow the
  principles. The directive earns its place because the failure is frequent and the fix
  isn't obvious — buffering is invisible.

## Alternatives considered

- **Leave it:** the blind-wait recurs in every repo.
- **Enforce mechanically (a command wrapper):** heavier, and can't cover ad-hoc agent
  commands; a one-line habit is the right tool for agent *behavior*.
- **Put it among the four principles:** over-weights a working-habit; the operational-tail
  placement keeps the core lean.
