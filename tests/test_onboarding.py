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


def test_recon_step_scopes_the_reading(tmp_path: Path) -> None:
    # Don't burn time pre-reading the whole repo — AGENTS.md + the runbook are enough.
    assert "pre-read the whole repo" in _onboarding(tmp_path)


def test_cleanup_commit_skips_a_second_ci_watch(tmp_path: Path) -> None:
    # The final cleanup commit only deletes setup scaffolding; making the agent wait on CI
    # for it is a wasted round-trip. The one CI watch stays on the first push (step 8).
    assert "no CI watch is needed" in _onboarding(tmp_path / "ci")
    assert "no CI watch is needed" not in _onboarding(tmp_path / "no_ci", include_ci=False)


def test_runner_reflected_in_commands(tmp_path: Path) -> None:
    assert "make quality" in _onboarding(tmp_path / "m", runner="make")
    assert "task quality" in _onboarding(tmp_path / "t", runner="task")


def test_install_uses_pre_commit_for_existing_runner(tmp_path: Path) -> None:
    assert "pre-commit install" in _onboarding(tmp_path, existing_runner=True)


def test_install_step_notes_pre_commit_prerequisite(tmp_path: Path) -> None:
    # `{runner} install` runs `pre-commit install`, which needs the binary present —
    # the runbook must be self-sufficient about that (the summary no longer says it).
    assert "pipx install" in _onboarding(tmp_path)


def test_install_step_offers_a_pipx_alternative(tmp_path: Path) -> None:
    # Don't assume pipx is the only installer for pre-commit — it isn't always present
    # (a real onboarding hit this). Offer pip as a fallback.
    body = _onboarding(tmp_path)
    assert "pipx install pre-commit" in body
    assert "pip install pre-commit" in body


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


def test_runbook_has_commit_and_push_step(tmp_path: Path) -> None:
    # The agent shouldn't have to improvise the initial commit — the runbook owns it,
    # and ties the push to CI only when CI exists.
    with_ci = _onboarding(tmp_path / "ci")
    assert "Commit the scaffold" in with_ci
    assert "triggers CI" in with_ci
    assert "add a git remote first" in with_ci  # sets expectations for the push step
    assert "directly to `main`" in with_ci  # no branch/PR judgment call for the bootstrap
    assert "triggers CI" not in _onboarding(tmp_path / "no_ci", include_ci=False)


def test_runbook_flags_the_main_push_approval_prompt(tmp_path: Path) -> None:
    # The push targets `main`; an agent harness may classify that as needing approval,
    # so the runbook flags it as expected — but only when there's a push (CI) at all.
    assert "pause for your approval" in _onboarding(tmp_path / "ci")
    assert "pause for your approval" not in _onboarding(tmp_path / "no_ci", include_ci=False)


def test_architecture_step_is_greenfield_safe(tmp_path: Path) -> None:
    # On a brand-new repo there's no product architecture to write; the step must say
    # to leave it as TODOs rather than read as an action item (a real onboarding hit this).
    assert "leave those sections as TODOs" in _onboarding(tmp_path)


def test_wire_up_step_states_the_testing_bar(tmp_path: Path) -> None:
    # "add it the way the existing ones are" was ambiguous on tests (the JS test is a
    # no-op); point at the contract's bar instead of leaving it to the agent.
    body = _onboarding(tmp_path)
    assert "a real test where there's logic" in body
    assert "can't be tested" in body


def test_runbook_notes_python_prereq_for_rfc_hooks(tmp_path: Path) -> None:
    # The RFC/docs hooks shell out to `python`; a non-Python project still needs it.
    assert "`python` must be on your PATH" in _onboarding(tmp_path / "d")  # docs default on
    assert "`python` must be on your PATH" not in _onboarding(tmp_path / "n", include_docs=False)


def test_runbook_has_npm_lockfile_step_for_node(tmp_path: Path) -> None:
    # package.json ships without a lockfile; the runbook must own generating + committing it.
    node = _build(tmp_path / "node", languages=["node"]) / "ONBOARDING.md"
    assert "package-lock.json" in node.read_text(encoding="utf-8")
    plain = _build(tmp_path / "py", languages=["python"]) / "ONBOARDING.md"
    assert "package-lock.json" not in plain.read_text(encoding="utf-8")


def test_setup_step_points_at_bootstrap_when_there_are_deps(tmp_path: Path) -> None:
    # node has a setup_command, so the runbook hands the agent the one-shot `make
    # bootstrap`; a deps-free project just installs hooks via `make install`.
    node = (_build(tmp_path / "n", languages=["node"]) / "ONBOARDING.md").read_text(
        encoding="utf-8"
    )
    assert "make bootstrap" in node
    py = (_build(tmp_path / "p", languages=["python"]) / "ONBOARDING.md").read_text(
        encoding="utf-8"
    )
    assert "make bootstrap" not in py and "make install" in py


