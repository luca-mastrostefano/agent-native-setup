<div align="center">

# 🪄 ai-project-setup

**One command to scaffold an AI-native setup into any repo — new or existing.**

A canonical agent contract, an agents & commands library, a docs + RFC structure,
language linters with pre-commit hooks, secrets + dependency scanning, and CI —
wired so AI and human contributors share one set of rules and quality is enforced
mechanically, not from memory.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)

</div>

---

## Quick start

```bash
# Run it once, no install (uv):
uvx --from git+https://github.com/luca-mastrostefano/ai-project-setup ai-setup -o ./my-app

# …or install the `ai-setup` command (pick one):
pipx install git+https://github.com/luca-mastrostefano/ai-project-setup
uv tool install git+https://github.com/luca-mastrostefano/ai-project-setup
```

Then run `ai-setup` and answer the prompts — or go non-interactive (below).

> Installs straight from GitHub — no clone, no manual dependency setup. Needs the
> repo to be public (or collaborator access) and Python 3.10+.

## What you get

Pointed at a target repo, the wizard generates:

- **`AGENTS.md`** — the single source of truth; `CLAUDE.md`, Cursor, and Copilot all
  point back to it so the contract never forks.
- **`.claude/`** — a small, opinionated set of subagents and slash commands.
- **`docs/` + RFCs** — an architecture doc and an RFC lifecycle
  (`current → done → superseded`), kept in sync by hooks.
- **Linters + pre-commit hooks** — per language, plus secrets scanning (gitleaks) and
  self-explaining enforcement hooks.
- **CI** — a GitHub Actions quality gate (lint + tests) and a security job
  (dependency + secret scanning).

It's **non-destructive**: existing files are never overwritten, and on a repo that
already has code it **grandfathers the legacy code** — the gate checks only what a
pull request changes, so day one isn't a wall of red.

## Usage

**Interactive** — prompts for everything:

```bash
ai-setup -o ./my-new-project
```

**Non-interactive** — scriptable / CI:

```bash
ai-setup my-app -o ./my-app --languages python,node \
  --tools claude,cursor,copilot --yes
```

**Existing project** — point `-o` at code that already exists. Languages are
auto-detected (from marker files like `pyproject.toml` / `package.json` / `go.mod` /
`Cargo.toml` and from source extensions), existing files are preserved, and the CI
gate switches to changed-files-only so your legacy code isn't flagged on day one:

```bash
ai-setup -o ./existing-app --yes
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
git clone https://github.com/luca-mastrostefano/ai-project-setup
cd ai-project-setup
pip install -e .
task install   # set up pre-commit hooks (once)
task quality   # lint + typecheck + tests
```

## Extending

Add a language by appending one `Language` entry to `src/ai_setup/languages.py` —
the generators stay generic.
