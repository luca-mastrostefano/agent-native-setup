# Legacy-aware quality setup — grandfather existing code, don't gate it on day one

- **Status:** Active
- **Date:** 2026-06-01
- **Author:** Luca Mastrostefano

## Context

The wizard already scaffolds into existing repos: it detects languages
(`detect_languages`) and is non-destructive (the `Scaffolder` skips files that
already exist). But the quality tooling it writes assumes a *greenfield* repo:

- The generated CI (`ci.py`) runs **whole-repo** checks — `ruff check .` /
  `ruff format --check .` / `npx eslint .` / `npx prettier --check .` /
  `gofmt -l .` / `cargo clippy`. On a legacy codebase the first PR goes red and
  stays red until the entire repo is reformatted/fixed, blocking all work.
- Auto-format hooks are safe locally — pre-commit only touches *staged* files — but
  a `pre-commit run --all-files` rewrites the whole tree in one noisy commit.

We already ask *whether* to set up quality (`include_quality`, `git_hooks`). The
gap is that we don't adapt to legacy reality: turning the gate on shouldn't mean
"clean the entire existing codebase before your next commit can land."

The standard resolution is to **grandfather existing code and ratchet new code**:
never gate legacy code, require only changed/new code to pass, and offer a clean
one-time cleanup with `git blame` preserved.

## Decision

Detect when we're scaffolding into a **populated** repo — `detect_languages`
already finds pre-existing source for the selected languages — and set
`config.existing_project`. Greenfield behavior is unchanged; for an existing repo:

1. **Warn** — a printed notice (and interactive prompt) explaining that existing
   code is grandfathered and how to do a full cleanup when ready.
2. **Ratchet the CI gate to changed files.** For existing projects the generated
   `quality.yml` runs on `pull_request` only, checks out with `fetch-depth: 0`,
   resolves the PR base into `$DIFF_BASE`, and lints only files changed vs the
   base:
   - file-scoped tools take the changed list directly: `ruff check $files`,
     `ruff format --check $files`, `npx eslint $files`, `npx prettier --check
     $files`, `gofmt -l $files`, `rustfmt --check $files`;
   - golangci-lint uses its native `--new-from-rev=$base` (reports only new
     issues);
   - clippy is whole-crate with no changed-file mode, so it runs
     `continue-on-error` (surfaced, non-blocking) on existing projects.
   Each step no-ops when nothing of its language changed. Legacy code is never
   gated until edited.
3. **Scaffold the clean cleanup path** — emit `.git-blame-ignore-revs` (with
   instructions) and an "Adopting on an existing codebase" section in
   `CONTRIBUTING.md`: run `task format` once, commit it alone, record its SHA
   in `.git-blame-ignore-revs`, set `git config blame.ignoreRevsFile`. Blame stays
   intact.
4. **Leave the local loop alone** — pre-commit stays changed-files-only, so daily
   work only touches code you edit.

## Consequences

- Adopting on a legacy repo no longer means red CI on day one or a forced mass
  reformat. New/changed code is held to the standard immediately; existing code is
  cleaned up on the user's schedule, with blame preserved.
- The CI workflow gains a second shape (greenfield whole-repo vs existing ratchet),
  adding generation + test surface. The ratchet shell (base resolution, per-tool
  file filtering) is best-effort and only fully exercised in a real Actions run;
  unit tests assert the generated YAML, not its runtime behavior.
- Honest tool limits: clippy can't scope to changed files, so legacy Rust lint is
  *reported but not enforced* (formatting still is, via `rustfmt --check $files`).
  Non-formatting lint findings elsewhere aren't auto-fixed by `task format`; fix
  them as code is touched, or scope rules in the linter config.
- Existing-project CI runs on `pull_request` only — main is assumed to be updated
  via PRs. Direct pushes to main are not gated (documented).
- Detection is heuristic; a false "existing" reading just adds a notice + a
  `.git-blame-ignore-revs` and changed-files CI (harmless), a false "new" reverts
  to today's behavior.

## Alternatives considered

- **Big-bang only (warn + blame-ignore + docs, CI stays whole-repo):** simpler, and
  the standard way to adopt *formatters*, but it still forces an immediate full
  cleanup before CI is green and ignores non-auto-fixable lint. Kept its pieces
  (warn + blame-ignore + docs) and added the ratchet on top.
- **Just ask "do you want quality checks?"** We already ask; it doesn't address the
  blast radius.
- **Whole-repo gate made non-blocking on existing repos:** a gate nobody must pass
  gets ignored — against the mechanical-enforcement pillar.
- **Per-language baseline files** (snapshot violations, fail only on new ones): most
  precise, but heavy and tool-specific; the changed-files ratchet plus native
  new-code flags gets most of the value with far less machinery.
