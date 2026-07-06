<div align="center">

# 🪄 agent-native-setup

**One command to make any repo agent-native — new or existing — and keep it that way.**

Your agent setup — contract, prompts, subagents, guardrails — installs like a package and
**updates like one**: as the profile you adopted improves, `update` brings the best current
version into your repo, without touching what you've customized.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

</div>

---

## Why

Coding agents (Claude Code, Cursor, Copilot, Gemini, …) are only as effective as the repo
they work in. A repo becomes **agent-native** when it carries three things: a single
contract every agent follows, mechanical guardrails that catch mistakes automatically, and
feedback loops — review subagents, tests, an RFC trail — so quality compounds instead of
drifting. Enforced by tooling, not memory.

**The hard part is that there is no one right setup.** A Python backend, a TypeScript
monorepo, a design-heavy frontend, a legacy service being adopted progressively — each
needs a different contract, different gates, different agents. Today every team
re-discovers theirs from scratch: weeks of tuning hooks, prompts, and CI, none of it
shared, all of it drifting the moment it lands, every lesson re-learned one repo over.

This project turns that private, perishable effort into a **community asset**:

- A setup is a **profile** — a versioned, inspectable, forkable package. The built-in
  scaffold is itself just the flagship profile,
  [`agent-native-baseline`](https://github.com/luca-mastrostefano/agent-native-baseline);
  it has no special powers your profile can't have.
- You **adopt** one in a command, **tune** it to your stack, **snapshot** what you built
  (`profile save`), and **share** it through the community index — so the next team with
  your use case starts where you finished, not from zero.
- **Improvements compound instead of scattering — and your setup never goes stale.**
  Fork a profile and `git merge` takes upstream fixes; `agent-native-setup update` flows
  each profile release into every project scaffolded from it (refreshing pristine files,
  never clobbering your edits). One good idea — a better reviewer prompt, a sharper gate —
  propagates to every downstream repo instead of dying in the one repo that had it, and
  every repo keeps running the best current version of its setup rather than a snapshot
  of the day it was scaffolded.

The goal: the community **converges** on great agentic scaffolding per use case — searched,
adopted, extended — the way package registries let code converge, with the trust model
(sandboxing, content-hash consent, safety classification) that sharing executable setup
demands.

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

## The default: `agent-native-baseline`

This repo is the **manager** — resolve, prompt, trust-gate, apply, update, discover. The
*content* comes from whichever profile you scaffold, and with no `--profile` that's the
flagship, [`agent-native-baseline`](https://github.com/luca-mastrostefano/agent-native-baseline)
(vendored in the wheel, hash-pinned to a tagged release of its repo). In one run it lays
down a complete agent-native setup: the `AGENTS.md` contract every tool follows (Claude,
Cursor, Copilot, Gemini — never forking), a `.claude/` library of review subagents and
slash commands, docs + an RFC lifecycle, per-language linters wired identically at
pre-commit / command surface / CI, a security baseline, and a self-deleting onboarding
runbook. Non-destructive: existing files are never overwritten, and legacy code is
grandfathered so day one isn't a wall of red.

**The full tour — every file it ships and every guardrail it enforces — lives in [its own
README](https://github.com/luca-mastrostefano/agent-native-baseline#readme).** It's an
ordinary profile with no special powers: fork it to make it yours, or start from a
different one entirely (`profile search`).

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
| `--profile <name\|path>` | Scaffold from a [profile](#profiles--the-community-loop) instead of the flagship baseline. |
| `--answer NAME=VALUE` | Answer a profile prompt headlessly (repeatable) — for agents/CI; others take defaults with `-y`. |
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

A scaffolded setup is a **living dependency, not a one-time template**: the wizard records
what it generated in `.agent-native-setup.json`, so your prompts, agents, and gates track
the best current version of the profile you adopted instead of freezing at the version
that made them:

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

### Profiles — the community loop

A **profile** is a packaged, versioned, **complete** project setup — the built-in scaffold is
itself just the flagship profile. A team or community ships their own (`.claude/` agents, MCP
config, house rules, extra gates), so new projects start from "exactly like ours," not just
the generic baseline. The loop: **discover → adopt → tune → snapshot or fork → publish** —
and every release you cut flows to your consumers through `update`.

```bash
# Find & use
agent-native-setup profile search python           # search the community index (name/description/tags)
agent-native-setup profile show acme-profile       # inspect before adopting: files, prompts, safety
agent-native-setup my-app --profile acme-profile   # scaffold from it (also: a path or git+https://… URL)

# Make & share your own
agent-native-setup profile init my-team            # scaffold a skeleton…
agent-native-setup profile save ./my-app my-team   # …or snapshot a project you've tuned
agent-native-setup profile validate ./my-team      # check it loads + every template renders
agent-native-setup profile publish ./my-team       # print its shareable URL + index entry (then PR it)
```

- **Discover** — profiles are found through the curated
  [community index](contributions/index.json): a PR-gated list of URLs, kept rot-free by CI
  (`AGENT_NATIVE_SETUP_INDEX_URL` points a team at a private one). A listing is discovery,
  not endorsement — trust is decided at fetch.
- **Trust** — fetches are data-only (an https/ssh allowlist), templates render in a sandbox
  with outputs confined to the project, and each profile is classified **safe**/**unsafe**
  from its content. A fetched code-carrying profile asks for consent once per exact content
  (`--allow-code`; review or revoke with `profile trust --list` / `untrust`).
- **Extend** — fork the profile's repo (the flagship included), add your templates, and
  publish your fork to the index; `git fetch upstream && git merge` takes base improvements
  later.
- **Update** — bump your profile's `version`, and your consumers' `agent-native-setup update`
  refreshes its files: pristine ones only (edits are reported as conflicts, `seed` files are
  never touched), with a pause for confirmation on a breaking bump or new session hooks.

The format (`profile.json` + `templates/` with prompts, sensed `env` facts, `seed` /
`transient` / `links`) and the full trust model live in
[`docs/architecture/profiles.md`](docs/architecture/profiles.md) — and `profile init` writes
a skeleton whose README documents every field.

## Contributing

```bash
git clone https://github.com/luca-mastrostefano/agent-native-setup
cd agent-native-setup
pip install -e .
task install   # set up pre-commit hooks (once)
task quality   # lint + typecheck + tests
```

Then see [`CONTRIBUTING.md`](./CONTRIBUTING.md) — the dev loop, the definition of done, and
how to contribute a profile.

## License

[MIT](./LICENSE) — the engine, the flagship [`agent-native-baseline`](https://github.com/luca-mastrostefano/agent-native-baseline) profile, and everything they scaffold into your project are yours to use, fork, and redistribute.
