"""The engineering-baseline files the wizard scaffolds (editorconfig, dependabot, etc.)."""

from __future__ import annotations

from pathlib import Path

from ai_setup import cli
from ai_setup.config import WizardConfig
from ai_setup.scaffold import Scaffolder


def _build(tmp_path: Path, **overrides: object) -> Path:
    config = WizardConfig(project_name="demo", output_dir=tmp_path, init_git=False, **overrides)
    cli.build(config, Scaffolder(config.target))
    return tmp_path


def test_editorconfig_and_gitattributes(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["python"])
    assert "root = true" in (root / ".editorconfig").read_text(encoding="utf-8")
    assert (root / ".gitattributes").read_text(encoding="utf-8").strip() == "* text=auto"


def test_dependabot_has_actions_and_language_ecosystems(tmp_path: Path) -> None:
    db = (_build(tmp_path, languages=["python", "go"]) / ".github/dependabot.yml").read_text(
        encoding="utf-8"
    )
    assert "github-actions" in db
    assert "pip" in db
    assert "gomod" in db


def test_pr_template_present(tmp_path: Path) -> None:
    assert (_build(tmp_path, languages=["python"]) / ".github/PULL_REQUEST_TEMPLATE.md").exists()


def test_ci_least_privilege_permissions(tmp_path: Path) -> None:
    wf = (_build(tmp_path, languages=["python"]) / ".github/workflows/quality.yml").read_text(
        encoding="utf-8"
    )
    assert "permissions:" in wf
    assert "contents: read" in wf


def test_security_md_present_with_security(tmp_path: Path) -> None:
    assert (_build(tmp_path, languages=["python"]) / "SECURITY.md").exists()


def test_security_md_omitted_without_security(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["python"], include_security=False)
    assert not (root / "SECURITY.md").exists()


def test_no_github_actions_omits_github_files(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["python"], use_github_actions=False)
    assert not (root / ".github/dependabot.yml").exists()
    assert not (root / ".github/PULL_REQUEST_TEMPLATE.md").exists()
