# Architecture overview

`agent-native-setup` is a Python CLI that scaffolds an agent-native setup into a target
repo. It reads a `WizardConfig`, then a set of generators write files through a
`Scaffolder`. There is no runtime service. Beyond the one-shot scaffold, an `update`
subcommand refreshes an already-scaffolded project to a newer version of the setup, using
the provenance recorded in `.agent-native-setup.json`.

## Components

| Module | Responsibility |
| --- | --- |
| `cli.py` | Entry point (`agent-native-setup`). Parses flags / runs the interactive prompts, detects languages, builds the `WizardConfig`, and orchestrates `build()`. |
| `config.py` | `WizardConfig` — the immutable-ish description of what to scaffold. A leaf: no project imports. |
| `languages.py` | The `Language` registry (linters, pre-commit hooks, CI steps, configs per language) and `detect_languages()`. Adding a language = one `Language` entry. |
| `pins.py` | Every version the wizard pins into generated output (toolchains, hook revs, npm ranges), as one `PINS` dict. Templates carry `@KEY@` tokens resolved by `sub()` at import time. A leaf: no project imports. |
| `scaffold.py` | `Scaffolder` — writes files under the target, records what it created and snapshots what `--force` overwrote (for rollback), fingerprints each write (for the manifest), and renders Jinja templates. Knows nothing about the generators. |
| `manifest.py` | Writes `.agent-native-setup.json` into each scaffolded project — version + resolved config + a fingerprint per written file (transient one-time files like `ONBOARDING.md` excluded) — so `update` can refresh pristine generated files without clobbering edits. Records provenance only; update *policy* lives in `update.py`. A leaf: imports the version, `config`, `scaffold`. |
| `update.py` | The `update` subcommand. Regenerates from the recorded config and **classifies** each file (create / refresh-pristine / conflict / orphan) so pristine managed files refresh while edited and user-owned files are left as reported conflicts. Requires a clean git tree (or `--dry-run`); writes an `UPDATING.md` runbook. `--dry-run` also serves as a conformance/drift check, and `--check` prints a one-line staleness nudge. |
| `versioning.py` | Semver as a difficulty contract: `breaking_series` + `decide` (NOOP / DOWNGRADE / AUTOPILOT / GATED). Shared by the update gate and the release guard so they can't drift. A leaf. |
| `migrations.py` | Ordered, version-keyed structural migrations (`auto` idempotent moves, `agent`/`manual` steps) replayed across the installed→latest span on update, with the agent steps aggregated into `UPDATING.md`. |
| `update_check.py` | Cached "is there a newer release?" lookup (GitHub), shared by the end-of-run nudge and the SessionStart `update --check`. |
| `generators/` | One module per concern — `ai_context` (AGENTS.md + per-tool entry points: CLAUDE.md/GEMINI.md symlinks, Cursor/Copilot pointer files, plus an optional self-removing first-run banner), `agents` (`.claude/`), `docs` (docs tree + RFC lifecycle + embedded check scripts), `quality` (pre-commit, Taskfile, gitignore), `ci` (GitHub Actions), `onboarding` (the self-deleting `ONBOARDING.md` first-run runbook, whose last step also removes the banner). Each exposes `generate(config, sc)`. |
| `tools/checks/` | Standalone enforcement scripts run as hooks: `sync_rfc_status.py` (any project with docs), `rfc_needed.py` (any language with a dependency manifest — its dep trigger reads pyproject.toml/package.json/go.mod/Cargo.toml), `docs_sync.py` and `tests_needed.py` (Python `src/`+`tests/` layout), and `format_on_edit.py` (the Claude PostToolUse format-on-edit helper). Each ships with a stdlib-`unittest` test, run via `python -m unittest discover -s tools/checks` (wired into the command surface, a pre-push hook, and CI). The wizard embeds the scripts and their tests as constants in `generators/docs.py` (gates) and `generators/agents.py` (format hook). |

Flow: `cli.build()` → `ai_context` → `agents` → `docs` → `quality` → `ci`, each
gated on the matching `include_*` flag, then `onboarding` (gated on
`include_quality or include_ci`), and finally `manifest.write()` to record provenance.

## Dependency rules

- **Generators depend inward only.** `generators/*` may import `config`, `languages`,
  `pins`, and `scaffold` — plus constants a sibling generator owns (e.g.
  `quality.IMPROVEMENT_USAGE`, so the target and every mention of it stay in step) —
  but **must not import `cli`**: generation never reaches back into the orchestrator.
  Enforced by `tests/test_architecture.py`.
- **`config`, `languages`, `pins`, `scaffold`, and `manifest` are leaves** — they don't
  import the generators or the CLI. (Flat layout limits mechanical enforcement to the
  `generators/` boundary above; keep these leaves leaf-like by convention.)
- `cli` sits on top and may import everything.
