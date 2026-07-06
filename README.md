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
| `--profile <name\|path>` | Scaffold from a [profile](#profiles--the-community-loop-experimental) instead of the flagship baseline. |
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

### Profiles — the community loop (experimental)

A **profile** is a packaged, versioned, **complete** project setup — the built-in scaffold is
itself just the vendored flagship profile (`agent-native-baseline`). A team or community ships
their own — their `.claude/` agents, MCP config, house rules, extra gates — so new projects
start from "exactly like ours," not just the generic baseline. The loop is: **discover** a
profile for your use case → **adopt** it → **tune** it → **snapshot or fork** what you built →
**publish** it back — and every release you cut flows to your consumers through `update`.

```bash
# Find & use a community profile
agent-native-setup profile search python         # search the community index (name/description/tags)
agent-native-setup profile list --community       # …or browse the whole index
agent-native-setup profile show git+https://github.com/acme/profile.git   # inspect one before adopting
agent-native-setup my-app --profile git+https://github.com/acme/profile.git    # use one by URL
agent-native-setup profile add acme-profile      # …or install a search hit by its index name

# Make & share your own
agent-native-setup profile init my-team           # scaffold a skeleton
agent-native-setup profile save ./my-app team     # …or snapshot a project you tuned
agent-native-setup profile validate ./my-team     # check it loads + every template renders
agent-native-setup profile publish ./my-team      # print its shareable URL + index entry (then PR it)
```

**Discover, then share.** Profiles are found through a curated, zero-infra
[community index](contributions/index.json) — a PR-gated list of URLs (each profile lives in its own
repo). `profile search` / `list --community` read it; `profile publish` prints the entry to PR. A
team can point `AGENT_NATIVE_SETUP_INDEX_URL` at a private index. A listing is *discovery, not
endorsement* — trust is decided at fetch, not by being listed.

**Trust.** Consume a profile by URL (`--profile git+https://…`, optionally `@v1.2.0` to pin,
`#subdir=team` for a monorepo) or `profile add <url-or-index-name>` to install it (a bare name
that isn't local is looked up in the index — the redirection is printed). The fetch is data-only (an
https/ssh allowlist, no submodules). A **safe** profile (declarative — sandboxed, no hooks/sinks)
applies with no prompt; a fetched **unsafe** (code-carrying) one asks for `--allow-code` and
remembers your consent per exact content (`profile trust --list` / `untrust` to review or revoke). A
local or `~/.config` profile is trusted — the gate is for code fetched from the internet.

`profile save <project> <name>` is the reverse of authoring: point it at a project you
scaffolded and then customized, and it **snapshots the complete setup** as a standalone profile
— every scaffold-recorded file as it exists on disk (your edits included, plus files you added
in setup-owned dirs), with the project name and scaffold date parameterized, `seed` status
preserved, and symlinks captured as `links`. It's read-only on the source and produces a
review-ready draft (run `profile validate` on it). The snapshot is pinned to your project's
languages and choices — for a *general* reusable base, fork the flagship instead (below).

**Extend.** To build on any profile — the flagship baseline or a community one, "that base
plus our house files" — fork it and publish your fork to the index:

```bash
git clone https://github.com/acme/python-backend-profile.git my-profile
cd my-profile && git remote rename origin upstream
# edit templates/, set your own name/version in profile.json, push to your repo, tag, publish
git fetch upstream && git merge upstream/main   # later: take base improvements, then bump + tag
```

Your consumers get each release through the normal `update` flow.

**Safety.** Profile templates are untrusted input, so they render in a **sandbox** (a hostile
template can't reach Python) and every output path is **confined** to the project (no `../`
escape). Each profile is classified **safe** or **unsafe** from its content (`session_start` hooks,
`onboarding` steps, or writing an execution sink like a CI workflow or `Makefile` → unsafe;
`validate` shows the tier), and an `update` that flips a profile safe → unsafe asks before applying.

`profile init` also drops an **`AGENTS.md`** at the profile root (and a `README.md`) — a contract
that lets an assistant help you *build* the profile. Those root files are **meta**: only what's
under `templates/` ever ships, so your notes/scratch/harness live at the root and never leak into
scaffolded projects.

A profile is a directory with a `profile.json` and a `templates/` tree. A full example:

```json
{
  "name": "my-team",
  "version": "1.0.0",
  "description": "Our team's agent setup",
  "tags": ["backend", "python"],
  "seed": ["docs/team-notes.md"],
  "prompts": [
    {"name": "tier",   "type": "select",  "message": "Service tier?",   "choices": ["basic", "enterprise"], "default": "basic"},
    {"name": "use_db", "type": "confirm", "message": "Include the DB?",  "default": false},
    {"name": "engine", "type": "select",  "message": "DB engine?",       "choices": ["postgres", "mysql"], "when": "answers.use_db"}
  ],
  "onboarding": ["Run `task team-setup` to configure the toolchain."],
  "session_start": ["echo 'Remember the team release checklist'"]
}
```

Only `name` and `version` are required; `tags` (freeform discovery keywords — who/what
it targets, surfaced by `search`/`show` and carried into the community index by `publish`), `seed`,
`prompts`, `onboarding`, and `session_start` are optional. `agent-native-setup profile init` writes
this skeleton **plus a README documenting every field** — start there.

In short: a profile ships **everything** — a scaffolded project gets exactly the files under
`templates/` (its own `AGENTS.md` included), nothing else. `.j2` templates render (sandboxed)
against the project context — the profile's own **prompt answers** (`{{ answers.tier }}`; a
`when` asks a question only when relevant, answers are recorded and replayed on `update`, and
`-y` / `--answer name=value` cover headless runs) and an **`env`** namespace of sensed facts
(`{% if env.existing_project %}…`; never an echo of a wizard choice) — while every other file
ships verbatim, so a literal
`${{ ... }}` is safe. `onboarding` steps fold into the project's one-time `ONBOARDING.md`;
`session_start` commands join the `.claude` SessionStart hooks (each wrapped so a failure can't
disrupt a session). The full subsystem reference — resolution precedence, prompt types, the
trust model, integration points — lives in
[`docs/architecture/profiles.md`](docs/architecture/profiles.md).

