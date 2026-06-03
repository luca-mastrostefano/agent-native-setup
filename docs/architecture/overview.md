# Architecture overview

`ai-project-setup` is a Python CLI that scaffolds an AI-native setup into a target
repo. It reads a `WizardConfig`, then a set of generators write files through a
`Scaffolder`. There is no runtime service — it's a one-shot generator.

## Components

| Module | Responsibility |
| --- | --- |
| `cli.py` | Entry point (`ai-setup`). Parses flags / runs the interactive prompts, detects languages, builds the `WizardConfig`, and orchestrates `build()`. |
| `config.py` | `WizardConfig` — the immutable-ish description of what to scaffold. A leaf: no project imports. |
| `languages.py` | The `Language` registry (linters, pre-commit hooks, CI steps, configs per language) and `detect_languages()`. Adding a language = one `Language` entry. |
| `scaffold.py` | `Scaffolder` — writes files under the target, records what it created (for rollback), and renders Jinja templates. Knows nothing about the generators. |
| `generators/` | One module per concern — `ai_context` (AGENTS.md/CLAUDE.md, plus an optional self-removing first-run banner), `agents` (`.claude/`), `docs` (docs tree + RFC lifecycle + embedded check scripts), `quality` (pre-commit, Taskfile, gitignore), `ci` (GitHub Actions), `onboarding` (the self-deleting `ONBOARDING.md` first-run runbook, whose last step also removes the banner). Each exposes `generate(config, sc)`. |
| `tools/checks/` | Standalone enforcement scripts run as git hooks: `sync_rfc_status.py` (shipped with docs for any project), plus `rfc_needed.py` / `docs_sync.py` (Python projects). Each ships with a stdlib-`unittest` test, run via `python -m unittest discover -s tools/checks` (wired into the command surface, a pre-push hook, and CI). The wizard embeds the scripts and their tests as constants in `generators/docs.py`. |

Flow: `cli.build()` → `ai_context` → `agents` → `docs` → `quality` → `ci`, each
gated on the matching `include_*` flag, then `onboarding` (gated on
`include_quality or include_ci`).

## Dependency rules

- **Generators depend inward only.** `generators/*` may import `config`, `languages`,
  and `scaffold`, but **must not import `cli`** — generation never reaches back into
  the orchestrator. Enforced by `tests/test_architecture.py`.
- **`config`, `languages`, and `scaffold` are leaves** — they don't import the
  generators or the CLI. (Flat layout limits mechanical enforcement to the
  `generators/` boundary above; keep these leaves leaf-like by convention.)
- `cli` sits on top and may import everything.
