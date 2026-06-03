# How to use `ai-setup`

`ai-setup` scaffolds an AI-native project setup: a canonical `AGENTS.md` contract
(with per-tool pointers), a docs + RFC structure, Claude Code agents/commands,
language linters with pre-commit hooks, and CI.

It is **safe to run on a directory that already has code** — existing files are
never overwritten (your `README.md`, `pyproject.toml`, configs, etc. are
preserved), and languages are auto-detected.

## Install

From the `ai-project-setup` repo:

```bash
pip install -e .
```

This puts the `ai-setup` command on your PATH (also runnable as `python -m ai_setup`).

## On an existing project

Languages are auto-detected from marker files (`pyproject.toml`, `package.json`,
`go.mod`, `Cargo.toml`, …) and source file extensions.

```bash
# non-interactive — detect languages, scaffold everything, skip existing files
ai-setup -o /path/to/existing-project --yes

# interactive — detected languages come pre-checked; confirm or adjust
ai-setup -o /path/to/existing-project

# from inside the project (-o defaults to the current directory)
cd /path/to/existing-project && ai-setup --yes

# pin languages explicitly (skips detection)
ai-setup -o /path/to/existing-project --languages python,node --yes
```

## On a new project

There's nothing to detect yet, so choose languages interactively or pass them.

```bash
# interactive (prompts for name, languages, tools, and which parts to scaffold)
ai-setup -o ./my-new-project

# non-interactive
ai-setup my-app -o ./my-app --languages python,node --tools claude --yes
```

## After scaffolding

```bash
cd <project>
task install    # activate pre-commit + pre-push git hooks (once)
task quality    # run the full local gate: lint + typecheck + test
```

Then read `AGENTS.md` — it's the single source of truth for both human and AI
contributors.

## Flags

| Flag | Effect |
| --- | --- |
| `--languages python,node,go,rust` | Set languages explicitly (skips auto-detection). |
| `--tools claude,cursor,copilot` | Which AI assistants to wire up (default: all three). |
| `--description "..."` | One-line project description used in `AGENTS.md`/`README.md`. |
| `--no-agents` / `--no-docs` / `--no-quality` / `--no-ci` | Skip a part of the scaffold. |
| `--no-github-actions` | Quality tooling without the CI workflow. |
| `--no-hooks` / `--no-git` | Skip pre-commit hooks / `git init`. |
| `-y, --yes` | Non-interactive; use flags and defaults. |
| `--force` | Overwrite existing files (`README.md` is still preserved). |

## Notes

- **Auto-detection** keys off root marker files plus file extensions anywhere in
  the tree, so a monorepo with a nested `package.json` is still caught via its
  `.ts`/`.js` files. Use `--languages` to pin the set explicitly.
- **CLAUDE.md** is created as a symlink to `AGENTS.md` so the contract never
  forks; Cursor and Copilot get thin pointer files back to it.
