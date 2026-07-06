# Ship the tools/checks helpers with their tests and a runner

- **Status:** Active
- **Date:** 2026-06-03
- **Author:** Luca Mastrostefano

## Context

A fresh onboarding retrospective (`scaffold-review.md`, §3.3 / §4) flagged that the
scaffold violates its own contract: `AGENTS.md` §4 says "every change ships with the
test that proves it," yet the wizard scaffolds `tools/checks/*.py` — real branching
logic — with **no test and, for a non-Python project, no test runner at all**.

Verified against source:

- `docs.generate` always writes `tools/checks/sync_rfc_status.py` (the `parse_status`
  / `target_folder` / `find_moves` logic), plus `rfc_needed.py` + `docs_sync.py` for
  Python projects — and never writes a test for any of them.
- The earlier "guard shipped Python" fix (`b87a281`) wired a *ruff* guard
  (`TOOLS_RUFF_HOOK` / `TOOLS_RUFF_CI`) at all three layers, but ruff only lints/formats
  — nothing exercises the logic.
- A generated project's own test runner doesn't reach these: pytest is wired only when
  Python is a selected language, and even then `testpaths = ["tests"]` excludes
  `tools/checks/`. A node/go/rust project has no Python runner at all.
- We don't dogfood this either: there is no `tests/test_sync_rfc_status.py` in this
  repo, so our own copy of that helper is untested too.

## Decision

Treat the shipped `tools/checks` helpers like any other shipped logic: each ships with
its test, and a runner enforces them at all three layers — whenever the helpers ship
(`include_docs`), independent of the selected languages.

1. **Scaffold a test beside each shipped helper**, in stdlib `unittest`:
   - `tools/checks/test_sync_rfc_status.py` — always (it always ships).
   - `tools/checks/test_rfc_needed.py` + `tools/checks/test_docs_sync.py` — for Python
     projects (when those helpers ship).
   - `unittest`, **not pytest**, so they run with only `python3` on PATH (the
     invocation switched from `python` after real-run feedback, 2026-07-06) — no new
     dependency, and they work whether or not Python is a selected language. Kept
     ruff-clean and ≤88 cols (non-Python projects have no `line-length=100`), so they
     pass the existing `tools/` ruff guard.
2. **Wire a runner** at all three layers whenever helpers ship, generalizing today's
   `ships_tools_python` guard (which covers only lint/format, and only when Python
   isn't selected) to also cover tests — and, for the test layer, *even when Python is
   selected*, since the project's pytest doesn't reach `tools/checks/`:
   - **Command surface** — a `test`-leg entry
     `python -m unittest discover -s tools/checks -p "test_*.py"`, so `quality` runs it.
   - **Pre-push hook** — a local hook running the same (today pre-push tests fire only
     for a *language's* suite, so a non-Python repo gets none).
   - **CI** — a step running the same, reusing the `setup-python` that
     `TOOLS_RUFF_CI` already adds (`_dedupe_steps` collapses the duplicate).
3. **Dogfood it.** Keep `tools/checks/test_sync_rfc_status.py` in this repo, assert it
   byte-for-byte in the wizard suite (as `test_embedded_scripts_match_repo_files` does
   for the helpers), and wire the same `unittest discover` step into this repo's Taskfile
   / pre-push / CI. This closes our own previously-missing `sync_rfc_status` coverage.
   The Python-only helper tests (`rfc_needed` / `docs_sync`) are **not** kept as in-repo
   copies — they'd share a basename with this repo's existing richer `tests/` suites and
   collide in pytest/mypy — so the wizard still ships them, and a build-and-run test
   (`test_shipped_tests_pass_against_shipped_helpers`) verifies them end-to-end instead.

Shipped tests are a minimal smoke + pure-function check (the logic, not every branch),
not a port of this repo's richer pytest suites — enough to satisfy the contract without
bloating generated output.

Alongside (no separate RFC — runbook polish, not a contract change), fold in the other
verified retrospective items: soften `ONBOARDING.md`'s `pipx install pre-commit` to not
assume one installer (§3.2); sharpen the greenfield architecture step to say "leave as
TODOs if no product code exists yet" (§3.4); and add a one-line note that the first
direct-to-`main` push will prompt for approval under the agent harness (§3.5).

## Consequences

- The scaffold stops shipping untested logic — it now satisfies its own §4 across every
  layer, including for non-Python projects, with no new toolchain assumption (`python`
  is already required to *run* the helpers).
- Generated output grows by one to three small test files and one runner entry per
  layer; CI gains no extra `setup-python` (deduped).
- This repo gains the `sync_rfc_status` test it was missing. The other two shipped tests
  aren't duplicated in-repo (they'd collide with the existing `tests/` suites), so their
  in-repo proof is the end-to-end build-and-run test rather than a byte-for-byte copy.

## Alternatives considered

- **Scaffold pytest tests under `tests/` instead.** Forces a pytest runner (and a
  `pipx`/pip install) onto non-Python projects — the exact assumption §3.2 warns against
  — and entangles with the project's own `testpaths`.
- **Lint-only, as today (`b87a281`).** Ruff proves the helpers parse and are formatted,
  not that they *work*; the contract asks for the test that proves the change.
- **Only test `sync_rfc_status.py`** (the always-shipped one). Smaller, but leaves
  `rfc_needed` / `docs_sync` — also real logic — shipping untested to Python projects.
- **Do nothing / record as a known gap.** It's a self-consistency hole in the wizard's
  flagship promise; cheap to close now.
