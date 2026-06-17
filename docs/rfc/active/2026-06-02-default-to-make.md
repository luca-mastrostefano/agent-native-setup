# Default the generated runner to Make (zero-install); keep Task on detection/opt-in

- **Status:** Active
- **Date:** 2026-06-02
- **Author:** Luca Mastrostefano

## Context

The generated setup defaults to **Task**, which must be installed (`brew install
go-task`, …). So the first instruction we print — `task install` — and the
`SessionStart` `task --list` hook both fail on a machine without it. `make` is
essentially ubiquitous on Unix/macOS and more widely available than `task` overall,
so for a runner *imposed on arbitrary projects* it's the lower-friction default.

The runner is a thin local-dev convenience — **CI doesn't use it** — so ubiquity
matters more than Task's nicer ergonomics when it's a default handed to others.
(`pre-commit` is still required regardless; it's pip-installable.)

## Decision

- **Fresh project (no runner detected) → generate a self-documenting `Makefile`**
  (a `help` target + `## ` target descriptions) and speak `make` in the command
  surface, README quickstart, and SessionStart hook.
- **`--runner task`** opts back into a generated `Taskfile`.
- **An existing `Taskfile`/`Makefile` is still detected and deferred to** (unchanged).
  A detected `Taskfile` means `task` is assumed installed (they wrote it).
- **SessionStart hook gains a missing-runner guard:**
  `command -v <runner> >/dev/null 2>&1 && <list> || echo "<install hint>"`, so a
  missing tool prints a hint instead of a raw error. Discovery is `task --list`
  (Task), `make help` (our generated Makefile), or a target grep (an existing
  Makefile).
- This repo **keeps its `Taskfile` automatically** — it's a detected existing runner,
  so there's no dogfood churn.

## Consequences

- A fresh project needs nothing installed for the wrapper (make is present); only
  `pre-commit` remains a prerequisite, now documented in the generated README.
- Make's ergonomics are weaker than Task's — mitigated by generating a
  self-documenting Makefile (`make help`).
- **Windows** has no `make` by default (WSL/choco) — documented; `--runner task`
  remains for Task shops.
- New generator artifact: a `Makefile` template alongside the `Taskfile` one.

## Alternatives considered

- **Keep Task as default + just document the install:** rejected — still imposes an
  install for the common, fresh-project case.
- **No runner at all (raw commands only):** rejected — loses the standard command
  surface the project deliberately provides.
- **Per-platform auto-install of `task`:** rejected — installing system binaries is
  environment-specific and intrusive, outside a scaffolder's remit.
