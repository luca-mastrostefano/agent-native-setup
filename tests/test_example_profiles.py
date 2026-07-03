"""The committed example profiles under examples/profiles/ must stay valid and scaffoldable, so
they can't rot into broken copy-paste starting points."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_native_setup import cli

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "profiles"


def _example_dirs() -> list[Path]:
    return sorted(p.parent for p in EXAMPLES.glob("*/profile.json"))


def test_there_is_at_least_one_example() -> None:
    assert _example_dirs(), f"no example profiles under {EXAMPLES}"


@pytest.mark.parametrize("profile_dir", _example_dirs(), ids=lambda p: p.name)
def test_example_profile_validates(profile_dir: Path) -> None:
    assert cli.main(["profile", "validate", str(profile_dir)]) == 0


def test_example_team_scaffolds_and_renders(tmp_path: Path) -> None:
    target = tmp_path / "out"
    rc = cli.main(
        ["demo", "-o", str(target), "-y", "--no-git", "--profile", str(EXAMPLES / "example-team")]
    )
    assert rc == 0
    conventions = (target / "docs/conventions.md").read_text(encoding="utf-8")
    assert "# demo — team conventions" in conventions  # project_name rendered
    assert "**standard**" in conventions  # the `tier` prompt's default (-y) rendered via answers
    assert (target / "docs/team-notes.md").exists()  # seed file shipped
    assert (target / ".claude/agents/example-reviewer.md").exists()  # house agent shipped
