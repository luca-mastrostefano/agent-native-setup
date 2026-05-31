"""Contract generation: never clobber a pre-existing AGENTS.md / CLAUDE.md."""

from __future__ import annotations

from pathlib import Path

from ai_setup.config import WizardConfig
from ai_setup.generators import ai_context
from ai_setup.scaffold import Scaffolder


def _run(tmp_path: Path, *, ai_tools: list[str] | None = None) -> Path:
    config = WizardConfig(
        project_name="demo",
        output_dir=tmp_path,
        languages=[],
        ai_tools=["claude"] if ai_tools is None else ai_tools,
    )
    ai_context.generate(config, Scaffolder(config.target))
    return tmp_path / "AGENTS.md"


def test_fresh_write_has_no_preserved_block(tmp_path: Path) -> None:
    agents = _run(tmp_path)
    body = agents.read_text(encoding="utf-8")
    assert "Agent Contract" in body
    assert "Preserved from your original" not in body


def test_merges_existing_agents_md(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# House rules\n\nAlways rebase.\n")
    body = _run(tmp_path).read_text(encoding="utf-8")
    # Wizard contract comes first, original content preserved below the divider.
    assert body.index("Agent Contract") < body.index("House rules")
    assert "<!-- Preserved from your original AGENTS.md -->" in body
    assert "Always rebase." in body


def test_absorbs_real_claude_md_then_symlinks(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("# Legacy CLAUDE\n\nUse tabs.\n")
    agents = _run(tmp_path)
    body = agents.read_text(encoding="utf-8")
    assert "<!-- Preserved from your original CLAUDE.md -->" in body
    assert "Use tabs." in body
    claude = tmp_path / "CLAUDE.md"
    assert claude.is_symlink()
    assert claude.resolve() == agents.resolve()


def test_empty_existing_file_is_not_preserved(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("   \n")
    body = _run(tmp_path).read_text(encoding="utf-8")
    assert "Preserved from your original" not in body
