# Scope agent context down as the repo grows (nested contracts + per-subsystem docs)

- **Status:** Accepted
- **Date:** 2026-06-06
- **Author:** Luca Mastrostefano

## Context

The wizard scaffolds a single `docs/architecture/overview.md` and a single root contract.
Neither tells the agent what to do when one file stops being enough — and **Simplicity
First actively nudges the wrong way** ("no structure that wasn't requested"), so an agent
tends to keep cramming one file rather than split. The question raised: how does the agent
know when to give a subsystem its own architecture doc, or a subdirectory its own rules?

Three placements were weighed:

- **In `overview.md` itself** — rejected: it's *content* (the architecture map, meant to be
  studied), not an instruction file. Putting "how to organize these docs" meta inside it is
  a category error.
- **In `docs/README.md`** (the docs index) — right category, but read *on demand*; we can't
  rely on it being seen, which is exactly the reliability worry.
- **A recursive / nested `AGENTS.md` structure** — the established standard (the AGENTS.md
  spec: "agents automatically read the nearest file… the closest one takes precedence";
  OpenAI's monorepo has 88). Verified against Claude Code's docs, two facts shape how we
  use it: Claude Code reads **`CLAUDE.md`, not `AGENTS.md`**, and nested files load
  **lazily** (when the agent touches files in that subtree), not at startup.

## Decision

Don't have the wizard *scatter* nested files into the fresh, small repos it creates — for a
one-package project that's premature structure, and the per-tool split (Claude needs a
nested `CLAUDE.md`) makes it messy. Instead, **name the convention in the root contract**
(auto-loaded = reliable, which the on-demand docs index is not), doing two jobs at once:

- **Nested contracts as the scaling path** — a directory with rules of its own can carry a
  local `AGENTS.md` that agents follow as the nearest contract. For Claude targets the note
  adds: put a `CLAUDE.md` symlink beside it, like the root — Claude loads `CLAUDE.md`, not a
  bare nested `AGENTS.md`. (Gated to Claude targets.)
- **Per-subsystem architecture docs** — give a subsystem its own
  `docs/architecture/<name>.md` and keep `overview.md` the index, so no one file becomes a
  monolith. (Gated to `docs`.)

This rides in the existing "Context" bullet under *How this project stays agent-native*.
`overview.md` stays pure content. Dogfooded into this repo's `AGENTS.md`.

## Consequences

- The agent gets a reliable, always-loaded signal to scope context down as the project
  grows — and the recursive-contract pattern is documented so it's adopted *deliberately*
  when the repo grows into one that needs it, not pre-scattered on day one.
- The lazy-load timing of nested `CLAUDE.md` is actually a good fit: a directory's local
  rules load exactly when the agent works in that subtree.
- Enforcement already exists and is directory-aware: the `docs-sync` commit-msg hook and the
  reviewer's docs-in-sync lens work on *any* file under `docs/architecture/`, not just
  `overview.md`.

## Alternatives considered

- **A note inside `overview.md`:** category error — content file, not an instruction file.
- **Only `docs/README.md`:** right category, but read on demand; no guaranteed pickup.
- **Have the wizard generate nested contracts by default:** premature structure for the
  small repos it scaffolds, and splits the clean single-canonical-contract model per tool.
- **A new `code-reviewer` "this doc is too big, split it" lens:** rejected — same
  over-prescription/nag risk we scoped out of the cohesion lens; the reviewer's job for docs
  is catching *staleness*, not pushing reorganizations.
