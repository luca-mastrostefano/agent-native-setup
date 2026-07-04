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
| `scaffold.py` | `Scaffolder` — writes files under the target, records what it created and snapshots what `--force` overwrote (for rollback), fingerprints each write (for the manifest), and renders Jinja templates through a **`SandboxedEnvironment`** (profile templates are untrusted input — RFC 2026-07-03-profile-safety). Knows nothing about the generators. |
| `manifest.py` | Writes `.agent-native-setup.json` into each scaffolded project — version + resolved config + a fingerprint per written file (transient one-time files like `ONBOARDING.md` excluded) — so `update` can refresh pristine generated files without clobbering edits. Records provenance only; update *policy* lives in `update.py`. A leaf: imports the version, `config`, `scaffold`. |
| `update.py` | The `update` subcommand. Regenerates from the recorded config and **classifies** each file (create / refresh-pristine / conflict / orphan) so pristine managed files refresh while edited and user-owned files are left as reported conflicts. Requires a clean git tree (or `--dry-run`); writes an `UPDATING.md` runbook. `--dry-run` also serves as a conformance/drift check, and `--check` prints a one-line staleness nudge. |
| `versioning.py` | Semver as a difficulty contract: `breaking_series` + `decide` (NOOP / DOWNGRADE / AUTOPILOT / GATED). Shared by the update gate and the release guard so they can't drift. A leaf. |
| `migrations.py` | Ordered, version-keyed structural migrations (`auto` idempotent moves, `agent`/`manual` steps) replayed across the installed→latest span on update, with the agent steps aggregated into `UPDATING.md`. |
| `update_check.py` | Cached "is there a newer release?" lookup (GitHub), shared by the end-of-run nudge and the SessionStart `update --check`. |
| `profiles.py` | Profiles (RFC 2026-06-23): load/resolve a profile (a dir with `profile.json` + `templates/`) and **overlay** it on the default scaffold (`extends: default`) — or run it **standalone** (`extends: null`: `cli.build` skips the default generators, the profile provides everything). Profile files are managed (refreshed on update) unless listed in the profile's `seed`. A profile can also declare `prompts` (a declarative wizard — answers exposed to templates as `answers.<name>`, with optional `when` conditions, recorded + replayed on update, headless overrides via the repeatable `--answer NAME=VALUE` flag, a `.j2` that renders empty is skipped), read detected/resolved environment facts under an `env.<name>` namespace (`existing_project`, `detected_languages`, …), and contribute `onboarding` steps (folded into `ONBOARDING.md`) and `session_start` hook commands (appended to the SessionStart hooks — for a standalone profile, a minimal settings.json led by the version-check nudge), recorded so a degraded update keeps the hooks. Also the authoring CLI: `profile init` (`--standalone` for `extends: null`) / `list` / `validate` (loads + strict-renders every template) / `save` (extract a profile from a scaffolded project's *delta* from the default — reuses `update`'s regenerate + fingerprint classification, parameterizes name/slug, keeps `seed` status, turns symlinks into onboarding steps, discloses the safety tier). `classify_safety` derives a `safe`/`unsafe` tier from a profile's content (session_start / onboarding / a template writing an execution sink or a not-provably-inert path — allowlist + fail-closed; recorded in the manifest); `apply` **confines** every output path to the target (RFC 2026-07-03-profile-safety). `resolve` also fetches a **`git+https://…` URL** into a cache (transport allowlist, no submodules), and `consent` gates a fetched *unsafe* profile behind a per-artifact **content-hash** trust store (`~/.config/.../trusted.json`) — `profile add`/`untrust`/`trust --list` manage it; a *safe* or local profile passes freely (RFC 2026-07-04). **Discovery**: `profile search`/`list --community` read a curated `contributions/index.json` (a PR-gated list of URLs, cached like `update --check`, env-overridable), and `profile publish` prints a profile's shareable URL + index entry (RFC 2026-07-04-community-index); `add`/`show` also resolve a bare name via the index (git+-URL entries only — a path-shaped entry is refused so it can't masquerade as trusted-local; locals win). A profile may also declare freeform discovery `tags` (surfaced by `show`/`search`, carried into the index by `publish`) and `profile show` inspects any profile — including a `git+URL`, read-only — before adopting it. `cli.build` applies the resolved profile before the manifest; `Scaffolder.overlay` does the child-last write; on update, `update.py` re-resolves the recorded profile and re-applies it (its `version` gates a breaking bump; *new* `session_start` commands **or** a *safe → unsafe* flip gate on any bump — a trust check before new code runs), degrading to frozen if it can't be found. `update --check` re-resolves the profile from its recorded `source` and nudges when a newer `version` exists (no network). |
| `generators/` | One module per concern — `ai_context` (AGENTS.md + per-tool entry points: CLAUDE.md/GEMINI.md symlinks, Cursor/Copilot pointer files, plus an optional self-removing first-run banner), `agents` (`.claude/`), `docs` (docs tree + RFC lifecycle + embedded check scripts), `quality` (pre-commit, Taskfile, gitignore), `ci` (GitHub Actions), `onboarding` (the self-deleting `ONBOARDING.md` first-run runbook, whose last step also removes the banner). Each exposes `generate(config, sc)`; `agents` and `onboarding` also accept a profile's `session_start`/`onboarding` contributions to merge in. |
| `tools/checks/` | Standalone enforcement scripts run as hooks: `sync_rfc_status.py` (any project with docs), `rfc_needed.py` (any language with a dependency manifest — its dep trigger reads pyproject.toml/package.json/go.mod/Cargo.toml), `docs_sync.py` and `tests_needed.py` (Python `src/`+`tests/` layout), and `format_on_edit.py` (the Claude PostToolUse format-on-edit helper); `check_index.py` (repo-only, not embedded) fetches + validates every community-index entry — run weekly / on `contributions/` PRs by the `index-check` workflow. Each ships with a stdlib-`unittest` test, run via `python -m unittest discover -s tools/checks` (wired into the command surface, a pre-push hook, and CI). The wizard embeds the scripts and their tests as constants in `generators/docs.py` (gates) and `generators/agents.py` (format hook). |

Flow: `cli.build()` → `ai_context` → `agents` → `docs` → `quality` → `ci`, each
gated on the matching `include_*` flag, then `onboarding` (when there's tooling to activate,
or a profile contributes steps), then a `--profile`'s file overlay (if any, via
`profiles.apply`), and finally `manifest.write()` to record provenance. A profile's
`session_start`/`onboarding` contributions are passed into `agents`/`onboarding` so they merge
into the base output rather than overwriting it.

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
