---
name: extract-profile
description: Extract a complete agent-native-setup profile from an existing repo's agent setup (contracts, .claude/.cursor/.gemini tooling, MCP, docs conventions, git gates) — inventory, classify, parameterize, verify by byte-diff, and ship. Use when someone wants to turn a well-structured repo into a shareable profile.
---


Extract the **agent-native setup surface** of the repo at the source repo path given in the task into a complete, standalone
agent-native-setup profile (working name: as given, default `<repo>-setup`), following the
proven procedure below. The profile must reproduce the source's agent workflow faithfully —
parameterized, verified, and ready to publish. Work in a sibling directory, never inside
the source repo.

## 1. Inventory (fan out, classify everything)

Sweep the source repo for its agent-native surface — not its product code:

- **Contracts**: AGENTS.md / CLAUDE.md / GEMINI.md (symlinks or shim files?), CONTRIBUTING,
  SECURITY, code-of-conduct.
- **Agent tooling**: `.claude/` (agents, commands, skills, settings), `.cursor/`,
  `.gemini/`, `.github/prompts/`, MCP config (`.mcp.json` — and check whether tools the
  contract *references* (e.g. `mcp__x__*` allowlists) are actually **registered**
  anywhere; a permission allowlist is not a registration).
- **Docs conventions**: ADR/RFC systems (index, template, lifecycle rules), architecture
  docs, onboarding/getting-started docs — separate the *conventions and structure*
  (reusable) from the *product content* (not).
- **Gates**: git hooks (and **how they're armed** — husky prepare script? pre-commit
  install? core.hooksPath?), linter/scanner configs, quality-ratchet files, CI workflows
  that enforce the contract (vs product build/release pipelines).
- **Env surface**: `.env.example`, secret *names* in workflows.
- **Distribution vehicles**: some repos *are* the setup, packaged for a marketplace
  (`.claude-plugin/` manifests, root-level `skills/` dirs). The packaging is SKIP; the
  payload ships relocated to project-native paths (`skills/x` → `.claude/skills/x`). Docs
  *about* the setup (README, examples, per-tool install guides) are SKIP too — the
  profile writes its own README.

Classify every file: **VERBATIM** (ships as-is), **PARAMETERIZE** (project name/slug,
instance-bound IDs, org URLs), **SKIP** (product code, fixtures, lockfiles, generated
artifacts, product-specific doc content). Red-flag pass: embedded secrets/tokens, absolute
paths, personal instance IDs (ticket-system section IDs, dashboards), non-English docs, and
**per-machine/local state** (`.claude/settings.local.json`, any `*.local.json`, `.env` /
`.env.local`) — always SKIP and `.gitignore` these; shipping one commits the *adopter's* own
approvals and tokens.

## 2. License gate (before writing anything)

Check the source repo's LICENSE. If the requesting user is the copyright holder, they may
relicense the extracted profile (ask which license; note the relicense in the profile's
LICENSE). Otherwise the profile is a derivative work: it must carry the source's license
and attribution — and if that license is copyleft, say plainly what that means for
adopters' repos before proceeding.

## 3. Author the profile

- `profile.json`: name, version `0.1.0`, honest description naming the source, discovery
  `tags`, `seed` for files the adopter owns after day one (contracts, doc skeletons,
  ratchet floors, `.env.example`), `transient` never (that's the engine's onboarding
  apparatus), `links` for symlink contracts.
- **Prompts for instance-bound values** (the Todoist-section-ID pattern): anything tied to
  the author's accounts becomes a `text` prompt with a placeholder default, gated by a
  `confirm` prompt (`when:`) so the whole feature is opt-in and the files render empty —
  and don't ship — when declined.
- **Write each prompt `message` so an outsider can answer it.** The adopter never saw the
  source repo, and the message is all they get (`choices` render as bare values; there is no
  help field). State what the answer *does* — which files ship, which gate starts blocking,
  what breaks if declined — and what it *costs* (an install, an account, a slower commit).
  **Name and link every external tool** the source takes for granted but an adopter may not
  know (CodeScene, Codacy, Semgrep, Todoist, husky): `"Add CodeScene gates? (code-health
  ratchet, fails CI on regression - https://codescene.com)"`. For an instance-bound value,
  say **where to find it** ("open the section in Todoist; the ID is the last part of the
  URL"), not just its name. A profile whose wizard reads as a list of the author's internal
  jargon is one an adopter answers by mashing enter.
- **Parameterize identity only**: source project name → `{{ project_name }}` in `.j2`
  files. Before renaming any file to `.j2`, grep it for literal `{{`/`{%`/`${{` — GitHub
  workflows and anything Jinja-hazardous ship **verbatim** (never `.j2`).
- **Reset earned state**: quality-ratchet thresholds restart at an attainable floor (the
  source *earned* its numbers; a fresh repo inheriting them would be unbuildable). Dated
  artifacts use `@DATE@`.
- **A fresh scaffold must reach a clean first commit** (the setup, not the app). The source's
  build/test *stack* is product: don't ship a hook or CI step that runs a tool the empty
  scaffold can't. Either (a) ship the manifest that defines it (`package.json` / `Taskfile` /
  `Cargo.toml` — a minimal stub with no-op scripts is fine) so the gate is a safe no-op, or
  (b) make the step conditional on its files existing (`git ls-files '*.rs' | grep -q . &&
  cargo test`, or a language-gated `.j2`) so it self-skips. A `pre-commit` calling `pnpm lint`
  with no `package.json`, or a `pre-push` hard-requiring `cargo` on a non-Rust project, blocks
  the very first commit. `profile validate` now flags these as `⚠` — clear them.
