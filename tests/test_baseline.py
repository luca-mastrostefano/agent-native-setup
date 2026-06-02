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


def test_dependabot_security_only_for_existing_repo(tmp_path: Path) -> None:
    fresh = (_build(tmp_path / "fresh", languages=["python"]) / ".github/dependabot.yml").read_text(
        encoding="utf-8"
    )
    legacy = (
        _build(tmp_path / "legacy", languages=["python"], existing_project=True)
        / ".github/dependabot.yml"
    ).read_text(encoding="utf-8")
    assert "open-pull-requests-limit: 0" not in fresh  # fresh repo: full version updates
    assert "open-pull-requests-limit: 0" in legacy  # existing repo: security-only, no flood


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


def test_gitignore_ignores_claude_local_settings(tmp_path: Path) -> None:
    gi = (_build(tmp_path, languages=["python"]) / ".gitignore").read_text(encoding="utf-8")
    assert ".claude/settings.local.json" in gi  # claude is in the default ai_tools


def test_existing_gitignore_never_overwritten_even_with_force(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("my-custom/\n")
    config = WizardConfig(
        project_name="demo", output_dir=tmp_path, init_git=False, languages=["python"]
    )
    cli.build(config, Scaffolder(config.target, force=True))  # force must not clobber it
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == "my-custom/\n"


def test_node_and_html_set_up_node_once(tmp_path: Path) -> None:
    wf = (_build(tmp_path, languages=["node", "html"]) / ".github/workflows/quality.yml").read_text(
        encoding="utf-8"
    )
    quality_job = wf.split("  checks:")[0]  # the checks job sets up node separately
    assert quality_job.count("actions/setup-node@") == 1  # deduped — not once per language


def test_actionlint_hook_only_with_github_actions(tmp_path: Path) -> None:
    with_ga = (_build(tmp_path / "ga", languages=["python"]) / ".pre-commit-config.yaml").read_text(
        encoding="utf-8"
    )
    without_ga = (
        _build(tmp_path / "no_ga", languages=["python"], use_github_actions=False)
        / ".pre-commit-config.yaml"
    ).read_text(encoding="utf-8")
    assert "actionlint" in with_ga
    assert "actionlint" not in without_ga