**Updating to a new profile version.** Bump the profile's `version` when you change its
templates. In projects scaffolded from it, `agent-native-setup update` then refreshes those
files — each is **managed** (refreshed when the user hasn't touched it; reported as a conflict
to reconcile if they have), unless you list it under `seed` (shipped once, never refreshed). A
breaking bump (major, or the minor pre-1.0) pauses for confirmation, just like a base update;
and a bump that introduces **new `session_start` commands** lists them and asks before applying
(even on a non-breaking bump) — new shell shouldn't start running on a machine unannounced.
`agent-native-setup update --check` (also wired into the SessionStart hook) **nudges** when a
newer version exists at the profile's source. For `update` to pull it, the profile must still be
resolvable then — the same path, or a name in `~/.config/agent-native-setup/profiles/` —
otherwise the base still updates and the profile's files are left as-is.

> **Still experimental.** The community loop is complete end-to-end — authoring, composing,
> prompts, updating, the safety/trust model, git-URL distribution, and discovery (the community
> index, kept rot-free by CI) — but the format may still evolve with feedback. The deliberate
> frontier: **code-plugin** profiles (arbitrary generator code — a one-way trust door we haven't
> opened; `ecosystem-core`) and per-profile **migrations** (`scaffolding-profiles`), both under
> [`docs/rfc/proposed/`](docs/rfc/proposed/).

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

## License

[MIT](./LICENSE) — the engine, the flagship [`agent-native-baseline`](https://github.com/luca-mastrostefano/agent-native-baseline) profile, and everything they scaffold into your project are yours to use, fork, and redistribute.
