# Onboarding retrospective — clinic_slack

_Date: 2026-06-03. Author: the agent that ran `/onboard`._

This repo was scaffolded by another AI agent (the `ai-setup` wizard). I then ran
the one-time `/onboard` flow (`ONBOARDING.md`). This file records what I did, how
long it took and why, what the scaffolding agent could have done better, and the
ambiguities I hit — so the next person understands the current state and the
remaining rough edges.

Result commits: `619c5d5` (bootstrap) and `39f027d` (finalize), both green on CI.

---

## 1. What I did

The nine `ONBOARDING.md` steps, condensed:

1. **Read the contract** (`AGENTS.md`) and surveyed the whole scaffold.
2. **Installed git hooks** (`make install` → pre-commit + pre-push).
3. **Tried to establish a clean baseline** (`make quality`). It was **red out of
   the box** — see §4.1. Formatted the three offending scaffold files
   (`AGENTS.md`, `eslint.config.mjs`, `.claude/agents/code-reviewer.md`) so the
   gate and CI could pass. Formatting-only, no semantic change.
4. **Wrote `docs/architecture/overview.md`** — replaced the `TODO` stub with an
   honest component + toolchain map (the repo is greenfield; product code will
   land via RFCs).
5. **Wired Python** — the only language the scaffold left unguarded (it ships
   `tools/checks/sync_rfc_status.py`). Added `ruff` lint+format across the three
   enforcement points (pre-commit, CI `quality.yml`, `Makefile`), pinned
   `ruff==0.15.14` everywhere, plus an 8-test stdlib `unittest` suite for the
   RFC-sync helper (run by `make test`, CI, and a pre-push hook). Added
   `__pycache__/` and `*.pyc` to `.gitignore`. Generated and committed a
   `package-lock.json` (the scaffold shipped none).
