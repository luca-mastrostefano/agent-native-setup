"""ONBOARDING.md: a one-time, self-deleting first-run runbook + the /onboard command."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_native_setup import cli
from agent_native_setup.config import WizardConfig
from agent_native_setup.scaffold import Scaffolder


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


def test_architecture_step_only_for_existing_code(tmp_path: Path) -> None:
    # On a brand-new repo there's no product architecture to write — the step always
    # resolved to "move on" (real-run feedback), so it ships only for a brownfield repo
    # (the doc itself says "add components as they land" for greenfield).
    assert "docs/architecture/overview.md" not in _onboarding(tmp_path / "green")
    assert "docs/architecture/overview.md" in _onboarding(tmp_path / "brown", existing_project=True)


def test_wire_up_step_is_gone(tmp_path: Path) -> None:
    # The wizard already wired every selected language, so the step was always a no-op
    # (real-run feedback); the standing rule lives in INSTRUCTION.md.
    assert "uncovered language" not in _onboarding(tmp_path)


def test_runbook_notes_python3_prereq_for_rfc_hooks(tmp_path: Path) -> None:
    # The RFC/docs hooks shell out to `python3`; a non-Python project still needs it.
    assert "`python3` must be on your PATH" in _onboarding(tmp_path / "d")  # docs default on
    assert "`python3` must be on your PATH" not in _onboarding(tmp_path / "n", include_docs=False)


def test_baseline_step_gives_the_exact_install_command(tmp_path: Path) -> None:
    # "install them on your PATH first" left the how as a scavenger hunt (real-run
    # feedback) — the runbook now names a copy-pasteable command for the exact tool set.
    assert "`pipx install ruff mypy pytest`" in _onboarding(tmp_path)


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


def test_runbook_has_no_api_key_step(tmp_path: Path) -> None:
    # The @claude CI bot is out of scope, so onboarding never asks for ANTHROPIC_API_KEY.
    assert "ANTHROPIC_API_KEY" not in _onboarding(tmp_path, ai_tools=["claude"])


def test_runbook_flags_enabling_dependabot_security_updates(tmp_path: Path) -> None:
    # dependabot.yml can't flip the repo setting; on by default for public, manual for
    # private — a maintainer hit this. Only when CI/dependabot.yml is scaffolded.
    body = _onboarding(tmp_path / "ci")
    assert "automated-security-fixes" in body
    assert "on by default for public" in body
    assert "automated-security-fixes" not in _onboarding(tmp_path / "no_ci", include_ci=False)


def test_baseline_step_flags_python_command_surface_tools(tmp_path: Path) -> None:
    # The command surface calls ruff/mypy/pytest directly; the scaffold doesn't install
    # them, so the runbook must name them as prereqs (a real onboarding tripped on ruff).
    py = _onboarding(tmp_path / "py")  # python project -> ruff, mypy, pytest
    assert "`ruff`" in py and "`mypy`" in py and "`pytest`" in py
    assert "on your PATH" in py
    # node + docs ships only tools/checks (Python helpers), so just ruff is in the surface.
    node = (_build(tmp_path / "n", languages=["node"]) / "ONBOARDING.md").read_text(
        encoding="utf-8"
    )
    assert "`ruff`" in node and "`mypy`" not in node


def test_cleanup_keeps_ci_watch_for_link_checked_docs(tmp_path: Path) -> None:
    # With HTML/lychee in CI, the cleanup commit edits link-checked docs, so don't claim
    # "no CI watch needed" — a dangling link could fail the build.
    html = (_build(tmp_path / "h", languages=["html"]) / "ONBOARDING.md").read_text(
        encoding="utf-8"
    )
    assert "no CI watch is needed" not in html
    assert "no CI watch is needed" in _onboarding(tmp_path / "py")  # non-HTML keeps the speedup


def test_cleanup_flags_claude_md_symlink_transiently(tmp_path: Path) -> None:
    # CLAUDE.md symlinks to AGENTS.md; the self-deleting runbook flags it so the agent
    # doesn't edit CLAUDE.md separately. Only when claude is targeted and a banner exists.
    assert "`CLAUDE.md` symlinks to `AGENTS.md`" in _onboarding(
        tmp_path / "c", ai_tools=["claude"], first_run_banner=True
    )
    assert "symlinks to" not in _onboarding(tmp_path / "nb", ai_tools=["claude"])  # no banner
    assert "symlinks to" not in _onboarding(
        tmp_path / "cur", ai_tools=["cursor"], first_run_banner=True
    )


def test_cleanup_flags_both_symlinks_for_claude_and_gemini(tmp_path: Path) -> None:
    # With both symlink tools targeted, the note names both and says "all" (not "both").
    body = _onboarding(tmp_path, ai_tools=["claude", "gemini"], first_run_banner=True)
    assert "`CLAUDE.md` and `GEMINI.md` symlink to `AGENTS.md`" in body
    assert "all update together" in body


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
    assert "scaffolded by the `agent-native-setup` wizard" in body
    assert "AI assistant" in body  # speaks to the agent waking up here


def test_cleanup_enumerates_every_written_trigger(tmp_path: Path) -> None:
    # The /onboard triggers are part of the self-deleting first-run apparatus, so cleanup
    # must list each one actually written — whichever brand finishes onboarding removes
    # them all, and no future agent re-runs it (RFC 2026-07-07).
    for_claude = _onboarding(tmp_path / "c", ai_tools=["claude"])
    assert "`.claude/commands/onboard.md`" in for_claude
    multi = _onboarding(tmp_path / "m", ai_tools=["cursor", "gemini"])
    assert "`.cursor/commands/onboard.md`" in multi
    assert "`.gemini/commands/onboard.toml`" in multi
    assert "onboard.prompt.md" not in multi  # copilot not targeted
    assert ".claude/commands/onboard.md" not in multi  # claude not targeted
    # The gate is uniform (runbook => triggers): include_agents no longer gates Claude's.
    assert ".claude/commands/onboard.md" in _onboarding(
        tmp_path / "na", ai_tools=["claude"], include_agents=False
    )
    # No tools targeted -> a runbook with no triggers and no trigger-cleanup clause.
    assert "/onboard" not in _onboarding(tmp_path / "none", ai_tools=[])


def test_triggers_ship_per_tool_and_parse(tmp_path: Path) -> None:
    import tomllib

    root = _build(tmp_path, languages=["python"])  # default: all four tools
    assert (root / ".claude/commands/onboard.md").is_file()
    assert (root / ".cursor/commands/onboard.md").is_file()
    prompt_md = (root / ".github/prompts/onboard.prompt.md").read_text(encoding="utf-8")
    assert prompt_md.startswith("---\ndescription:")  # copilot frontmatter
    toml_body = (root / ".gemini/commands/onboard.toml").read_text(encoding="utf-8")
    data = tomllib.loads(toml_body)  # gemini: must be valid TOML
    assert "ONBOARDING.md" in data["prompt"] and data["description"]
    # All transient: never recorded, so update can't resurrect them post-onboarding.
    import json

    m = json.loads((root / ".agent-native-setup.json").read_text(encoding="utf-8"))
    for rel in (
        ".claude/commands/onboard.md",
        ".cursor/commands/onboard.md",
        ".github/prompts/onboard.prompt.md",
        ".gemini/commands/onboard.toml",
    ):
        assert rel not in m["files"], rel


def test_profile_owned_trigger_path_wins_through_the_real_cli(tmp_path: Path) -> None:
    # Integration for RFC 2026-07-07 §5 through cli.main (review of the first cut: the
    # generator honored profile_paths but no call site passed it): a profile shipping its
    # own file at a trigger path must get no engine trigger there and no cleanup listing —
    # else onboarding deletes a managed file that `update` then resurrects.
    import json

    prof = tmp_path / "prof"
    (prof / "templates" / ".gemini" / "commands").mkdir(parents=True)
    (prof / "templates" / ".gemini" / "commands" / "onboard.toml").write_text(
        'description = "mine"\nprompt = "custom onboarding"\n', encoding="utf-8"
    )
    (prof / "profile.json").write_text(
        json.dumps(
            {
                "name": "own-trigger",
                "version": "1.0.0",
                "description": "d",
                "onboarding": ["Do the one thing."],
            }
        ),
        encoding="utf-8",
    )
    target = tmp_path / "proj"
    rc = cli.main(
        [
            "demo",
            "-o",
            str(target),
            "-y",
            "--no-git",
            "--no-update-check",
            "--tools",
            "gemini,cursor",
            "--profile",
            str(prof),
        ]
    )
    assert rc == 0
    # The profile's managed copy is what lands (and is recorded); no engine transient.
    body = (target / ".gemini" / "commands" / "onboard.toml").read_text(encoding="utf-8")
    assert "custom onboarding" in body
    m = json.loads((target / ".agent-native-setup.json").read_text(encoding="utf-8"))
    assert ".gemini/commands/onboard.toml" in m["files"]  # profile-owned, managed
    # The cleanup enumerates only the engine's own trigger — never the profile's file.
    runbook = (target / "ONBOARDING.md").read_text(encoding="utf-8")
    assert "`.cursor/commands/onboard.md`" in runbook
    assert ".gemini" not in runbook


def test_trigger_skips_profile_owned_and_preexisting_paths(tmp_path: Path) -> None:
    from agent_native_setup.generators import onboarding

    # Profile-owned path wins (RFC 2026-07-07 §5): no engine trigger, not enumerated.
    target = tmp_path / "p"
    target.mkdir()
    config = WizardConfig(
        project_name="demo", output_dir=target, ai_tools=["gemini", "cursor"], init_git=False
    )
    sc = Scaffolder(target)
    onboarding.generate(
        config,
        sc,
        profile_steps=("Do the thing.",),
        base=False,
        profile_paths=frozenset({".gemini/commands/onboard.toml"}),
    )
    assert not (target / ".gemini/commands/onboard.toml").exists()
    body = (target / "ONBOARDING.md").read_text(encoding="utf-8")
    assert ".gemini" not in body and "`.cursor/commands/onboard.md`" in body

    # A pre-existing user file is preserved and never listed for deletion.
    target2 = tmp_path / "u"
    (target2 / ".cursor/commands").mkdir(parents=True)
    (target2 / ".cursor/commands/onboard.md").write_text("mine\n", encoding="utf-8")
    config2 = WizardConfig(
        project_name="demo", output_dir=target2, ai_tools=["cursor"], init_git=False
    )
    sc2 = Scaffolder(target2)
    onboarding.generate(config2, sc2, profile_steps=("Step.",), base=False)
    assert (target2 / ".cursor/commands/onboard.md").read_text(encoding="utf-8") == "mine\n"
    assert ".cursor" not in (target2 / "ONBOARDING.md").read_text(encoding="utf-8")


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
    assert "agent-native-setup:first-run" in agents  # the removable, delimited block
    assert "complete [`ONBOARDING.md`]" in agents


def test_no_banner_without_flag_or_without_onboarding(tmp_path: Path) -> None:
    off = _build(tmp_path / "off", languages=["python"], first_run_banner=False) / "AGENTS.md"
    assert "agent-native-setup:first-run" not in off.read_text(encoding="utf-8")
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
    assert "agent-native-setup:first-run" not in bare.read_text(encoding="utf-8")


def test_banner_suppressed_without_an_ai_tool(tmp_path: Path) -> None:
    # Nothing auto-loads AGENTS.md without a targeted tool, so the banner would be inert —
    # and the runbook must not tell the agent to remove one that was never written.
    root = _build(tmp_path, languages=["python"], ai_tools=[], first_run_banner=True)
    assert "agent-native-setup:first-run" not in (root / "AGENTS.md").read_text(encoding="utf-8")
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
