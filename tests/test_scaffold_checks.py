"""The wizard scaffolds the RFC/docs commit-msg gates — for Python projects only."""

from __future__ import annotations

from pathlib import Path

from ai_setup import cli
from ai_setup.config import WizardConfig
from ai_setup.generators import docs
from ai_setup.scaffold import Scaffolder

REPO_ROOT = Path(__file__).resolve().parents[1]


def _build(tmp_path: Path, **overrides: object) -> Path:
    config = WizardConfig(project_name="demo", output_dir=tmp_path, init_git=False, **overrides)
    cli.build(config, Scaffolder(config.target))
    return tmp_path


def test_python_project_scaffolds_commit_msg_gates(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["python"])
    assert (root / "tools/checks/rfc_needed.py").exists()
    assert (root / "tools/checks/docs_sync.py").exists()
    cfg = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "commit-msg" in cfg.splitlines()[0]  # in default_install_hook_types
    assert "id: rfc-needed" in cfg
    assert "id: docs-sync" in cfg


def test_non_python_project_omits_commit_msg_gates(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["go"])
    assert not (root / "tools/checks/rfc_needed.py").exists()
    assert not (root / "tools/checks/docs_sync.py").exists()
    cfg = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "commit-msg" not in cfg
    assert "docs-sync" not in cfg


def test_no_docs_omits_commit_msg_gates(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["python"], include_docs=False)
    assert not (root / "tools/checks/rfc_needed.py").exists()
    cfg = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "commit-msg" not in cfg


def test_code_reviewer_has_docs_check_with_docs(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["python"])
    assert "Docs in sync" in (root / ".claude/agents/code-reviewer.md").read_text(encoding="utf-8")


def test_code_reviewer_omits_docs_check_without_docs(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["python"], include_docs=False)
    body = (root / ".claude/agents/code-reviewer.md").read_text(encoding="utf-8")
    assert "Docs in sync" not in body
    assert "4. Goal-driven" in body  # the other checks survive


def test_embedded_scripts_match_repo_files() -> None:
    """The wizard ships exactly the scripts this repo dogfoods and tests."""
    assert docs.RFC_NEEDED == (REPO_ROOT / "tools/checks/rfc_needed.py").read_text(encoding="utf-8")
    assert docs.DOCS_SYNC == (REPO_ROOT / "tools/checks/docs_sync.py").read_text(encoding="utf-8")


def test_sync_rfc_status_stays_under_default_line_length(tmp_path: Path) -> None:
    # sync_rfc_status.py ships even for non-Python projects, where no line-length=100
    # config is present — keep it <=88 cols so a default ruff/flake8 won't flag it.
    root = _build(tmp_path, languages=["node"])  # node project: no Python tooling shipped
    body = (root / "tools/checks/sync_rfc_status.py").read_text(encoding="utf-8")
    too_long = [line for line in body.splitlines() if len(line) > 88]
    assert not too_long, f"lines over 88 cols: {too_long}"
