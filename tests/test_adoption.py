"""The legacy adoption strategy: progressive / full / none drive the gate coherently."""

from __future__ import annotations

from pathlib import Path

from agent_native_setup import cli
from agent_native_setup.config import WizardConfig
from agent_native_setup.scaffold import Scaffolder


def _build(tmp_path: Path, **overrides: object) -> Path:
    config = WizardConfig(project_name="demo", output_dir=tmp_path, init_git=False, **overrides)
    cli.build(config, Scaffolder(config.target))
    return tmp_path


def _wf(root: Path) -> str:
    return (root / ".github/workflows/quality.yml").read_text(encoding="utf-8")


def _deps(root: Path) -> str:
    return (root / ".github/dependabot.yml").read_text(encoding="utf-8")


def test_progressive_ratchets_and_security_only(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["python"], existing_project=True, adoption="progressive")
    assert "DIFF_BASE" in _wf(root)  # ratchet — changed files only
    assert "open-pull-requests-limit: 0" in _deps(root)  # dependabot security-only


def test_full_enforces_whole_repo_blocking(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["python"], existing_project=True, adoption="full")
    wf = _wf(root)
    assert "DIFF_BASE" not in wf  # whole repo, not a ratchet
    assert "ruff check ." in wf
    assert "continue-on-error" not in wf  # fully blocking (incl. the checks job)
    assert "open-pull-requests-limit: 0" not in _deps(root)  # full version updates


def test_none_is_informational(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["python"], existing_project=True, adoption="none")
    wf = _wf(root)
    assert "adoption=none: informational" in wf  # quality job runs but never fails
    assert "DIFF_BASE" not in wf  # whole repo (informational)
    assert "open-pull-requests-limit: 0" in _deps(root)  # security-only


def test_fresh_repo_is_full_regardless(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["python"])  # existing_project defaults False
    assert "DIFF_BASE" not in _wf(root)
    assert "open-pull-requests-limit: 0" not in _deps(root)
