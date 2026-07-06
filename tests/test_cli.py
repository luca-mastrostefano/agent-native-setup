"""CLI-level behavior: Ctrl+C / Ctrl+D during the wizard exits cleanly (not a traceback)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_native_setup import cli
from agent_native_setup.config import WizardConfig
from agent_native_setup.scaffold import Scaffolder


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt, EOFError])
def test_interrupt_during_prompts_exits_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupt: type[BaseException]
) -> None:
    # Force the interactive path, then have a prompt abort.
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def boom(*_a: object, **_k: object) -> object:
        raise interrupt

    monkeypatch.setattr(cli, "_interactive", boom)

    assert cli.main(["demo", "-o", str(tmp_path)]) == 130
    assert not (tmp_path / "AGENTS.md").exists()  # nothing scaffolded on cancel


def test_default_name_comes_from_cwd_when_output_is_dot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: Path(".").name is "" — scaffolding into the cwd (the default -o)
    # without a name argument must still title the project after the directory.
    project = tmp_path / "my-project"
    project.mkdir()
    monkeypatch.chdir(project)
    assert cli.main(["-y", "--no-git"]) == 0
    agents = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "# my-project — Agent Contract" in agents


def test_dry_run_previews_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # --dry-run lists what a real run would create but touches nothing (parity with
    # `update --dry-run`).
    target = tmp_path / "proj"
    rc = cli.main(["demo", "-o", str(target), "-y", "--dry-run", "--languages", "python"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "dry run" in out.lower()
    assert "would create AGENTS.md" in out
    assert "would run git init" in out  # git defaults on, but dry-run never runs it
    # Nothing was actually written — not even the manifest.
    assert not (target / "AGENTS.md").exists()
    assert not (target / ".agent-native-setup.json").exists()
    assert not (target / ".git").exists()


def test_dry_run_marks_existing_files_as_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The preview must reproduce the writer's skip-existing behaviour — pretending every path
    # is new is exactly wrong for the "what will this do to my repo?" case.
    target = tmp_path / "proj"
    target.mkdir()
    (target / "README.md").write_text("my own readme\n", encoding="utf-8")  # a real run skips it
    rc = cli.main(
        ["demo", "-o", str(target), "-y", "--no-git", "--dry-run", "--languages", "python"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "would skip (exists): README.md" in out
    assert "would create README.md" not in out
    # The user's file is untouched, and nothing was written.
    assert (target / "README.md").read_text(encoding="utf-8") == "my own readme\n"
    assert not (target / ".agent-native-setup.json").exists()


def test_unknown_tool_exits_2_without_scaffolding(tmp_path: Path) -> None:
    # --languages typos are rejected; --tools typos must not silently no-op.
    rc = cli.main(["demo", "-o", str(tmp_path), "-y", "--no-git", "--tools", "cluade"])
    assert rc == 2
    assert not (tmp_path / "AGENTS.md").exists()


def test_intro_shown_at_start_of_interactive_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Interactive run: the intro prints before any prompt, even if the user cancels.
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def boom(*_a: object, **_k: object) -> object:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_interactive", boom)
    cli.main(["demo", "-o", str(tmp_path)])
    assert "scaffolds" in capsys.readouterr().out  # the "what this will do" intro


def test_intro_shows_version_in_top_right(capsys: pytest.CaptureFixture[str]) -> None:
    # The version rides on the top border, to the right of the "What this will do" heading.
    from agent_native_setup import __version__

    cli._intro()
    top = capsys.readouterr().out.splitlines()[0]  # the top border line
    assert "What this will do" in top
    assert f"v{__version__}" in top
    assert top.index("What this will do") < top.index(f"v{__version__}")  # heading left, ver right


def test_next_steps_label_contract_optional_and_setup_important(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # With both steps shown, they're a contrasting pair: reading the contract is Optional,
    # finishing the one-time setup is the IMPORTANT must-do — and in that order.
    config = WizardConfig(project_name="demo", output_dir=tmp_path, init_git=False)
    sc = Scaffolder(config.target)
    sc.created.append("ONBOARDING.md")  # the hint keys on the runbook actually shipping
    cli._summary(config, sc)
    out = capsys.readouterr().out
    assert "⚠" in out  # the importance icon precedes IMPORTANT
    assert out.index("Optional:") < out.index("IMPORTANT:")  # contract first, setup second


def test_next_steps_lone_contract_not_mislabelled_optional(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # No quality and no CI -> only the contract step. With no contrasting must-do, it must
    # NOT be marked "Optional" (that would read as "skip the only thing to do").
    config = WizardConfig(
        project_name="demo",
        output_dir=tmp_path,
        init_git=False,
        include_quality=False,
        include_ci=False,
    )
    cli._summary(config, Scaffolder(config.target))
    out = capsys.readouterr().out
    assert "AGENTS.md" in out
    assert "Optional:" not in out
    assert "IMPORTANT:" not in out


def test_git_init_lands_on_main_regardless_of_user_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The docs, CI triggers, and onboarding all say `main`, but a user's
    # init.defaultBranch (or an old git default) can produce `master` — seen in a real
    # first run. The scaffold must pin the branch name itself.
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("[init]\n\tdefaultBranch = master\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    target = tmp_path / "proj"
    assert cli.main(["demo", "-o", str(target), "-y", "--no-update-check"]) == 0
    branch = subprocess.run(
        ["git", "-C", str(target), "branch", "--show-current"],
        capture_output=True,
        text=True,
    )
    assert branch.stdout.strip() == "main"


def test_git_init_fallback_lands_on_main_for_old_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # git <2.28 has no `init -b`; the fallback must retarget the unborn HEAD (review of
    # the fix: `branch -m` needs git 2.30, so it failed silently on exactly the old gits).
    # Shim: a `git` that rejects `init -b` like an old git, passing everything else through.
    import shutil as _shutil

    real_git = _shutil.which("git")
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    shim = shim_dir / "git"
    shim.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "init" ] && echo "$@" | grep -q -- "-b"; then\n'
        '  echo "error: unknown switch \\`b\'" >&2; exit 129\n'
        "fi\n"
        f'exec "{real_git}" "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("[init]\n\tdefaultBranch = master\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("PATH", f"{shim_dir}:{__import__('os').environ['PATH']}")
    target = tmp_path / "proj"
    assert cli.main(["demo", "-o", str(target), "-y", "--no-update-check"]) == 0
    head = subprocess.run(
        ["git", "-C", str(target), "symbolic-ref", "HEAD"], capture_output=True, text=True
    )
    assert head.stdout.strip() == "refs/heads/main"
