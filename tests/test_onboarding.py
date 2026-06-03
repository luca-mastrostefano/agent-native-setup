"""ONBOARDING.md: a one-time, self-deleting first-run runbook + the /onboard command."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_setup import cli
from ai_setup.config import WizardConfig
from ai_setup.scaffold import Scaffolder


def _build(tmp_path: Path, **overrides: object) -> Path:
    config = WizardConfig(project_name="demo", output_dir=tmp_path, init_git=False, **overrides)
    cli.build(config, Scaffolder(config.target))
    return tmp_path


def _onboarding(tmp_path: Path, **overrides: object) -> str:
    return (_build(tmp_path, languages=["python"], **overrides) / "ONBOARDING.md").read_text(
        encoding="utf-8"
    )


def test_generated_with_the_essentials(tmp_path: Path) -> None:
    body = _onboarding(tmp_path)
    assert "First-run setup" in body
    assert "Read **AGENTS.md**" in body
    assert "Delete this file" in body  # self-deleting bootstrap, not a standing doc


def test_not_generated_without_quality_or_ci(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["python"], include_quality=False, include_ci=False)
    assert not (root / "ONBOARDING.md").exists()


def test_runner_reflected_in_commands(tmp_path: Path) -> None:
    assert "make quality" in _onboarding(tmp_path / "m", runner="make")
    assert "task quality" in _onboarding(tmp_path / "t", runner="task")


def test_install_uses_pre_commit_for_existing_runner(tmp_path: Path) -> None:
    assert "pre-commit install" in _onboarding(tmp_path, existing_runner=True)


def test_install_step_notes_pre_commit_prerequisite(tmp_path: Path) -> None:
    # `{runner} install` runs `pre-commit install`, which needs the binary present —
    # the runbook must be self-sufficient about that (the summary no longer says it).
    assert "pipx install" in _onboarding(tmp_path)


def test_full_adoption_baselines_blame_ignore(tmp_path: Path) -> None:
    body = _onboarding(tmp_path, existing_project=True, adoption="full")
    assert ".git-blame-ignore-revs" in body


def test_progressive_adoption_grandfathers_without_reformat(tmp_path: Path) -> None:
    body = _onboarding(tmp_path, existing_project=True, adoption="progressive")
    assert "grandfathered" in body
    assert ".git-blame-ignore-revs" not in body  # no repo-wide reformat


def test_existing_runner_points_at_command_surface_not_targets(tmp_path: Path) -> None:
    # We defer to a detected runner and don't generate its targets, so the runbook must
    # not tell the agent to run `make quality`/`make format` — those may not exist.
    body = _onboarding(tmp_path, existing_runner=True, existing_project=True, adoption="full")
    assert "`make quality`" not in body
    assert "`make format`" not in body
    assert "command surface" in body  # points at AGENTS.md instead


def test_ci_verify_step_tracks_ci(tmp_path: Path) -> None:
    assert "gh run watch" in _onboarding(tmp_path / "ci")
    assert "gh run watch" not in _onboarding(tmp_path / "no_ci", include_ci=False)


def test_api_key_step_only_for_claude_with_ci(tmp_path: Path) -> None:
    assert "ANTHROPIC_API_KEY" in _onboarding(tmp_path / "c", ai_tools=["claude"])
    assert "ANTHROPIC_API_KEY" not in _onboarding(tmp_path / "x", ai_tools=["cursor"])


def test_onboard_command_scaffolded_for_claude(tmp_path: Path) -> None:
    cmd = (_build(tmp_path, languages=["python"]) / ".claude/commands/onboard.md").read_text(
        encoding="utf-8"
    )
    assert "ONBOARDING.md" in cmd


def test_onboard_command_absent_when_no_onboarding(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["python"], include_quality=False, include_ci=False)
    assert not (root / ".claude/commands/onboard.md").exists()


def test_header_frames_first_run_for_an_agent(tmp_path: Path) -> None:
    body = _onboarding(tmp_path)
    assert "scaffolded by the `ai-setup` wizard" in body
    assert "AI assistant" in body  # speaks to the agent waking up here


def test_cleanup_removes_banner_when_injected(tmp_path: Path) -> None:
    with_banner = _onboarding(tmp_path / "b", first_run_banner=True)
    assert "remove the first-run banner" in with_banner
    without = _onboarding(tmp_path / "n", first_run_banner=False)
    assert "remove the first-run banner" not in without


def test_banner_injected_into_agents_md(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["python"], first_run_banner=True)
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "ai-setup:first-run" in agents  # the removable, delimited block
    assert "complete [`ONBOARDING.md`]" in agents


def test_no_banner_without_flag_or_without_onboarding(tmp_path: Path) -> None:
    off = _build(tmp_path / "off", languages=["python"], first_run_banner=False) / "AGENTS.md"
    assert "ai-setup:first-run" not in off.read_text(encoding="utf-8")
    # Flag on but no tooling -> no ONBOARDING.md -> banner would dangle, so it's suppressed.
    bare = (
        _build(
            tmp_path / "bare",
            languages=["python"],
            first_run_banner=True,
            include_quality=False,
            include_ci=False,
        )
        / "AGENTS.md"
    )
    assert "ai-setup:first-run" not in bare.read_text(encoding="utf-8")


def test_banner_suppressed_without_an_ai_tool(tmp_path: Path) -> None:
    # Nothing auto-loads AGENTS.md without a targeted tool, so the banner would be inert —
    # and the runbook must not tell the agent to remove one that was never written.
    root = _build(tmp_path, languages=["python"], ai_tools=[], first_run_banner=True)
    assert "ai-setup:first-run" not in (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "remove the first-run banner" not in (root / "ONBOARDING.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("extra_args", "expected"),
    [
        ([], "AI assistant"),  # banner on (default) -> self-onboard message
        (["--no-first-run-banner"], "/onboard"),  # no banner -> Claude types /onboard
        (["--no-first-run-banner", "--tools", "cursor"], "ONBOARDING.md"),
    ],
)
def test_summary_points_at_first_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    extra_args: list[str],
    expected: str,
) -> None:
    # Banner on -> "open in your AI assistant"; banner off -> /onboard or the file.
    cli.main(["demo", "-o", str(tmp_path), "--no-git", "-y", *extra_args])
    assert expected in capsys.readouterr().out


def test_summary_defers_to_onboarding_without_duplicating_steps(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The runbook owns install + secrets; the summary must not re-list them.
    cli.main(["demo", "-o", str(tmp_path), "--languages", "python", "--no-git", "-y"])
    out = capsys.readouterr().out
    assert "ONBOARDING.md" in out  # points at the runbook
    assert "pipx install" not in out  # install lives in ONBOARDING.md now
    assert "ANTHROPIC_API_KEY" not in out  # so does the secret