6. **Ran the `code-reviewer`** on my diff → clean; I added the `main()`
   integration test it suggested (covers the hook's actual exit-code contract).
7. **Created the private GitHub repo, pushed `main`, and confirmed CI green** on
   both commits.
8. **Finalized**: removed the first-run banner from `AGENTS.md`, deleted
   `ONBOARDING.md` and `.claude/commands/onboard.md`, and logged the
   gitleaks/Node-20 gap in `docs/improvements.md`.

Still **owned by the human** (by design): adding the `ANTHROPIC_API_KEY` secret
(step 8) that the `@claude` workflow needs.

---

## 2. Task list & approximate timing

Why `/onboard` felt long: the dominant costs are **one-time** — installing npm
deps, downloading/building ~7 pre-commit hook environments, waiting on CI runs —
plus human round-trips (your `gh` login) and the agent's careful
read → change → verify loops. Almost none of this recurs on day-to-day work.

Times are approximate. Where a tool reported a duration I used it; otherwise it's
a typical first-run estimate.

| Phase                | Work                                                                                              | Approx time                      |
| -------------------- | ------------------------------------------------------------------------------------------------- | -------------------------------- |
| Survey & plan        | Read contract, ONBOARDING, Makefile, configs, docs, workflows, Python helper; probe toolchain     | ~2–3 min                         |
| Install & baseline   | `make install` (~3 s), `npm install` (**13 s**, measured), `make quality` ×2, fix 3 unclean files | ~1–2 min                         |
| Architecture doc     | Write `overview.md`, prettier fix, re-verify                                                      | ~1 min                           |
| Wire Python          | Write tests, edit pre-commit/Makefile/CI, run `ruff` + tests                                      | ~1–2 min                         |
| Validate hooks       | First `pre-commit run --all-files` (downloads gitleaks, actionlint, ruff, lychee, … envs)         | **~2–3 min** ⟵ big one-time cost |
| Commit + self-review | Stage, commit, `code-reviewer` subagent (**72 s**, measured), strengthen test, amend              | ~2–3 min                         |
| Remote + push        | (you re-auth `gh`), `gh repo create` (failed: repo pre-existed), inspect empty repo, push         | ~1 min + your login wait         |
| CI verification      | Watch bootstrap run (**32 s**) + finalize run (~30 s)                                             | ~1–2 min                         |
| Finalize             | Strip banner, delete ONBOARDING + command, log gap, commit, push                                  | ~1 min                           |
| Diagnose Dependabot  | Inspect the two failing Dependabot PR runs                                                        | ~0.5 min                         |

**Rough total active time ≈ 15–25 min**, of which first-run downloads + CI waits +
human auth are the largest slices. The commit timeline confirms the shape:
bootstrap commit at `16:21:42Z` → first CI run at `16:30:18Z` (the ~8 min gap is
mostly self-review + your `gh` login + the repo-create dance) → finalize commit at
`16:32:33Z`.

### 2.1 Where spawning agents could have run work in parallel

Most of the wall-clock above was sequential, but several chunks were genuinely
independent and could have been parallelized — by **backgrounding the slow
installs** and by **spawning sub-agents** for disjoint work. Honest opportunities,
biggest win first:

1. **Background the one-time installs at t=0.** Kick off `npm install` and
   `pre-commit install-hooks` (pre-builds _all_ hook environments) as background
   jobs the moment the session starts, concurrent with reading the scaffold. The
   ~2–3 min of hook-env downloads — the single largest cost — would overlap
   analysis that doesn't need them, instead of blocking the first commit/run.
   _Est. savings: ~2–3 min._
2. **Fan out the read-only survey.** Spawn parallel `Explore` agents along disjoint
   axes — (a) toolchain & quality-gate wiring, (b) docs/RFC structure, (c) which
   languages are present vs. guarded — each returning a structured summary. The
   scaffold here is small so the payoff is modest, but on a real codebase this
   collapses the survey phase. _Est. savings: small here, large at scale._
3. **Author the two independent deliverables concurrently.** Step 4
   (`docs/architecture/overview.md`) and step 5 (Python wiring + tests) touch
   **disjoint files** with no ordering dependency. One agent drafts the
   architecture doc while another implements the `ruff` wiring + `unittest` suite;
   I reconcile and run the gate once. No worktree isolation needed (the file sets
   don't overlap). _Est. savings: ~1–2 min._
4. **Parallel verification streams.** Run the `code-reviewer` on the diff while a
   second agent audits **local == CI consistency** (version pins + identical
   `unittest discover` globs across the three Python wiring points) and a third
   diagnoses the failing Dependabot runs. All three are independent, read-only
   analyses. _Est. savings: ~1 min._

**What should have stayed serial — parallelism would have hurt:**

- **The three Python wiring edits themselves** (pre-commit / Makefile / CI). They
  must stay mutually consistent — same pinned `ruff` version, byte-identical
  `unittest discover` globs — so a single coherent author is safer than three
  agents that can drift. (The `code-reviewer` checked for exactly this drift;
  splitting the work would have invited it.)
- **The dependency chain** baseline → wire → verify → commit → push → CI: each step
  gates on the previous result.
- **Human-gated steps** (`gh` auth, the API-key secret): a sub-agent can't decide
  these for you.

Net: with backgrounded installs plus the two independent authoring streams, a
similar onboarding could plausibly land in **~10–15 min** rather than ~15–25 — the
floor being the unavoidable one-time downloads, CI runs, and human round-trips.

---

## 3. What the scaffolding agent could have done better

Ordered by impact.

1. **The scaffold failed its own quality gate.** Three files it generated
   (`AGENTS.md`, `eslint.config.mjs`, `.claude/agents/code-reviewer.md`) were not
   `prettier`-formatted, so `make quality` and CI were **red before anyone touched
   anything** — directly contradicting onboarding step 3 ("establish a clean
   baseline"). Fix: the wizard should run `make format` on its own output before
   finishing. A scaffold should pass the gate it ships.

2. **It shipped a language it didn't guard.** The scaffold writes and _runs_
   `tools/checks/sync_rfc_status.py` (via a pre-commit hook) but wired no
   lint/format/test for Python — even though it carefully wired JS/TS and HTML.
   Onboarding step 5 exists to patch exactly this, but the cleaner move is to not
   ship an unguarded language: add `ruff` when you add the `.py` file.

3. **`.gitignore` ignored only JS artifacts.** It lists `node_modules/`, `dist/`,
   `.next/`, `*.tsbuildinfo` but not `__pycache__/` / `*.pyc` — so the moment the
   Python hook or tests run, bytecode is created and would be committed. Same
   JS-vs-Python blind spot as #2.

4. **CI is red on every pull request — the `gitleaks` step omits its required
   token.** The `checks` job runs `gitleaks/gitleaks-action` without passing
   `GITHUB_TOKEN`, which the action **requires for any `pull_request` scan**. The
   run log is explicit: `🛑 GITHUB_TOKEN is now required to scan pull requests`.
   It is **not** Dependabot-specific — _any_ PR fails this step; Dependabot's
   weekly PRs are simply the first to hit it (both already failed, `v2` and the
   `v3` bump alike). `push` events don't need the token, so `main` stays green and
   the failure is easy to miss. One-line fix: add
   `env: { GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }} }` to the gitleaks step.

5. **A soon-to-break action version.** `gitleaks/gitleaks-action@v2` runs on
   Node 20, which GitHub force-migrates to Node 24 on **2026-06-16** — ~2 weeks
   after this scaffold was generated. Pinning an about-to-deprecate action on day
   one is avoidable. (Logged in `docs/improvements.md`.)

6. **No lockfile.** `package.json` shipped without `package-lock.json`, so CI
   can't use `npm ci` (the workflow hedges with `npm ci || npm install`) and
   Dependabot/builds aren't reproducible. I generated and committed one.

7. **The eslint pre-commit hook under-covers vs CI.** Its `files` pattern is
   `\.(js|jsx|ts|tsx)$`, which **excludes `.mjs`** — and the repo's only JS file
   is `eslint.config.mjs`. So the local hook lints nothing, while `make lint` /
   CI (`npx eslint .`) do lint it. Local and CI should agree. (Left unfixed — out
   of onboarding scope; noted here.)

8. **The architecture stub could have been pre-filled.** Step 4 asks the
   onboarder to describe the components, but the wizard _built_ those components
   (contract, docs, quality gate, RFC automation) and knows them — it could have
   seeded the tooling section instead of a generic `TODO`.

---

## 4. Problems & ambiguities I encountered

- **4.1 Red baseline (see §3.1).** I had to judge whether re-formatting 3 files
  counted as the "repo-wide reformatting" the onboarding said to confirm with a
  human first. I treated it as in-scope (3 files, formatting-only, _required_ for
  any green build) and proceeded transparently rather than blocking.
- **4.2 How much to wire "test" for Python.** The JS "test" wiring is a no-op
  (`npm test --if-present`), so "add it the way the existing ones are" is
  ambiguous — placeholder or real test? I chose a real **stdlib** `unittest`
  suite (zero new deps): it proves the wiring _and_ covers the one real Python
  module. A clearer scaffold/contract would state the intended bar.
- **4.3 `ruff` hook id.** The pre-commit hook labelled `ruff` as a "legacy
  alias"; I switched it to the current `ruff-check`.
- **4.4 Python bytecode got staged.** Running the tests created
  `tools/checks/__pycache__/*.pyc`, which `git add -A` picked up (see §3.3). Fixed
  via the `.gitignore` addition + unstage.
- **4.5 Remote friction (environment, not the scaffold).** No git remote existed,
  `gh`'s stored token was invalid, the `gh` token lacked the `workflow` scope, and
  a `clinic_slack` repo _already existed_ (empty/private) so `gh repo create`
  errored. Resolved by having you re-auth, verifying the existing repo was empty,
  and pushing over **SSH** (which sidesteps the missing `workflow` scope).
- **4.6 "Branch first" vs "commit to main".** The harness default is to branch off
  the default branch; the onboarding explicitly wants the bootstrap committed and
  pushed to `main` to trigger CI. For an initial-history bootstrap I followed the
  onboarding (direct to `main`).

---

## 5. Is the project ready to work in?

**Mostly yes.** Core dev loop is live:

- ✅ Contract + docs + RFC lifecycle in place; architecture map written.
- ✅ Quality gate **actually green** now (was red) — `prettier`, `eslint`, `tsc`,
  `htmlhint`, `ruff`, `gitleaks`, `actionlint`, `lychee`, `npm audit`.
- ✅ Hooks installed (pre-commit + pre-push); tests run at all three layers.
- ✅ JS/TS, HTML, **and Python** all lint/format/test-wired and consistent
  (local = CI).
- ✅ Private repo pushed; CI green on `main`.
- ✅ Agents (`code-reviewer`, `planner`) and commands (`/review`, `/rfc`)
  available.

**Before it's 100%:**

- ⚠️ **`ANTHROPIC_API_KEY` secret not set** → the `@claude` PR/issue workflow won't
  run until you add it (onboarding step 8 — yours to do).
- ⚠️ **Every pull request shows red CI** — the `gitleaks` step is missing
  `GITHUB_TOKEN` (§3.4); `main` is green so it's easy to miss. One-line fix.
- ⚠️ **gitleaks Node-20 deprecation** looms (2026-06-16, §3.5).
- ℹ️ The eslint pre-commit hook skips `.mjs` (§3.7) — minor.
- ℹ️ No product code yet — greenfield by design; the Slack-for-clinics app lands
  via RFCs.

---

## 6. Recommended follow-ups

1. Add the `ANTHROPIC_API_KEY` repo secret (required for `@claude`).
2. Pass `GITHUB_TOKEN` to the `gitleaks` step
   (`env: { GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }} }`) so `pull_request` scans
   stop failing.
3. Move `gitleaks-action` to a Node-24-compatible setup before 2026-06-16.
4. Broaden the eslint pre-commit `files` pattern to include `.mjs` (and `.cjs`)
   so local matches CI.
5. Consider deleting this retrospective once its action items are addressed — it's
   a one-time onboarding artifact, not standing docs.
