<div align="center">

# 🪄 agent-native-setup

**One command to make any repo agent-native — new or existing.**

Coding agents (Claude Code, Cursor, Copilot, Gemini, …) are only as effective as the repo they
work in. This wizard lays down the setup that makes a codebase legible and safe for
agents *and* humans: a single contract every agent follows, mechanical guardrails that
catch mistakes automatically, and feedback loops — review subagents, tests, an RFC
trail — so quality compounds instead of drifting. Enforced by tooling, not memory.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)

</div>

---

## Quick start

```bash
# Run it once, no install (uv):
uvx --from git+https://github.com/luca-mastrostefano/agent-native-setup agent-native-setup -o ./my-app

# …or install the `agent-native-setup` command (pick one):
pipx install git+https://github.com/luca-mastrostefano/agent-native-setup
uv tool install git+https://github.com/luca-mastrostefano/agent-native-setup
```

Then run `agent-native-setup` and answer the prompts — or go non-interactive (below).

> Installs straight from GitHub — no clone, no manual dependency setup. Needs the
> repo to be public (or collaborator access) and Python 3.10+.

## What you get

Pointed at a target repo, the wizard generates:

- **The `AGENTS.md` + `INSTRUCTION.md` contract** — `INSTRUCTION.md` carries the four
  execution principles and when-to-write-an-RFC rules (managed, so an `update` keeps it
  fresh); `AGENTS.md` is the thin project map (navigation + live command surface) that
  points at it. `CLAUDE.md` and `GEMINI.md` (symlinks), `.cursor/rules/`, and
  `.github/copilot-instructions.md` all point back to `AGENTS.md`, so the rules never fork across tools.
- **A `.claude/` agent library** — focused subagents (`code-reviewer`, `rfc-reviewer`,
  `planner`), slash commands (`/review`, `/rfc`, `/update-agent-scaffolding`, `/onboard`), a permission allowlist for the
  contract's own commands, and hooks that inject the live command surface at session start
  and auto-format files as they're edited.
- **`docs/` + an RFC lifecycle** — a pre-seeded architecture map (reflecting the active
  RFCs), the `proposed → active → (superseded | retired)` RFC flow (with a template), a root
  `CONTRIBUTING.md` dev-loop guide, and an improvements backlog — kept in folder-sync and
  freshness by hooks.
