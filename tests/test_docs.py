"""docs/improvements.md tells the agent to stamp each entry (commit + date, or date if no git)."""

from __future__ import annotations

from pathlib import Path

from agent_native_setup.config import WizardConfig
from agent_native_setup.generators import docs
from agent_native_setup.scaffold import Scaffolder


def _improvements(tmp_path: Path, *, init_git: bool) -> str:
    config = WizardConfig(project_name="demo", output_dir=tmp_path, init_git=init_git)
    docs.generate(config, Scaffolder(config.target))
    return (tmp_path / "docs/improvements.md").read_text(encoding="utf-8")


def test_rfc_lifecycle_folders_and_adopt_rfc_land_in_active(tmp_path: Path) -> None:
    # The lifecycle is proposed → active → (superseded | retired); the adopt RFC is an
    # in-effect decision, so it's written Active, into active/ (not the old current/).
    config = WizardConfig(project_name="demo", output_dir=tmp_path, init_git=False)
    docs.generate(config, Scaffolder(config.target))
    rfc = tmp_path / "docs/rfc"
    assert sorted(p.name for p in rfc.iterdir() if p.is_dir()) == [
        "active",
        "proposed",
        "retired",
        "superseded",
    ]
    assert not (rfc / "current").exists() and not (rfc / "done").exists()
    adopt = next((rfc / "active").glob("*-adopt-agent-native-setup.md"))
    body = adopt.read_text(encoding="utf-8")
    assert "- **Status:** Active" in body
    assert "- [ ] Implemented" in body  # implementation is a checkbox, not a state


def test_improvements_stamps_each_entry_with_commit_and_date_in_a_git_repo(tmp_path: Path) -> None:
    body = _improvements(tmp_path, init_git=True)
    assert "git rev-parse --short HEAD" in body  # anchor to the commit you're at
    assert "[a1b2c3d · YYYY-MM-DD]" in body  # seed models the commit · date format
    assert "today's date" in body  # the header asks for the date too


def test_improvements_falls_back_to_date_only_without_git(tmp_path: Path) -> None:
    # init_git=False and no existing .git -> the project won't be a git repo, so there's no
    # commit to anchor to; stamp with the date alone.
    body = _improvements(tmp_path, init_git=False)
    assert "[YYYY-MM-DD]" in body
    assert "git rev-parse" not in body  # no commit form
    assert " · " not in body  # no commit·date separator in the date-only form


def test_improvements_points_at_the_runner_target_when_one_is_generated(tmp_path: Path) -> None:
    # With a generated runner, the header names the `improvement` target so agents use
    # it instead of re-deriving the stamp format; without one there's nothing to name.
    body = _improvements(tmp_path / "a", init_git=True)  # default: quality on, make
    assert 'make improvement TEXT="<idea>"' in body
    for sub, overrides in (
        ("b", {"include_quality": False}),  # no quality -> no runner file at all
        ("c", {"existing_runner": True}),  # their runner -> we never wrote the target
    ):
        config = WizardConfig(
            project_name="demo", output_dir=tmp_path / sub, init_git=True, **overrides
        )
        docs.generate(config, Scaffolder(config.target))
        body = (tmp_path / sub / "docs/improvements.md").read_text(encoding="utf-8")
        assert "make improvement" not in body and "task improvement" not in body
