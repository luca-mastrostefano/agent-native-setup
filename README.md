# ai-project-setup

A wizard that scaffolds an **AI-native project setup** into a brand-new repo:
a canonical agent contract, per-tool entry points, an agents/commands library,
a docs + RFC structure, language linters with pre-commit hooks, and CI.

## Philosophy

Three pillars, lifted from real production setups:

1. **Context** — one canonical `AGENTS.md`; `CLAUDE.md`, Cursor, and Copilot
   all point back to it so the contract never forks. Plus `docs/` and RFCs.
2. **Mechanical enforcement** — linters, hooks, and CI catch violations
   automatically; error messages tell you how to fix them.
3. **Feedback loops** — subagents, tests, and reviews compound quality.

Every generated project ships the **four execution principles**: think before
coding, simplicity first, surgical changes, goal-driven execution.

## Install

```bash
pip install -e .
```

## Usage

Interactive:

```bash
ai-setup --output ./my-new-project
```

Non-interactive (scriptable / CI):

```bash
ai-setup my-app -o ./my-app --languages python,node \
  --tools claude,cursor,copilot --yes
```

### Existing projects

Point `-o` at a project that already has code. Languages are **auto-detected**
(from marker files like `pyproject.toml` / `package.json` / `go.mod` /
`Cargo.toml` and from source extensions) and existing files are never overwritten
— your `README.md`, configs, etc. are preserved. Override detection with
`--languages` any time.

```bash
ai-setup -o ./existing-app --yes
```

### Key flags

| Flag | Effect |
| --- | --- |
| `--languages` | Comma-separated: `python,node,go,rust`. Linters only for these. |
| `--tools` | Comma-separated: `claude,cursor,copilot` (default: all). |
| `--no-agents` / `--no-docs` / `--no-quality` / `--no-ci` | Skip a part. |
| `--no-github-actions` | Quality tooling without CI workflows. |
| `--no-hooks` / `--no-git` | Skip pre-commit hooks / `git init`. |
| `-y, --yes` | Non-interactive; use flags and defaults. |
| `--force` | Overwrite existing files. |

## Extending

Add a language by appending one `Language` entry to
`src/ai_setup/languages.py` — generators stay generic.
