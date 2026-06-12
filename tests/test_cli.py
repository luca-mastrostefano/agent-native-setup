"""CLI-level behavior: Ctrl+C / Ctrl+D during the wizard exits cleanly (not a traceback)."""

from __future__ import annotations

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
    cli._summary(config, Scaffolder(config.target))
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
