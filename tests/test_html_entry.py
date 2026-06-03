"""The html language entry: HTMLHint markup lint + lychee link/resource check."""

from __future__ import annotations

from pathlib import Path

from ai_setup import cli
from ai_setup.config import WizardConfig
from ai_setup.languages import detect_languages
from ai_setup.scaffold import Scaffolder


def _build(tmp_path: Path, **overrides: object) -> Path:
    config = WizardConfig(project_name="demo", output_dir=tmp_path, init_git=False, **overrides)
    cli.build(config, Scaffolder(config.target))
    return tmp_path


def test_html_detected_by_extension(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html></html>\n")
    assert detect_languages(tmp_path) == ["html"]


def test_greenfield_html_scaffolds_htmlhint_and_lychee(tmp_path: Path) -> None:
    _build(tmp_path, languages=["html"])
    assert (tmp_path / ".htmlhintrc").exists()
    pc = (tmp_path / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "id: htmlhint" in pc
    assert "id: lychee" in pc
    assert "--offline" in pc  # link check stays offline / local-file only
    wf = (tmp_path / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    assert "lycheeverse/lychee-action@v2" in wf
    assert "htmlhint" in wf


def test_htmlhint_is_pinned_not_floating(tmp_path: Path) -> None:
    # `npx --yes htmlhint` floats to latest; pin it so CI/local are reproducible.
    root = _build(tmp_path, languages=["html"])
    wf = (root / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    mk = (root / "Makefile").read_text(encoding="utf-8")
    assert "htmlhint@1.1.4" in wf
    assert "htmlhint@1.1.4" in mk
    assert 'htmlhint "**/*.html"' not in wf  # no bare, unpinned invocation


def test_lychee_binary_install_is_documented(tmp_path: Path) -> None:
    # The lychee hook is language:system (needs the binary on PATH), so a fresh clone
    # can't commit until it's installed — README + ONBOARDING must flag it.
    root = _build(tmp_path, languages=["html"])
    readme = (root / "README.md").read_text(encoding="utf-8")
    onboarding = (root / "ONBOARDING.md").read_text(encoding="utf-8")
    assert "lychee" in readme and "install lychee" in readme
    assert "install lychee" in onboarding
    # A project without html says nothing about lychee.
    plain = (_build(tmp_path / "p", languages=["python"]) / "README.md").read_text(encoding="utf-8")
    assert "lychee" not in plain


def test_existing_html_ratchets_to_changed_files(tmp_path: Path) -> None:
    _build(tmp_path, languages=["html"], existing_project=True)
    wf = (tmp_path / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    assert "DIFF_BASE" in wf
    assert "steps.html.outputs.files" in wf
    assert "lycheeverse/lychee-action@v2" in wf