- **Ship a `.gitignore`** (dependencies, build/test output, `.env*.local`, `*.local.json`).
  Without one, the first `git add -A` stages `node_modules/` and any secrets onboarding creates.
- **Genericize structural docs**: keep the source's section structure as seeded skeletons
  with TODOs; never copy product-truth prose into another project's docs. Reset ADR/RFC
  indexes to empty starters (the source's decisions are its history, not the adopter's).
- **Make referenced tooling real**: if the contract references MCP tools, ship the
  `.mcp.json` registration (env-var token expansion, never a secret) and pre-approve it in
  settings. If the contract describes git gates, ship a **self-silencing `session_start`
  guard** that warns every session until the hooks are actually armed (versioned hooks
  can't self-arm — git's security model), and an `onboarding` step with the exact arming
  commands. The guard's armed-check and the arming commands **must agree**: if the guard
  tests `git config core.hooksPath == .husky`, the onboarding must set exactly that (note
  husky v9 points `core.hooksPath` at `.husky/_`, not `.husky` — so a bare `husky install`
  leaves the guard still firing) and `chmod +x` the hook scripts (git silently skips
  non-executable hooks). Every "the repo has X" claim in the shipped contract must be true in
  a fresh scaffold or guarded until made true.
- Meta files at the profile root (never shipped): a README.md that opens the way `profile
  init` writes one — the attribution line (`🌐 *Part of the **agent-native-setup** registry —
  [browse all community profiles](https://lucamastrostefano.com/agent-native-setup/).*`), a
  **Description** of what the profile sets up and for whom
  (matching `description` in `profile.json`), and a **How to use it** block with `profile add
  <name>` followed by `-o ./my-app --profile <name>` (only `profile add` reads the community
  index, and only for a bare name — a scaffold with a bare `--profile <name>` that was never
  `add`ed fails) — that's the repo's landing page on the registry. Below a `---`, the
  maintainer half: what's reusable vs adapted and
  why, an adopter checklist (external services, secrets to map); a
  root **AGENTS.md** that names the repo as an agent-native-setup profile, links back to the
  manager (`https://github.com/luca-mastrostefano/agent-native-setup`), and carries the notes
  useful for building/maintaining *this* profile — including how to re-validate, re-publish, and
  ship an updated version (`profile validate` → bump `version` → tag → `profile publish
  --release`; adopters pull it with `agent-native-setup update`); **CLAUDE.md** and **GEMINI.md** as symlinks
  to that AGENTS.md so every assistant reads the same guide (`profile init` / `profile save`
  write exactly these three — mirror them); LICENSE per step 2. If the source's recommended
  install is user-level (e.g. a plugin available across all projects), state plainly that
  the profile reproduces the per-project experience only.

## 4. Verify (the fidelity proof)

- `agent-native-setup profile validate <profile>` — zero errors, and resolve every advisory
  `⚠` warning (a gate with no manifest, a missing `.gitignore`, a shipped local/secret file).
- **Make the first commit** in the throwaway scaffold with hooks armed. If `git commit` (and a
  `git add -A`) can't succeed cleanly on the empty scaffold, the profile ships a gate whose
  tool/manifest is missing or a `.gitignore` gap — fix it before shipping.
- Scaffold a throwaway project named **exactly like the source repo** and byte-diff it
  against the source: every VERBATIM file must be identical (this catches accidental
  mangling); PARAMETERIZE files must round-trip the name; list the deliberate deltas and
  check each has a reason (fresh ratchet, genericized doc, placeholder ID).
- Scaffold both paths of every `confirm` prompt (feature on/off) and check the off-path
  ships nothing dangling.
- Read the scaffolded ONBOARDING.md end to end: could a fresh agent actually complete it?

## 5. Ship

`git init -b main`, then **commit every file the profile ships before tagging** — the published
tag and release asset are built from git-tracked content, so a file under `templates/` that git
ignores (`.claude/settings.local.json`, `__pycache__/`, `.DS_Store`) never reaches an adopter even
though a local scaffold copies it; if a normally-ignored file must ship, `git add -f` it and check
`git ls-files templates/`. Then confirm `git status --porcelain templates/` is empty (`publish`
hashes the working tree — a stray untracked/ignored file poisons the `content_hash` and fails the
index-check against the clean tag). Tag `v0.1.0`, then hand the user **one copy-pasteable
command** chaining everything that needs their say (repo creation) — not a list of steps:

```bash
cd <profile-dir> && gh repo create <name> --public --source=. --push && git push origin v0.1.0 && agent-native-setup profile publish . --release
```

(`publish --release` attaches the countable release asset.) Once it has run, add the
printed entry to `contributions/index.json` via PR.

Throughout: fidelity first — when unsure whether something is setup or product, ask the
user rather than guessing; the source repo is read-only.
