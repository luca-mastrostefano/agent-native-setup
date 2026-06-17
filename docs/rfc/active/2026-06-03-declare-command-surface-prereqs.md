# Declare the command surface's Python prerequisites (+ onboarding nits)

- **Status:** Active
- **Date:** 2026-06-03
- **Author:** Luca Mastrostefano

## Context

A second `clinic_slack` onboarding retrospective found the generated command surface
(`make lint/format/quality`) calls `ruff` (and, for Python projects, `mypy`/`pytest`)
directly, but nothing installs or declares them: `make bootstrap` only runs
`pre-commit install` + `npm install`, and neither `README` nor `ONBOARDING` lists `ruff`.
It only worked because the onboarding machine happened to have `ruff` on PATH; a clean
machine would fail at the first ruff call. (Node tools come from `npm install`; the managed
pre-commit hooks pin their own ruff; CI uses `pipx install ruff` — but the *local* command
surface assumes a system ruff nothing guarantees.)

The same run surfaced three smaller nits: `.ruff_cache/` wasn't gitignored for `node+docs`
projects (it relied on ruff's self-ignore); the `CLAUDE.md → AGENTS.md` symlink was
undocumented, briefly confusing the agent into editing `CLAUDE.md` separately; and the
cleanup-commit "no CI watch needed" claim is overconfident when `lychee` link-checks the
edited docs.

## Decision

1. **Declare the Python command-surface tools as prerequisites** — *not* auto-install them
   (`pipx`/`uv`/`pip` are each unguaranteed or fragile, as an earlier finding showed). A new
   `WizardConfig.python_surface_tools` is the single source: `ruff` whenever Python helpers
   ship, plus `mypy`/`pytest` with a Python project. Surfaced in the `README` quickstart and
   the `ONBOARDING` baseline step.
2. **Gitignore `.ruff_cache/`** for `ships_tools_python` projects (the `tools/` ruff hook
   drops it at the repo root).
3. **Flag the `CLAUDE.md → AGENTS.md` symlink** in the cleanup step — in the self-deleting
   runbook only, not the permanent contract.
4. **Gate the cleanup "no CI watch needed" claim** on the absence of HTML/`lychee`; with
   link-checking in CI, the runbook keeps the watch.

## Consequences

- `make quality` no longer has an undeclared dependency; a clean-machine clone is told what
  to install.
- The onboarding agent skips the `.ruff_cache` investigation and the `CLAUDE.md` detour, and
  isn't told to skip a watch that link-checking actually needs.
- Wording / one-line cost; no behavior change to the tooling itself.

## Alternatives considered

- **Auto-install ruff in `make bootstrap`** (`pipx`/`uv`/`pip`): fragile — `pipx` isn't
  guaranteed, `pip install` hits externally-managed-env errors, `uv` isn't guaranteed.
  Declaring matches how the `pre-commit`/`lychee`/`node` prereqs are already handled.
- **A `[project.optional-dependencies] dev` group + `pip install -e .[dev]` in bootstrap:**
  cleaner provisioning for Python projects, but assumes a venv and doesn't help `node+docs`
  (no pyproject). Deferred.
- **Put the `CLAUDE.md` note in the permanent contract:** clutters it forever for a one-time
  onboarding confusion.