def test_api_key_step_only_for_claude_with_ci(tmp_path: Path) -> None:
    assert "ANTHROPIC_API_KEY" in _onboarding(tmp_path / "c", ai_tools=["claude"])
    assert "ANTHROPIC_API_KEY" not in _onboarding(tmp_path / "x", ai_tools=["cursor"])


def test_onboard_command_scaffolded_for_claude(tmp_path: Path) -> None:
    cmd = (_build(tmp_path, languages=["python"]) / ".claude/commands/onboard.md").read_text(
        encoding="utf-8"
    )
    assert "ONBOARDING.md" in cmd


def test_runbook_suggests_concurrency(tmp_path: Path) -> None:
    # The one-time costs (installs, CI) parallelize; the runbook says so while flagging
    # the chain that must stay serial.
    body = _onboarding(tmp_path)
    assert "in the background" in body and "parallel" in body  # single words: survive wrapping
    assert "chain in order" in body  # names the serial constraint (baseline->commit->push->CI)


def test_onboard_command_suggests_parallel_work(tmp_path: Path) -> None:
    # The Claude command can spawn subagents; tell it to, while keeping the dependent
    # chain and mutually-dependent edits serial.
    cmd = (_build(tmp_path, languages=["python"]) / ".claude/commands/onboard.md").read_text(
        encoding="utf-8"
    )
    assert "subagents" in cmd
    assert "serial" in cmd


def test_onboard_command_absent_when_no_onboarding(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["python"], include_quality=False, include_ci=False)
    assert not (root / ".claude/commands/onboard.md").exists()


def test_header_frames_first_run_for_an_agent(tmp_path: Path) -> None:
    body = _onboarding(tmp_path)
    assert "scaffolded by the `ai-setup` wizard" in body
    assert "AI assistant" in body  # speaks to the agent waking up here


def test_cleanup_removes_onboard_command_for_claude(tmp_path: Path) -> None:
    # The /onboard command is part of the self-deleting first-run apparatus, so cleanup
    # must remove it too — otherwise it dangles, pointing at a now-deleted ONBOARDING.md.
    for_claude = _onboarding(tmp_path / "c", ai_tools=["claude"])
    assert ".claude/commands/onboard.md" in for_claude
    # No command scaffolded -> nothing to remove (not Claude, or agents disabled).
    assert "onboard.md" not in _onboarding(tmp_path / "x", ai_tools=["cursor"])
    assert "onboard.md" not in _onboarding(
        tmp_path / "na", ai_tools=["claude"], include_agents=False
    )


def test_cleanup_removes_banner_when_injected(tmp_path: Path) -> None:
    with_banner = _onboarding(tmp_path / "b", first_run_banner=True)
    assert "remove the first-run banner" in with_banner
    assert "then commit" in with_banner  # cleanup ends by committing
    without = _onboarding(tmp_path / "n", first_run_banner=False)
    assert "remove the first-run banner" not in without
    assert "then commit" in without  # both branches end the runbook with a commit


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
        ([], "/onboard"),  # Claude targeted -> concrete first action, banner or not
        (["--no-first-run-banner"], "/onboard"),
        (["--tools", "cursor"], "ONBOARDING.md"),  # no Claude -> point at the file
    ],
)
def test_summary_points_at_first_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    extra_args: list[str],
    expected: str,
) -> None:
    # The summary names a concrete first action (the agent can't speak first):
    # `/onboard` when Claude is targeted, else the ONBOARDING.md file.
    cli.main(["demo", "-o", str(tmp_path), "--no-git", "-y", *extra_args])
    assert expected in capsys.readouterr().out


def test_summary_claude_tail_reflects_banner(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Both Claude paths name /onboard; the tail is the real delta. Banner on adds
    # "...AGENTS.md flags the pending setup"; banner off explains it "walks through"
    # the file. Assert on single words so the rich panel's line-wrapping can't split
    # the match, and cross-assert absence so a swapped tail is caught.
    cli.main(["demo", "-o", str(tmp_path / "on"), "--no-git", "-y"])
    on = capsys.readouterr().out
    assert "pending" in on and "walks" not in on
    cli.main(["demo", "-o", str(tmp_path / "off"), "--no-git", "-y", "--no-first-run-banner"])
    off = capsys.readouterr().out
    assert "walks" in off and "pending" not in off


def test_summary_defers_to_onboarding_without_duplicating_steps(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The runbook owns install + secrets; the summary must not re-list them.
    cli.main(["demo", "-o", str(tmp_path), "--languages", "python", "--no-git", "-y"])
    out = capsys.readouterr().out
    assert "/onboard" in out  # the banner-on Claude line names /onboard, not the file
    assert "pipx install" not in out  # install lives in ONBOARDING.md now
    assert "ANTHROPIC_API_KEY" not in out  # so does the secret
