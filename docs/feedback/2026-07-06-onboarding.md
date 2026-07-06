# agent-native-setup onboarding feedback

**Scaffolder version:** 0.6.2.dev55+ga135cad7b
**Profile:** agent-native-baseline 0.1.0
**Date:** 2026-07-06
**Environment:** macOS (darwin), Python 3.14.0, Node 24.6.0, npm 11.5.1

---

## 1. Scaffolded file ships with formatting violations

`tools/checks/test_rfc_needed.py` fails `ruff format --check` out of the box. This means `make quality` cannot pass on a fresh scaffold without first running `make format` — but the onboarding instructions say to run `make quality` to "establish a clean baseline," implying it should already be clean.

**Impact:** The agent (or human) has to diagnose and fix a formatting issue before the baseline can be established. Confusing for a first-run experience.

**Suggestion:** Run `ruff format` on all generated Python files as a post-scaffold step, or add a self-check to the wizard that verifies `make quality` passes on the output it just produced.

---

## 2. `.agent-native-setup.json` also fails Prettier

Same category as above — the scaffold's own metadata file doesn't pass `npx prettier --check`. Since `prettier` is configured in the project and `.agent-native-setup.json` isn't in `.prettierignore`, it gets checked.

**Suggestion:** Either format the JSON file during generation, or add it to `.prettierignore`.

---

## 3. mypy fails on `tomllib` import in generated code

`tools/checks/rfc_needed.py:51` imports `tomllib` (stdlib since Python 3.11). On Python 3.14, mypy 2.1.0 reports `[import-untyped]` because the module lacks a `py.typed` marker in this mypy version. This breaks `make typecheck`.

**Fix applied:** Added a `[[tool.mypy.overrides]]` section for `tomllib` in `pyproject.toml` with `ignore_missing_imports = true`.

**Suggestion:** Ship this override in the generated `pyproject.toml`, or pin a mypy version range where `tomllib` stubs are bundled, or add a `# type: ignore[import-untyped]` comment on the import line.

---

## 4. `python` is not on PATH — only `python3`

The Makefile, pre-commit hooks, and `ONBOARDING.md` all reference `python` (not `python3`). On modern macOS with Homebrew Python, only `python3` is on PATH by default. The scaffolder doesn't check for this or warn about it.

**Impact:** Every `python tools/checks/...` invocation fails until the user creates a symlink or alias. This is the kind of thing that silently breaks commit-msg and pre-push hooks later, producing confusing errors.

**Suggestion:** Either:
- Use `python3` everywhere (more portable on macOS/Linux), or
- Detect during scaffolding whether `python` resolves and warn if not, or
- Add a `make doctor` target that checks all expected binaries are on PATH.

---

## 5. Required CLI tools not installed by `make bootstrap`

`ONBOARDING.md` step 3 says: "`make quality` runs `ruff`, `mypy`, and `pytest` directly, so install them on your PATH first." This is easy to miss or get wrong. The bootstrap step installs git hooks and npm deps, but leaves the Python CLI tools as a manual exercise.

**Impact:** There's a gap between "run `make bootstrap`" (step 2) and "run `make quality`" (step 3) that requires the user to know which tool installer to use (`pipx`, `uv tool`, `pip install --user`, etc.) and install four separate tools.

**Suggestion:** Either:
- Have `make bootstrap` install the Python tools too (detect `uv`/`pipx`/`pip` and use whichever is available), or
- Add a `make doctor` or `make check-deps` target that reports what's missing and how to install it, or
- At minimum, give the exact install command in `ONBOARDING.md` instead of just listing tool names (e.g., `uv tool install ruff mypy pytest pre-commit`).

---

## 6. Branch is `master`, not `main`

`git init` defaults to `master` on many systems. The scaffold's onboarding says to commit to `main`, and the repo's main branch metadata says `main`, but the actual branch after `git init` is `master`. The scaffolder doesn't rename it.

**Suggestion:** Run `git branch -m master main` as part of the scaffold, or document the rename in `ONBOARDING.md`.

---

## 7. `ONBOARDING.md` step 4 is a no-op for new projects

Step 4 says to flesh out `docs/architecture/overview.md`, but immediately concedes "if there's no product code yet, leave those sections as TODOs and move on." For a brand-new scaffold (which is the only time onboarding runs), there's never product code — so this step always resolves to "move on."

**Suggestion:** Remove this step from onboarding entirely and instead add a note in the architecture doc itself saying "fill this in when product code lands." One less step to read and skip.

---

## 8. Step 5 (wire uncovered languages) is also a no-op

The scaffolder already wires lint/format/test for every language the user selected during setup. So step 5 ("wire up any uncovered language") has nothing to do — the wizard already did it. It only makes sense if someone manually adds a new language *after* scaffolding, which isn't an onboarding concern.

**Suggestion:** Drop this from onboarding. The guidance belongs in `INSTRUCTION.md` (where it already is) as a standing rule, not a one-time step.

---

## Summary

The scaffolder produces a solid structure and the hook/tooling wiring is comprehensive. The friction is almost entirely in the "last mile" — the generated files don't pass the generated quality gate on a clean run. Three fixes would eliminate most of the onboarding pain:

1. **Self-test the output:** run `make quality` as a post-scaffold verification and fix any failures before handing off to the user.
2. **Install or verify dependencies:** either install the required CLI tools during bootstrap, or provide a `make doctor` that tells you exactly what's missing.
3. **Trim the no-op steps:** steps 4 and 5 always resolve to "skip" for new projects — removing them makes the onboarding shorter and less ambiguous.
