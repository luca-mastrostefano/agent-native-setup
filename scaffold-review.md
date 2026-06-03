# Scaffold review — onboarding retrospective

**Date:** 2026-06-03
**Author:** onboarding agent (Claude Code), reviewing a scaffold produced by another AI agent.

This is a one-time report written while running `ONBOARDING.md`. It records what
the first-run setup actually did, where the scaffold fell short, and the
ambiguities that needed a judgement call. It is feedback on the _scaffolding
agent's output_, not on the project itself.

---

## 1. What I did

Per `ONBOARDING.md`, in order:

1. **Read the contract** (`AGENTS.md`).
2. **Installed git hooks** — `make install` (pre-commit + pre-push).
3. **Established a clean `make quality` baseline.** This did not pass as
   shipped; the fixes are in section 2.
4. **Wrote `docs/architecture/overview.md`** — replaced the stub with a real map
   of what exists today (contract/docs, the local quality gate, CI, the `tools/`
   RFC-sync script) and honest "no app code yet" dependency rules.
5. **Wired up Python**, the one uncovered language (`tools/checks/sync_rfc_status.py`):
   a `ruff-check` + `ruff-format` pre-commit hook, a `setup-python` + ruff step in
   `quality.yml`, and `ruff` entries in the Makefile `lint`/`format` targets.
6. **Removed the `ai-setup:first-run` banner** from `AGENTS.md`.

To make the baseline green I added/changed:

- **`package.json` + `package-lock.json`** — pinned the JS/TS toolchain the
  scaffold already referenced (eslint 9, typescript-eslint 8, prettier 3,
  typescript 5). `npm audit`: 0 vulnerabilities.
- **`tsconfig.json`** (strict, `noEmit`) and a **guard on the `typecheck`
  target** so `tsc` is skipped until the first `.ts`/`.tsx` lands.
- **`.prettierignore`** for `package-lock.json`.
- Ran the formatters the scaffold ships but had not applied (`prettier --write`
  on 3 files, `ruff format` on 1).

Still outstanding (blocked on a human — see section 4): the first commit, adding
a git remote, pushing, confirming CI, the `ANTHROPIC_API_KEY` secret, and
deleting `ONBOARDING.md`.

---

## 2. What the scaffolding agent could have done better

Ordered by impact.

### 🔴 Blocker — the JS/TS toolchain had no `package.json`

`eslint.config.mjs` imports `typescript-eslint`; the Makefile and CI call
`npx eslint`, `npx tsc`, `npx prettier`; `quality.yml` runs `npm ci || npm install`;
`dependabot.yml` declares an **npm** ecosystem. Yet no `package.json` or lockfile
was shipped. The result: `make quality` and CI both fail immediately with
`ERR_MODULE_NOT_FOUND: typescript-eslint`. The "establish a clean baseline" step
**cannot pass as delivered**.

> Fix: ship `package.json` with pinned `devDependencies` and a committed
> `package-lock.json`. A scaffold that wires `npm ci` into CI must include the
> lockfile it expects.

### 🔴 Blocker — `typecheck` can never pass on an empty repo

`typecheck: npx tsc --noEmit` with no `tsconfig.json` and zero `.ts` files just
prints `tsc` help and exits 1; any `tsconfig` errors `TS18003`/`TS18002` with
zero inputs. Because `quality` depends on `typecheck`, the whole gate fails.

> Fix: ship a `tsconfig.json` **and** guard the target for the
> no-TypeScript-yet state (or don't fold `typecheck` into `quality` until TS
> exists). I chose the guard.

### 🟠 The local gate and CI enforce different things

- CI (`quality.yml`) runs `prettier --check` and `lychee`, but **not** `tsc`.
- Local `make quality` runs `tsc` (via `typecheck`) but **not** `prettier --check`
  or `lychee`.

So `make quality` can be green while CI is red (formatting/links), and `tsc` is
enforced locally but never in CI. A contributor's local gate should be a
superset of CI, or identical to it.

> Fix: make `make quality` run the same checks as CI (add `format`/prettier and a
> link check), and run `typecheck` in CI too.

### 🟠 `lychee` pre-commit hook needs a binary nobody is told to install

