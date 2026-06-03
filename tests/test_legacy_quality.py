"""Legacy-aware quality setup: an existing repo gets a changed-files ratchet, not a blast."""

from __future__ import annotations

from pathlib import Path

from agent_native_setup import cli
from agent_native_setup.config import WizardConfig
from agent_native_setup.scaffold import Scaffolder


def _build(tmp_path: Path, **overrides: object) -> Path:
    config = WizardConfig(project_name="demo", output_dir=tmp_path, init_git=False, **overrides)
    cli.build(config, Scaffolder(config.target))
    return tmp_path


# --- detection through the CLI -------------------------------------------------


def test_cli_detects_existing_python_and_ratchets(tmp_path: Path) -> None:
    (tmp_path / "legacy.py").write_text("x = 1\n")
    cli.main(["demo", "-o", str(tmp_path), "--languages", "python", "--yes", "--no-git"])
    wf = (tmp_path / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    assert "DIFF_BASE" in wf
    assert "ruff check ." not in wf  # whole-repo gate is gone
    assert "ruff check $files" in wf
    assert "on:\n  pull_request:" in wf
    assert (tmp_path / ".git-blame-ignore-revs").exists()
    contributing = (tmp_path / "docs/contributing.md").read_text(encoding="utf-8")
    assert "Adopting on an existing codebase" in contributing


def test_cli_greenfield_keeps_whole_repo_gate(tmp_path: Path) -> None:
    cli.main(["demo", "-o", str(tmp_path), "--languages", "python", "--yes", "--no-git"])
    wf = (tmp_path / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    assert "ruff check ." in wf
    assert "DIFF_BASE" not in wf
    assert "branches: [main]" in wf  # still gates push to main
    assert not (tmp_path / ".git-blame-ignore-revs").exists()
    contributing = (tmp_path / "docs/contributing.md").read_text(encoding="utf-8")
    assert "Adopting on an existing codebase" not in contributing


# --- per-language ratchet content ---------------------------------------------


def test_go_ratchet_uses_new_from_rev(tmp_path: Path) -> None:
    _build(tmp_path, languages=["go"], existing_project=True)
    wf = (tmp_path / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    assert "--new-from-rev=" in wf
    assert "fetch-depth: 0" in wf


def test_rust_ratchet_clippy_is_non_blocking(tmp_path: Path) -> None:
    _build(tmp_path, languages=["rust"], existing_project=True)
    wf = (tmp_path / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    assert "continue-on-error: true" in wf
    assert "rustfmt --check" in wf
