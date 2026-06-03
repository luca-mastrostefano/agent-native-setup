"""The node (JS/TS) language entry: a toolchain the generated gate can actually run."""

from __future__ import annotations

from pathlib import Path

from ai_setup import cli
from ai_setup.config import WizardConfig
from ai_setup.scaffold import Scaffolder


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


def test_local_gate_matches_ci_checks(tmp_path: Path) -> None:
    # Green locally should mean green in CI: the gate runs format-check + typecheck,
    # and CI runs the same tsc step it used to skip.
    root = _build(tmp_path, languages=["node"])
    mk = (root / "Makefile").read_text(encoding="utf-8")
    assert "quality: lint format-check typecheck test" in mk
    wf = (root / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    assert "npx prettier --check ." in wf  # CI formatting check
    assert "npx tsc --noEmit" in wf  # CI now type-checks too (guarded)
