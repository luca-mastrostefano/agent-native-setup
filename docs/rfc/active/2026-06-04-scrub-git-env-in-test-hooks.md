# Scrub git's exported env in pre-push test hooks

- **Status:** Active
- **Date:** 2026-06-04
- **Author:** Luca Mastrostefano

## Context

`git` exports `GIT_DIR` / `GIT_WORK_TREE` / `GIT_INDEX_FILE` into the environment of every
hook it runs, and those **override `cwd`**. The scaffold wires each language's test suite
(and the `tools/checks` tests) into a **pre-push** hook. A test that builds a throwaway repo
in a temp dir and shells out to `git` inherits the hook env, so its `git` calls resolve to
the **real** repo instead of the temp one — the suite fails *only under the hook*.

It's invisible three ways, which is the real trap:

- `make quality` / `task test` run the *identical* command outside a hook → green.
- CI runs the tests as a normal step (no `GIT_DIR`) → green.
- Only `git push` (the pre-push hook) is red — and a scaffolded project hit exactly this
  (37 errors, confirmed by reproducing with `export GIT_DIR`). This repo's own suite is
  latently affected too (`tests/test_rfc_needed.py` does `git init` in a temp dir).

## Decision

Prefix the **test** pre-push hook entries with `env -u GIT_DIR -u GIT_WORK_TREE -u
GIT_INDEX_FILE` so the test process — and its `git` subprocesses — discover the repo from
their own `cwd`. Applies to the per-language `_test_hook` and the `tools-checks-tests` hook
only. The `commit-msg` (`rfc-needed` / `docs-sync`) and `rfc-status` hooks are git-aware and
*should* operate on the real repo, so they keep the inherited env. The onboarding "wire up
a language" step notes the same for any new test hook. Dogfood into this repo's
`.pre-commit-config.yaml`.

## Consequences

- `git push` and `make` / `task test` now agree (both green) instead of the hook
  structurally failing on a git-using suite — the inconsistency the scaffold shipped is gone.
- The scrub is a no-op outside a hook (the vars aren't set), so it's safe everywhere.
- This is the scaffold's half. A project whose *production* code shells out to git should
  also clear these vars for robustness — that's the project's code, not the scaffold's.

## Alternatives considered

- **Don't wire tests into a pre-push hook:** loses the safety net that catches a broken
  suite before it reaches CI.
- **Ship a wrapper script that scrubs the env:** heavier than a one-token entry prefix, and
  less studyable.
- **Only document it (tell the onboarding agent):** leaves the generated hooks themselves
  broken for git-using suites. Fix the generator *and* note it — the working hook teaches
  by example.
