"""Contract generation: the AGENTS.md (map) / INSTRUCTION.md (standard) split, and the
non-destructive fold-in of a pre-existing AGENTS.md / CLAUDE.md."""

from __future__ import annotations

from pathlib import Path

from agent_native_setup.config import WizardConfig
from agent_native_setup.generators import ai_context
from agent_native_setup.scaffold import Scaffolder


def _build(tmp_path: Path, *, ai_tools: list[str] | None = None, **overrides: object) -> None:
    config = WizardConfig(
        project_name="demo",
        output_dir=tmp_path,
        languages=[],
        ai_tools=["claude"] if ai_tools is None else ai_tools,
        **overrides,
    )
    ai_context.generate(config, Scaffolder(config.target))


def _agents(tmp_path: Path, **kw: object) -> str:
    """The thin AGENTS.md (project map)."""
    _build(tmp_path, **kw)
    return (tmp_path / "AGENTS.md").read_text(encoding="utf-8")


def _contract(tmp_path: Path, **kw: object) -> str:
    """The full contract a tool sees: AGENTS.md plus the standard principles it points at,
    which now live in INSTRUCTION.md."""
    _build(tmp_path, **kw)
    return (
        (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
        + "\n"
        + (tmp_path / "INSTRUCTION.md").read_text(encoding="utf-8")
    )


# --- the AGENTS.md / INSTRUCTION.md split ---------------------------------------


def test_agents_md_is_a_thin_map_pointing_at_instruction(tmp_path: Path) -> None:
    agents = _agents(tmp_path)
    assert "Agent Contract" in agents  # title + project map
    assert "Read [`INSTRUCTION.md`](./INSTRUCTION.md) first" in agents
    assert "@INSTRUCTION.md" in agents  # the Claude import
    # The standard principles moved out — AGENTS.md no longer carries them.
    assert "Think Before Coding" not in agents
    assert "ships with the test that proves it" not in agents


def test_instruction_holds_the_standard_principles(tmp_path: Path) -> None:
    _build(tmp_path)
    instruction = (tmp_path / "INSTRUCTION.md").read_text(encoding="utf-8")
    assert "Engineering contract" in instruction
    for principle in (
        "Think Before Coding",
        "Simplicity First",
        "Surgical Changes",
        "Goal-Driven Execution",
    ):
        assert principle in instruction


def test_instruction_import_is_claude_only(tmp_path: Path) -> None:
    # The `@INSTRUCTION.md` import is a Claude Code feature; a Cursor-only project still gets
    # the prose pointer, but not the bare import line (which other tools would show literally).
    cursor = _agents(tmp_path / "cur", ai_tools=["cursor"])
    assert "INSTRUCTION.md" in cursor  # the prose pointer is portable
    assert "@INSTRUCTION.md" not in cursor


# --- the standard principles (now in INSTRUCTION.md) ----------------------------


def test_contract_states_testing_expectation(tmp_path: Path) -> None:
    body = _contract(tmp_path)
    assert "ships with the test that proves it" in body
    assert "Regression" in body  # bug -> reproducing test, named explicitly


def test_contract_pushes_test_quality(tmp_path: Path) -> None:
    # Beyond "ships with a test": steer toward meaningful, edge-case tests, not coverage theater.
    body = _contract(tmp_path)
    assert "prove behavior" in body
    assert "error paths" in body
    assert "can't fail isn't worth writing" in body


def test_contract_covers_uncovered_languages(tmp_path: Path) -> None:
    assert "isn't yet wired up" in _contract(tmp_path)  # framed by repo state


def test_contract_verify_ci_run_when_ci(tmp_path: Path) -> None:
    assert "gh run watch" in _contract(tmp_path)  # the "check the real run" line


def test_nav_links_security_policy_when_scaffolded(tmp_path: Path) -> None:
    # Security on -> the Navigation table (in AGENTS.md) points at SECURITY.md.
    assert "SECURITY.md" in _agents(tmp_path)


def test_contract_self_review_when_agents(tmp_path: Path) -> None:
    assert "/review" in _contract(tmp_path)  # wires in the code-reviewer


def test_contract_routes_to_security_review_for_claude(tmp_path: Path) -> None:
    # `/security-review` is a Claude Code built-in: point at it for Claude targets, with a
    # surface-based trigger so it isn't busywork — but never for a non-Claude target.
    claude = _contract(tmp_path / "c")
    assert "/security-review" in claude
    assert "untrusted input" in claude  # the scoping survives, not "review everything"
    assert "/security-review" not in _contract(tmp_path / "x", ai_tools=["cursor"])


def test_contract_warns_about_staging(tmp_path: Path) -> None:
    assert "staged index" in _contract(tmp_path)  # the commit-ships-the-index gotcha


def test_contract_wants_followable_processes(tmp_path: Path) -> None:
    body = _contract(tmp_path)
    assert "followable" in body
    assert "buffering silently" in body


def test_contract_scopes_context_down_as_repo_grows(tmp_path: Path) -> None:
    body = _contract(tmp_path)
    assert "nearest contract" in body  # the nested-contract (nearest-wins) convention
    assert "docs/architecture/<name>.md" in body  # split architecture per-subsystem
    assert "symlink beside it" in body  # the Claude-only nested-symlink note
    cursor = _contract(tmp_path / "cur", ai_tools=["cursor"])
    assert "nearest contract" in cursor  # the convention applies to any tool
    assert "symlink beside it" not in cursor  # but the Claude-only symlink note is gated out
    # docs-off drops the architecture clause but keeps the nested-contract convention.
    nodocs = _contract(tmp_path / "nodocs", include_docs=False)
    assert "docs/architecture/<name>.md" not in nodocs
    assert "nearest contract" in nodocs


# --- non-destructive fold-in + symlinks -----------------------------------------


def test_fresh_write_has_no_preserved_block(tmp_path: Path) -> None:
    agents = _agents(tmp_path)
    assert "Preserved from your original" not in agents


def test_merges_existing_agents_md(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# House rules\n\nAlways rebase.\n")
    body = _agents(tmp_path)
    # Wizard contract comes first, original content preserved below the divider.
    assert body.index("Agent Contract") < body.index("House rules")
    assert "<!-- Preserved from your original AGENTS.md -->" in body
    assert "Always rebase." in body
    # The split survives the fold-in: the INSTRUCTION.md pointer stays at the top, and
    # INSTRUCTION.md is still written alongside (the path the RFC flags as messiest).
    assert "@INSTRUCTION.md" in body
    assert body.index("@INSTRUCTION.md") < body.index("House rules")
    assert (tmp_path / "INSTRUCTION.md").read_text(encoding="utf-8").startswith(
        "# Engineering contract"
    )


def test_absorbs_real_claude_md_then_symlinks(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("# Legacy CLAUDE\n\nUse tabs.\n")
    _build(tmp_path)
    body = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "<!-- Preserved from your original CLAUDE.md -->" in body
    assert "Use tabs." in body
    claude = tmp_path / "CLAUDE.md"
    assert claude.is_symlink()
    assert claude.resolve() == (tmp_path / "AGENTS.md").resolve()


def test_empty_existing_file_is_not_preserved(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("   \n")
    assert "Preserved from your original" not in _agents(tmp_path)


def test_gemini_target_symlinks_gemini_md_to_agents(tmp_path: Path) -> None:
    # GEMINI.md is a symlink to AGENTS.md, exactly like CLAUDE.md (Gemini loads GEMINI.md).
    contract = _contract(tmp_path, ai_tools=["gemini"])
    gemini = tmp_path / "GEMINI.md"
    assert gemini.is_symlink()
    assert gemini.resolve() == (tmp_path / "AGENTS.md").resolve()
    assert not (tmp_path / "CLAUDE.md").exists()  # claude not targeted
    assert "Gemini loads `GEMINI.md`" in contract  # the nested-contract note is Gemini-aware


def test_no_gemini_md_when_gemini_not_targeted(tmp_path: Path) -> None:
    _build(tmp_path, ai_tools=["claude"])
    assert not (tmp_path / "GEMINI.md").exists()


def test_absorbs_real_gemini_md_then_symlinks(tmp_path: Path) -> None:
    (tmp_path / "GEMINI.md").write_text("# Legacy GEMINI\n\nUse spaces.\n")
    _build(tmp_path, ai_tools=["gemini"])
    body = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "<!-- Preserved from your original GEMINI.md -->" in body
    assert "Use spaces." in body
    gemini = tmp_path / "GEMINI.md"
    assert gemini.is_symlink()
    assert gemini.resolve() == (tmp_path / "AGENTS.md").resolve()


def test_both_symlink_tools_listed_when_claude_and_gemini(tmp_path: Path) -> None:
    _build(tmp_path, ai_tools=["claude", "gemini"])
    agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    instruction = (tmp_path / "INSTRUCTION.md").read_text(encoding="utf-8")
    assert "`CLAUDE.md`, `GEMINI.md`," in agents  # the pointer line lists both
    assert "`CLAUDE.md`/`GEMINI.md` symlink beside it" in instruction  # nested note lists both
    assert "those tools load their own file" in instruction
