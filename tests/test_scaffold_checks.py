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


def test_non_python_project_guards_shipped_python_with_ruff(tmp_path: Path) -> None:
    # docs ship tools/checks/*.py even for a node project; guard them with ruff at all
    # three layers (pre-commit, command surface, CI) so they don't ship unlinted.
    root = _build(tmp_path, languages=["node"])
    pc = (root / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    mk = (root / "Makefile").read_text(encoding="utf-8")
    wf = (root / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    assert "ruff-check" in pc and "^tools/.*\\.py$" in pc  # scoped pre-commit hook
    assert "ruff check tools/" in mk and "ruff format --check tools/" in mk  # local gate
    assert "ruff check tools/" in wf  # CI matches local
    assert "__pycache__/" in (root / ".gitignore").read_text(encoding="utf-8")


def test_python_project_does_not_double_guard(tmp_path: Path) -> None:
    # When Python IS selected its own ruff covers tools/; don't add the scoped guard.
    mk = (_build(tmp_path, languages=["python"]) / "Makefile").read_text(encoding="utf-8")
    assert "ruff check ." in mk
    assert "ruff check tools/" not in mk


def test_architecture_overview_preseeds_tooling(tmp_path: Path) -> None:
    # The wizard knows the components it built; seed them instead of a bare TODO.
    body = (_build(tmp_path, languages=["node"]) / "docs/architecture/overview.md").read_text(
        encoding="utf-8"
    )
    assert "Tooling & process" in body
    assert "`AGENTS.md`" in body and "`tools/checks/`" in body
    assert "CI" in body  # ci is on by default
    assert "TODO" in body  # product components still left to the team


def test_ruff_precommit_uses_current_id(tmp_path: Path) -> None:
    # ruff-pre-commit renamed `ruff` -> `ruff-check`; `ruff` is a legacy alias.
    pc = (_build(tmp_path, languages=["python"]) / ".pre-commit-config.yaml").read_text(
        encoding="utf-8"
    )
    assert "id: ruff-check" in pc
    assert "id: ruff\n" not in pc  # no bare legacy alias


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
