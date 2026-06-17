# Language profiles must pass their own generated gate

- **Status:** Active
- **Date:** 2026-06-03
- **Author:** Luca Mastrostefano

## Context

An onboarding agent ran `/onboard` on a freshly scaffolded **node + html**
project and found the generated gate could not pass as delivered:

- `eslint.config.mjs` imports `typescript-eslint` and the Makefile/CI call
  `npx eslint`/`tsc`/`prettier`, but no `package.json`/lockfile shipped — so
  `npm ci`/`npx eslint` fail with `ERR_MODULE_NOT_FOUND` on step one.
- `typecheck` was `npx tsc --noEmit` with no `tsconfig.json` and zero `.ts`
  files, which errors ("No inputs were found"); `quality` depends on it, so the
  whole gate went red on an empty repo.
- The node `format` command was `prettier --check` — it never wrote, unlike
  python/go/rust whose `format` writes.
- The local gate and CI enforced *different* checks: `make quality` ran `tsc`
  but not `prettier`; CI ran `prettier --check` but not `tsc`. "Green locally"
  did not predict "green in CI".
- `tools/checks/sync_rfc_status.py` ships for every project (the `rfc-status`
  hook needs it) but exceeded the default 88-col line length, so a project that
  wired Python with default settings saw it flagged.
- `htmlhint` ran via `npx --yes` (unpinned), so its version floated.

The through-line: a `Language` profile is only done when the gate it generates
is one a fresh repo can actually run green.

## Decision

Complete the **node** profile and make the gate/CI symmetric, generically:

- Ship `package.json` (pinned `eslint`, `typescript-eslint`, `prettier`,
  `typescript`) and a strict, `noEmit` `tsconfig.json`. `npm install` writes the
  lockfile on first run.
- Guard `typecheck`: run `tsc` only once a `.ts`/`.tsx` file is tracked
  (`if git ls-files … | grep -q .; then tsc; else echo "no TypeScript yet"; fi`).
  `if/then/else`, not `&& … ||`, so a real type error still fails the gate. The
  same guarded command runs in CI.
- Split formatting into `format` (writes) and a new read-only **`format-check`**
  label. The local `quality` gate depends on `format-check`, so it now checks
  formatting the way CI does without the gate rewriting files. Defined for every
  language with a formatter (`format-check` commands stay `$()`-free so they are
  identical under Make, Task, and CI).
- Pin `htmlhint@1.1.4` inline (html may be selected without the node toolchain,
  so it stays an `npx` invocation rather than a `package.json` dependency).
- Keep `sync_rfc_status.py` ≤ 88 cols so it is lint-clean under any config, and
  note in `ONBOARDING.md` that the RFC/docs hooks need `python` on PATH.

### Follow-up (same theme, applied after a second onboarding run)

- **The scaffold must pass its own formatter.** Conform `eslint.config.mjs` to
  prettier's output, and ship a `.prettierignore` (`*.md`, `package-lock.json`,
  `dist/`) so prettier covers code, not the hand-authored Markdown it would
  otherwise reflow — which had reddened the gate on the wizard's own output.
- **Guard the language you ship, not just the one selected.** When the docs
  machinery ships `tools/checks/*.py` into a non-Python project
  (`config.ships_tools_python`), wire a ruff guard scoped to `tools/` at all three
  layers (pre-commit, command surface, CI) so it can't drift — superseding the
  weaker "keep it ≤ 88 cols" stopgap above.

## Consequences

- A scaffolded JS/TS project passes `make quality` and CI from the first run.
- New invariant: **the local gate is a superset of CI** — the `format-check`
  label is the mechanism. New languages adding a formatter should add it.
- `tsc` is in the gate from day one but inert until TypeScript exists, so type
  checking turns on automatically rather than being homework.
- Cost: `package.json` pins drift over time (Dependabot tracks the npm
  ecosystem); the guarded-`tsc` shell snippet is a little more than a bare command.

## Alternatives considered

- **Drop `tsc` until TypeScript exists:** simpler, but no type checking even
  once `.ts` lands until someone re-adds it. The guard keeps it on for free.
- **Derive the format-check from the writing `format` command:** not mechanical
  across tools (`ruff format`→`--check`, `gofmt -w`→`gofmt -l`), so an explicit
  label is clearer than per-language string surgery.
- **Add `htmlhint` to `package.json`:** couples html to the node toolchain;
  pinning the `npx` version keeps html self-contained.
