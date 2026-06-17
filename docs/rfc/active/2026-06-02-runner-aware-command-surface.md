# Runner-aware command surface + live task list at session start

- **Status:** Active
- **Date:** 2026-06-02
- **Author:** Luca Mastrostefano

## Context

The wizard hardcodes **Task**: it always writes `Taskfile.yml`, and the `AGENTS.md`
command surface lists `task ...`. Scaffolding into a repo that already uses **Make**
(or has its own `Taskfile`) forces a second runner and a contract that references
commands the project doesn't have — against the non-destructive, accommodate-existing
ethos.

Separately, that command surface is a *static snapshot*. An agent doesn't get the
project's **live** task list in its context at session start, and the snapshot drifts
as tasks are added.

## Decision

1. **Detect the runner.** `Taskfile.yml`/`.yaml` → Task (existing); else
   `Makefile`/`makefile`/`GNUmakefile` → Make (existing); else → Task (ours). Record
   `runner` (`task`|`make`) and `existing_runner` (bool).
2. **Defer to an existing runner.** When one exists, do **not** write `Taskfile.yml`
   and never modify their file.
3. **Runner-aware command surface in `AGENTS.md`:**
   - *ours (no existing runner):* `task <x>` commands + "run `task --list`".
   - *existing runner:* the **raw** commands (`ruff check .`, `pytest`,
     `pre-commit install`) + "this repo uses Task/Make — its targets are the source of
     truth; run `task --list` / grep the `Makefile`; add any missing ones as targets."
   - both get the **capture directive**: when you work out a repeatable process, add it
     to the runner as a task/target with a one-line description.
4. **Live list at session start** via a scaffolded Claude Code **`SessionStart` hook**
   in `.claude/settings.json` that runs the runner's list command and injects the
   output (confirmed: SessionStart stdout / `additionalContext` is inserted before the
   first prompt):
   - Task: `task --list`.
   - Make: grep self-documenting `## ` targets, falling back to bare target names
     (Make has no built-in lister).
5. The README quickstart's `task` block renders only when we own the runner.

## Consequences

- An existing runner is respected; there is one command surface and one runner; on
  Claude Code the agent gets the **live** list at startup with zero hand-maintained
  snapshot to drift.
- Make has no built-in lister, so its list is grepped from `## ` annotations
  (names-only until annotated); the capture directive drives convergence to described
  targets. Task is self-describing out of the box.
- One new generated file, `.claude/settings.json` (skipped if one already exists —
  non-destructive; settings-merging is not attempted).
- Cursor/Copilot have no session-context hook, so they don't get auto-injection; they
  rely on the static surface + the directive to run the list command on demand.

## Alternatives considered

- **Bake a task-list snapshot into `AGENTS.md`:** in context at start but drifts; the
  SessionStart hook gives the live list with no drift.
- **Auto-merge our targets into the existing `Taskfile`/`Makefile`:** rejected —
  round-tripping YAML/Make without mangling comments and structure isn't safe, and it
  breaks the non-destructive guarantee. The capture directive converges safely instead.
- **Rely only on the agent running `task --list`:** unreliable (depends on the agent
  choosing to); the hook makes it automatic on Claude Code.