- **`tools/checks/`** — small enforcement scripts (RFC ↔ folder sync, "new component
  needs a doc," "structural change needs an RFC") that ship with their own tests.
- **Per-language lint, format & types** — ruff (Python), ESLint + Prettier + tsc (JS/TS),
  golangci-lint + gofmt (Go), clippy + rustfmt (Rust), htmlhint + lychee (HTML), with
  their config files.
- **A three-layer quality gate** — the same checks wired at **pre-commit**, a
  self-documenting **`make`/`task`** command surface, and **CI**, so local-green means
  CI-green.
- **A security baseline** — committed-secret scanning (gitleaks) and dependency/vuln
  audits, in both pre-commit and a dedicated CI job, plus `SECURITY.md` and Dependabot.
- **Engineering baseline files** — `.editorconfig`, `.gitattributes`, per-language
  `.gitignore`, a PR template, a provenance manifest (`.agent-native-setup.json`, recording
  what generated the project for a future `update`), and (on existing repos) a
  `.git-blame-ignore-revs`.
- **A self-deleting `ONBOARDING.md`** — a one-time runbook that walks an agent through
  activating the setup on first run, then removes itself.

It's **non-destructive**: existing files are never overwritten, and on a repo that
already has code it **grandfathers the legacy code** — the gate checks only what a
pull request changes, so day one isn't a wall of red.

## Guardrails for your agent

These aren't just config files — they actively keep an agent (and you) on the rails:

- **A real testing bar.** Every change ships the test that *proves* it, at the right
  level — **unit** (logic + edge cases), **integration** (module / public-contract /
  boundary crossings), and **regression** (a failing test written *first* for every bug).
  Tests must prove behavior, not restate the code: cover the boundaries (empty/zero/one/max),
  bad input, and error paths — not just the happy path.
- **A self-review pass before "done".** A `code-reviewer` subagent (`/review`) reads the
  diff and flags real bugs, over-engineering, drive-by changes, stale docs, weak or
  happy-path-only tests, and changes that hurt cohesion or sneak in coupling (scoped to the
  change — it never nags about legacy file size) — caught before they land, not after.
- **Security in two layers.** `gitleaks` (committed secrets) and dependency/vulnerability
  audits run mechanically in pre-commit and CI; for changes touching auth, untrusted input,
  secrets, or network I/O, the contract routes the agent to a `/security-review` for the
  logic-level flaws scanners can't see.
- **Docs, tests, and decisions can't silently drift.** `commit-msg` hooks require an RFC
  for a structural change, an architecture-doc update for a new component, and a test
  alongside a source change — each waivable with a logged trailer; RFCs auto-file into
  their lifecycle folder.
- **Every rule, enforced three ways.** The same checks run at **pre-commit**, on the
  **command surface**, and in **CI** — so a violation can't slip past whichever layer the
  agent skips.
- **…and the small operational foot-guns.** Followable background processes (no silent
  buffering), re-staging after `git add`, verifying CI after a workflow change — the
  reminders that turn a frustrating session into a smooth one.

## Usage

**Interactive** — prompts for everything:

```bash
agent-native-setup -o ./my-new-project
```

**Non-interactive** — scriptable / CI:

```bash
agent-native-setup my-app -o ./my-app --languages python,node \
  --tools claude,cursor,copilot,gemini --yes
```

**Existing project** — point `-o` at code that already exists. Languages are
auto-detected (from marker files like `pyproject.toml` / `package.json` / `go.mod` /
`Cargo.toml` and from source extensions), existing files are preserved, and the CI
gate switches to changed-files-only so your legacy code isn't flagged on day one:

```bash
agent-native-setup -o ./existing-app --yes
```

### Flags

| Flag | Effect |
| --- | --- |
| `-o, --output` | Target directory (default: current dir). |
| `--description "..."` | One-line project description (used in `AGENTS.md`/`README.md`). |
| `--profile <name\|path>` | Compose a [profile](#profiles-experimental) on top of the default setup. |
| `--languages` | Comma-separated: `python,node,go,rust,html`. Linters only for these. |
| `--tools` | Comma-separated: `claude,cursor,copilot,gemini` (default: all). |
| `--runner make\|task` | Command-surface runner for a fresh repo (default: `make`; an existing one is auto-detected). |
| `--adopt progressive\|full\|none` | How the gate applies to an **existing** repo's code (default: `progressive`). |
| `--no-agents` · `--no-docs` · `--no-quality` · `--no-ci` | Skip that part. |
| `--no-security` | Skip secrets + dependency scanning (keep the rest). |
| `--no-github-actions` | Quality tooling without the CI workflow. |
| `--no-hooks` · `--no-git` | Skip pre-commit hooks / `git init`. |
| `--no-first-run-banner` | Don't inject the self-removing "first run — finish ONBOARDING" banner into `AGENTS.md`. |
| `--no-update-check` | Don't check GitHub for a newer release at the end of a run. |
| `-y, --yes` | Non-interactive; use flags and defaults. |
| `--dry-run` | Preview what would be created (and what would be skipped as already-present) — writes nothing. |
| `--force` | Overwrite existing files. |

### Keeping a project up to date

The wizard records what it generated in `.agent-native-setup.json`, so a scaffolded project
isn't frozen at the version that made it:

```bash
agent-native-setup update            # refresh managed files to the installed version
agent-native-setup update --dry-run  # preview the changes — and check for local drift
agent-native-setup update --check    # one-line "newer version available?" nudge
```

`update` **classifies** rather than merges: it refreshes generated files that are still
pristine, never touches files you own or have edited (it reports those as conflicts to
reconcile), and removes guardrails it no longer generates. It needs a clean git working tree
(or `--dry-run`) so the change is a reviewable diff; a breaking version bump pauses for
confirmation and writes an `UPDATING.md` runbook. On an already-current project,
`update --dry-run` doubles as a **conformance check** — it flags any managed file that has
drifted from the scaffold.

### Profiles (experimental)

A **profile** lets a team or community ship their *own* agent setup composed on top of the
default one — their `.claude/` agents, MCP config, house rules, extra gates — so new projects
start from "exactly like ours," not just the generic baseline.

```bash
agent-native-setup profile init my-team          # scaffold a profile skeleton
# …add files under my-team/templates/, then:
agent-native-setup my-app -o ./my-app --profile ./my-team
agent-native-setup profile list                  # profiles in ~/.config/agent-native-setup/profiles
```

A profile is a directory with a `profile.json` (`name`, `version`, `extends: default`,
`description`) and a `templates/` tree. Every file under `templates/` is laid down at the
matching path in the new project, **on top of** the default scaffold. Files ending in `.j2`
are rendered (Jinja, with `project_name` / `slug` / `description` / `languages`) and the `.j2`
stripped; everything else ships verbatim, so files containing `${{ ... }}` (GitHub Actions)
are safe. `--profile` takes a path, or a bare name resolved under
`~/.config/agent-native-setup/profiles/`.

> **Phase 1 scope.** Profile files are shipped as **seed** — written once, then yours to
> maintain; the default base underneath stays managed and `update`-able. A profile's *own*
> versioned update stream, `extends`-from-blank, and `profile save` (derive a profile from an
> existing project) are planned — see
> [`docs/rfc/proposed/2026-06-23-scaffolding-profiles.md`](docs/rfc/proposed/2026-06-23-scaffolding-profiles.md).

## Philosophy

Three pillars, lifted from real production setups:

1. **Context** — one canonical contract (`AGENTS.md` → `INSTRUCTION.md`, plus `docs/` and
   RFCs) so intent is discoverable and never forks across tools.
2. **Mechanical enforcement** — linters, hooks, and CI catch violations
   automatically; error messages tell you how to fix them.
3. **Feedback loops** — subagents, tests, and reviews compound quality.

Every generated project ships the **four execution principles**: think before
coding, simplicity first, surgical changes, goal-driven execution.

## Develop

```bash
git clone https://github.com/luca-mastrostefano/agent-native-setup
cd agent-native-setup
pip install -e .
task install   # set up pre-commit hooks (once)
task quality   # lint + typecheck + tests
```

## Extending

Add a language by appending one `Language` entry to `src/agent_native_setup/languages.py` —
the generators stay generic.
