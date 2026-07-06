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

## What you get

Pointed at a target repo, the wizard scaffolds the flagship
[`agent-native-baseline`](https://github.com/luca-mastrostefano/agent-native-baseline)
profile (or any [profile](#profiles--the-community-loop-experimental) you pick):

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
plus our house files" — fork it with git; there is deliberately no in-tool extension mechanism
([why](docs/rfc/active/2026-07-04-profile-extends.md): git's three-way merge beats any overlay
we could ship, and you review base changes before releasing them to your own consumers):

```bash
git clone https://github.com/acme/python-backend-profile.git my-profile
cd my-profile && git remote rename origin upstream
# edit templates/, set your own name/version in profile.json, push to your repo, tag, publish
git fetch upstream && git merge upstream/main   # later: take base improvements, then bump + tag
```

Your consumers get each release through the normal `update` flow; `git diff upstream/main` stays
the view of exactly what you changed on the base.

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

## License

[MIT](./LICENSE) — the engine, the flagship [`agent-native-baseline`](https://github.com/luca-mastrostefano/agent-native-baseline) profile, and everything they scaffold into your project are yours to use, fork, and redistribute.
