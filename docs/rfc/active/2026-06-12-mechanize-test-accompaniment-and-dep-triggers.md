# Agent-experience upgrades: permission allowlist, format-on-edit, test gate, manifest dep-triggers

- **Status:** Active
- **Date:** 2026-06-12
- **Author:** agent-native-setup team

## Context

Four gaps slow agents down in scaffolded repos. (a) The commands the contract
itself instructs an agent to run (`make lint`, `pre-commit`, read-only git) each
cost a permission prompt. (b) Formatting failures are the most common quality-gate
red an agent hits — always self-inflicted, always a wasted loop. (c) Of the four
execution principles, §4 ("every change ships with the test that proves it") is
the only one with no mechanical backstop. (d) The `rfc-needed` gate enforces "RFC
before a new dependency" only for `pyproject.toml`: a Node, Go, or Rust project
gets no gate at all.

For (c) and (d) the repo already has the right idiom: commit-msg hooks that fire
on a mechanical signal, satisfied by the required artifact staged in the same
commit or an explicit waiver trailer (`RFC-Not-Needed:`, `Docs-Not-Needed:`).

## Decision

1. **Generate a `permissions.allow` list in `.claude/settings.json`**: the
   wizard-authored runner (`Bash(make:*)`/`Bash(task:*)`), `pre-commit`, and
   read-only git (`status`/`diff`/`log`/`show`). A *pre-existing* runner's targets
   are unknown (`make deploy`? `task release`?), so they are deliberately not
   pre-approved. `pre-commit` includes `uninstall`/`autoupdate`; accepted, since
   any effect lands in the reviewable diff.
2. **Ship a format-on-edit `PostToolUse` hook** (Claude + quality + docs, when a
   selected language has a formatter): `tools/checks/format_on_edit.py` reads the
   hook event and formats the just-edited file by extension
   (`Language.format_file_cmd`). Best-effort: every failure exits 0; pre-commit
   stays the enforcer.
3. **Ship a `tests-needed` commit-msg gate** (Python projects, like the other
   layout-shaped gates): a commit that changes `src/**/*.py` but stages nothing
   test-like (under `tests/`, or named `test_*` / `*_test.py`) fails with a message
   showing the fix; `Tests-Not-Needed: <reason>` waives it. It checks presence,
   not quality — review keeps owning quality.
4. **Extend `rfc_needed`'s dependency trigger to every manifest language**: parse
   added names from `package.json` (dependencies + devDependencies), `go.mod`
   (require lines, excluding comments and `// indirect`), and `Cargo.toml`
   ([dependencies]/[dev-dependencies]/[build-dependencies]) alongside the existing
   `pyproject.toml` parsing. The hook ships whenever a selected language has a
   dependency manifest (those with a Dependabot ecosystem), not just Python.

## Consequences

The contract-prescribed loop runs prompt-free, format reds disappear from agent
sessions, and §4 plus the dependency-RFC rule become mechanical; waiver trailers
keep an auditable escape hatch in commit history. The hooks stay stdlib-only, ship
with their tests, and are dogfooded in this repo. Pure-deletion commits and version
bumps don't fire. Cost: one more trailer to know about, three small parsers in
`rfc_needed.py`, and a `format_file_cmd` field per language.

## Alternatives considered

- **CI-side test-presence check** — later feedback (after push) and no waiver
  audit trail in the commit; commit-msg matches the existing gates.
- **Coverage thresholds** — heavier, language-specific toolchains, and gameable;
  presence + review is the scaffold's stated division of labor.
- **One generic source-vs-test heuristic for all languages** — test layouts vary
  too much outside the scaffold's own `src/`+`tests/` Python shape; shipping a
  wrong gate is worse than shipping none.
