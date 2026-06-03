"""The node (JS/TS) language entry: a toolchain the generated gate can actually run."""

from __future__ import annotations

from pathlib import Path

from agent_native_setup import cli
from agent_native_setup.config import WizardConfig
from agent_native_setup.scaffold import Scaffolder


def _build(tmp_path: Path, **overrides: object) -> Path:
    overrides.setdefault("project_name", "demo")
    config = WizardConfig(output_dir=tmp_path, init_git=False, **overrides)
    cli.build(config, Scaffolder(config.target))
    return tmp_path


def _makefile(tmp_path: Path, **overrides: object) -> str:
    return (_build(tmp_path, languages=["node"], **overrides) / "Makefile").read_text(
        encoding="utf-8"
    )


def test_node_ships_package_json_and_tsconfig(tmp_path: Path) -> None:
    # Without these the eslint config / npx tsc can't resolve and the gate fails on step 1.
    root = _build(tmp_path, languages=["node"])
    assert (root / "package.json").exists()
    assert (root / "tsconfig.json").exists()


def test_package_json_pins_the_toolchain_and_uses_slug(tmp_path: Path) -> None:
    pkg = (_build(tmp_path, project_name="My App", languages=["node"]) / "package.json").read_text(
        encoding="utf-8"
    )
    for dep in ("eslint", "typescript-eslint", "prettier", "typescript"):
        assert f'"{dep}"' in pkg
    assert '"my-app"' in pkg  # rendered slug, a valid npm name


def test_format_writes_and_format_check_is_separate(tmp_path: Path) -> None:
    # `format` (auto-format) must write; the read-only check is its own target.
    mk = _makefile(tmp_path)
    assert "format: ## auto-format\n\tnpx prettier --write ." in mk
    assert "format-check: ## check formatting (read-only)\n\tnpx prettier --check ." in mk


def test_typecheck_is_guarded_for_an_empty_repo(tmp_path: Path) -> None:
    # `tsc --noEmit` errors with zero .ts files; the gate must no-op until TS exists,
    # using if/then/else (not `&& ... ||`) so a real type error still fails.
    mk = _makefile(tmp_path)
    assert "git ls-files '*.ts' '*.tsx' | grep -q .; then npx tsc --noEmit" in mk
    assert "else echo" in mk


def test_bootstrap_target_does_hooks_then_deps(tmp_path: Path) -> None:
    # `make bootstrap` is the one deterministic first-run setup the agent can just run:
    # install the git hooks (via the `install` dep) then fetch deps (npm install).
    mk = _makefile(tmp_path)  # node
    block = mk.split("bootstrap:")[1].split("\n\n")[0]
    assert mk.count("bootstrap: install ## ") == 1  # depends on the hooks target
    assert "npm install" in block
    # No deps to fetch -> no bootstrap target (the hooks-only `install` suffices).
    py = (_build(tmp_path / "py", languages=["python"]) / "Makefile").read_text(encoding="utf-8")
    assert "bootstrap:" not in py


def test_bootstrap_without_hooks_fetches_deps_only(tmp_path: Path) -> None:
    # Git hooks are optional (--no-hooks); bootstrap still exists for the deps but must
    # not depend on / claim the (absent) hooks.
    mk = _makefile(tmp_path, git_hooks=False)
    assert "install:" not in mk  # no hooks target
    assert "bootstrap: ## first-run setup: fetch deps" in mk  # accurate desc, no deps
    assert "npm install" in mk
    onb = (_build(tmp_path / "o", languages=["node"], git_hooks=False) / "ONBOARDING.md").read_text(
        encoding="utf-8"
    )
    assert "make bootstrap" in onb  # still guided to fetch deps
    assert "pipx install pre-commit" not in onb  # no hooks -> no pre-commit prereq


def test_prettierignore_excludes_markdown_and_lockfile(tmp_path: Path) -> None:
    # The wizard's hand-authored Markdown isn't prettier-formatted; ignoring it (and the
    # generated lockfile) keeps `prettier --check` from reddening the gate on day one.
    pi = (_build(tmp_path, languages=["node"]) / ".prettierignore").read_text(encoding="utf-8")
    assert "*.md" in pi
    assert "package-lock.json" in pi


def test_precommit_hooks_cover_mjs(tmp_path: Path) -> None:
    # CI runs `eslint .`/`prettier .` (which lint eslint.config.mjs); the local hooks
    # must match by covering .mjs/.cjs, else the only JS file is linted only in CI.
    pc = (_build(tmp_path, languages=["node"]) / ".pre-commit-config.yaml").read_text(
        encoding="utf-8"
    )
    assert "js|jsx|mjs|cjs|ts|tsx" in pc  # eslint hook
    assert "mjs" in pc.split("id: prettier")[1].split("id: eslint")[0]  # prettier hook too


def test_local_gate_matches_ci_checks(tmp_path: Path) -> None:
    # Green locally should mean green in CI: the gate runs format-check + typecheck,
    # and CI runs the same tsc step it used to skip.
    root = _build(tmp_path, languages=["node"])
    mk = (root / "Makefile").read_text(encoding="utf-8")
    assert "quality: lint format-check typecheck test" in mk
    wf = (root / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    assert "npx prettier --check ." in wf  # CI formatting check
    assert "npx tsc --noEmit" in wf  # CI now type-checks too (guarded)
