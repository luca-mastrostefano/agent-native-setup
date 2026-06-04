<div align="center">

# 🪄 agent-native-setup

**One command to make any repo agent-native — new or existing.**

Coding agents (Claude Code, Cursor, Copilot, …) are only as effective as the repo they
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

- **The `AGENTS.md` contract** — one source of truth carrying the four execution
  principles, a live command surface, a navigation map, and when-to-write-an-RFC rules.
  `CLAUDE.md` (a symlink), `.cursor/rules/`, and `.github/copilot-instructions.md` all
  point back to it, so the rules never fork across tools.
- **A `.claude/` agent library** — focused subagents (`code-reviewer`, `planner`), slash
  commands (`/review`, `/rfc`, `/onboard`), and a `SessionStart` hook that injects the
  live command surface into every session.
- **`docs/` + an RFC lifecycle** — a pre-seeded architecture map, the
  `current → done → superseded` RFC flow (with a template), a contributing guide, and an
  improvements backlog — kept in folder-sync and freshness by hooks.
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
  `.gitignore`, a PR template, and (on existing repos) a `.git-blame-ignore-revs`.
- **A self-deleting `ONBOARDING.md`** — a one-time runbook that walks an agent through
  activating the setup on first run, then removes itself.

It's **non-destructive**: existing files are never overwritten, and on a repo that
already has code it **grandfathers the legacy code** — the gate checks only what a
pull request changes, so day one isn't a wall of red.

## Usage

**Interactive** — prompts for everything:

```bash
agent-native-setup -o ./my-new-project
```

**Non-interactive** — scriptable / CI:

```bash
agent-native-setup my-app -o ./my-app --languages python,node \
  --tools claude,cursor,copilot --yes
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
| `--languages` | Comma-separated: `python,node,go,rust,html`. Linters only for these. |
| `--tools` | Comma-separated: `claude,cursor,copilot` (default: all). |
| `--no-agents` · `--no-docs` · `--no-quality` · `--no-ci` | Skip that part. |
| `--no-security` | Skip secrets + dependency scanning (keep the rest). |
| `--no-github-actions` | Quality tooling without CI workflows. |
| `--no-hooks` · `--no-git` | Skip pre-commit hooks / `git init`. |
| `-y, --yes` | Non-interactive; use flags and defaults. |
| `--force` | Overwrite existing files. |

## Philosophy

Three pillars, lifted from real production setups:

1. **Context** — one canonical `AGENTS.md` (plus `docs/` and RFCs) so intent is
   discoverable and never forks across tools.
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
