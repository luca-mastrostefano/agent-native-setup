"""CLI-level behavior: Ctrl+C / Ctrl+D during the wizard exits cleanly (not a traceback)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_setup import cli


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