The hook is `language: system` (`entry: lychee`) — it requires a locally
installed `lychee`, which it will **not** download. But `README.md` lists only
`pre-commit` as a requirement and `ONBOARDING.md` never mentions lychee. A fresh
clone therefore **cannot `git commit`** until the dev discovers they need
`brew install lychee` (or equivalent). CI is fine because it uses
`lycheeverse/lychee-action`.

> Fix: either use the `lychee-docker` hook (no local binary), or document the
> `lychee` install in `README.md`/`ONBOARDING.md` alongside `pre-commit`.

### 🟠 Python shipped unguarded — violating the scaffold's own contract

`AGENTS.md` says: _"If a language in the repo isn't yet wired up for linting,
formatting, and tests, add it."_ The scaffold shipped `tools/checks/sync_rfc_status.py`
with **no** linter, formatter, or CI — and the file wasn't even `ruff format`
clean. The scaffolding agent both wrote code that breaks its own contract and
left the wiring as homework (onboarding step 5).

> Fix: the agent that adds a language should wire its tooling in the same pass.

### 🟡 Shipped files failed the scaffold's own formatters

`prettier --check` flagged `AGENTS.md`, `eslint.config.mjs`, and
`.claude/agents/code-reviewer.md`; `ruff format --check` flagged the Python tool.
The scaffold would reject itself at commit time.

> Fix: run your own formatters before declaring the scaffold done.

### 🟡 `htmlhint` is unpinned and untracked

`htmlhint` is invoked via `npx --yes` (Makefile + CI) rather than as a
`devDependency`, so its version floats and `dependabot` can't track it —
inconsistent with eslint/prettier/typescript.

> Fix: add `htmlhint` to `devDependencies` and drop `--yes`.

### 🟡 `make format` checks but doesn't format

The target named `format` ("auto-format") runs `prettier --check` (and now
`ruff format --check`) — it never writes. The name implies it fixes; it only
reports. (I matched the existing convention for ruff to stay consistent, but the
naming is misleading.)

> Fix: make `format` write (`--write` / `ruff format`) and add a separate
> `format-check` for CI, or rename the target.

---

## 3. Ambiguities I had to resolve

- **Is the JS/TS tooling premature?** There is no JS/TS source yet, only config.
  I treated the Node toolchain as intended (config + CI + dependabot all assume
  it) and materialized the manifest rather than deleting the tooling.
- **Version pinning.** `npx` had pulled eslint 10, but `typescript-eslint@8`
  supports only eslint `^8.57 || ^9`. I pinned **eslint 9** to keep a known-good
  pair rather than chase eslint 10.
- **"Clean baseline" vs. a `tsc` that can't pass with zero files.** Resolved by
  guarding the target instead of adding a placeholder `.ts` (which would be
  speculative code).
- **"lint, format, and tests" vs. "Simplicity First."** The contract says wire
  up _tests_ for each language, but adding a pytest suite + CI job for a single
  internal tool script is over-engineering. I wired lint+format and deferred
  Python tests until there's real Python to test.
- **Where will app code live?** Nothing specifies a layout; I assumed `src/` for
  the `tsconfig` include and the architecture doc, and said so.
- **May the agent commit/push?** `ONBOARDING.md` says to, but pushing is
  outward-facing and the `/onboard` brief says to confirm human decisions. I
  stopped before committing to get explicit sign-off.

---

## 4. Environment blockers (not the scaffold's fault, but worth noting)

- No git remote and no initial commit, so steps 6–7 (push, confirm CI) can't run.
- `gh` auth is invalid (`The token in keyring is invalid`), so even
  `gh repo create` would fail until re-auth.
- `ONBOARDING.md` steps 6–8 implicitly assume a working GitHub connection; a
  "prerequisites: authenticated `gh`, a remote" note would set expectations.

---

## 5. Suggested follow-ups

- Promote the actionable items above into `docs/improvements.md` or an RFC.
- Add Python unit tests for `sync_rfc_status.py` (`parse_status`,
  `target_folder`, `find_moves`) once a Python test runner is justified.
- Align the local gate with CI so "green locally" means "green in CI".
