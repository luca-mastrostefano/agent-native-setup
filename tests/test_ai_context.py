"""Contract generation: never clobber a pre-existing AGENTS.md / CLAUDE.md."""

from __future__ import annotations

from pathlib import Path

from agent_native_setup.config import WizardConfig
from agent_native_setup.generators import ai_context
from agent_native_setup.scaffold import Scaffolder


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


def test_contract_states_testing_expectation(tmp_path: Path) -> None:
    body = _run(tmp_path).read_text(encoding="utf-8")
    assert "ships with the test that proves it" in body
    assert "Regression" in body  # bug -> reproducing test, named explicitly


def test_contract_pushes_test_quality(tmp_path: Path) -> None:
    # Beyond "ships with a test": steer toward meaningful, edge-case tests, not coverage theater.
    body = _run(tmp_path).read_text(encoding="utf-8")
    assert "prove behavior" in body
    assert "error paths" in body
    assert "can't fail isn't worth writing" in body


def test_contract_covers_uncovered_languages(tmp_path: Path) -> None:
    body = _run(tmp_path).read_text(encoding="utf-8")
    assert "isn't yet wired up" in body  # framed by repo state, not "what the setup did"


def test_contract_verify_ci_run_when_ci(tmp_path: Path) -> None:
    # _run defaults to CI on -> the "check the real run" line is present.
    assert "gh run watch" in _run(tmp_path).read_text(encoding="utf-8")


def test_nav_links_security_policy_when_scaffolded(tmp_path: Path) -> None:
    # _run defaults to security on -> the Navigation table points at SECURITY.md.
    assert "SECURITY.md" in _run(tmp_path).read_text(encoding="utf-8")


def test_contract_self_review_when_agents(tmp_path: Path) -> None:
    # _run defaults to agents on -> the contract wires in the code-reviewer (/review).
    assert "/review" in _run(tmp_path).read_text(encoding="utf-8")


def test_contract_routes_to_security_review_for_claude(tmp_path: Path) -> None:
    # `/security-review` is a Claude Code built-in: point at it for Claude targets, with a
    # surface-based trigger so it isn't busywork — but never for a non-Claude target.
    claude = _run(tmp_path / "c").read_text(encoding="utf-8")
    assert "/security-review" in claude
    # The smart trigger names the sensitive surfaces (not "review everything"); assert one
    # of them so a reworded sentence that drops the scoping is caught.
    assert "untrusted input" in claude
    assert "/security-review" not in _run(tmp_path / "x", ai_tools=["cursor"]).read_text(
        encoding="utf-8"
    )


def test_contract_warns_about_staging(tmp_path: Path) -> None:
    # The commit-ships-the-index gotcha that bites agents after acting on review.
    assert "staged index" in _run(tmp_path).read_text(encoding="utf-8")


def test_contract_wants_followable_processes(tmp_path: Path) -> None:
    # Long/background commands must stream progress, not buffer silently (a common pain).
    body = _run(tmp_path).read_text(encoding="utf-8")
    assert "followable" in body
    assert "buffering silently" in body


def test_contract_scopes_context_down_as_repo_grows(tmp_path: Path) -> None:
    # As the repo grows, push detail into scoped files instead of one sprawling contract:
    # nearest-wins nested contracts + per-subsystem architecture docs.
    body = _run(tmp_path).read_text(encoding="utf-8")
    assert "nearest contract" in body  # the nested-contract (nearest-wins) convention
    assert "docs/architecture/<name>.md" in body  # split architecture per-subsystem
    # The nested file needs a CLAUDE.md symlink for Claude (it won't read a bare nested
    # AGENTS.md) — and that nugget is Claude-specific, so it's gated to Claude targets.
    assert "symlink beside it" in body
    cursor = _run(tmp_path / "cur", ai_tools=["cursor"]).read_text(encoding="utf-8")
    assert "nearest contract" in cursor  # the convention applies to any tool
    assert "symlink beside it" not in cursor  # but the Claude-only symlink note is gated out
    # The docs gate is pinned both ways: a docs-off contract drops the architecture clause
    # but keeps the (docs-independent) nested-contract convention.
    nodocs_cfg = WizardConfig(
        project_name="demo",
        output_dir=tmp_path / "nodocs",
        languages=[],
        ai_tools=["claude"],
        include_docs=False,
    )
    ai_context.generate(nodocs_cfg, Scaffolder(nodocs_cfg.target))
    nodocs = (tmp_path / "nodocs" / "AGENTS.md").read_text(encoding="utf-8")
    assert "docs/architecture/<name>.md" not in nodocs
    assert "nearest contract" in nodocs


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


def test_gemini_target_symlinks_gemini_md_to_agents(tmp_path: Path) -> None:
    # GEMINI.md is a symlink to AGENTS.md, exactly like CLAUDE.md (Gemini loads GEMINI.md).
    agents = _run(tmp_path, ai_tools=["gemini"])
    gemini = tmp_path / "GEMINI.md"
    assert gemini.is_symlink()
    assert gemini.resolve() == agents.resolve()
    assert not (tmp_path / "CLAUDE.md").exists()  # claude not targeted
    body = agents.read_text(encoding="utf-8")
    assert "Gemini loads `GEMINI.md`" in body  # the nested-contract note is Gemini-aware


def test_no_gemini_md_when_gemini_not_targeted(tmp_path: Path) -> None:
    _run(tmp_path, ai_tools=["claude"])
    assert not (tmp_path / "GEMINI.md").exists()


def test_absorbs_real_gemini_md_then_symlinks(tmp_path: Path) -> None:
    (tmp_path / "GEMINI.md").write_text("# Legacy GEMINI\n\nUse spaces.\n")
    agents = _run(tmp_path, ai_tools=["gemini"])
    body = agents.read_text(encoding="utf-8")
    assert "<!-- Preserved from your original GEMINI.md -->" in body
    assert "Use spaces." in body
    gemini = tmp_path / "GEMINI.md"
    assert gemini.is_symlink()
    assert gemini.resolve() == agents.resolve()


def test_both_symlink_tools_listed_when_claude_and_gemini(tmp_path: Path) -> None:
    body = _run(tmp_path, ai_tools=["claude", "gemini"]).read_text(encoding="utf-8")
    assert "`CLAUDE.md`, `GEMINI.md`," in body  # the pointer line lists both
    assert "`CLAUDE.md`/`GEMINI.md` symlink beside it" in body  # nested note lists both
    assert "those tools load their own file" in body
