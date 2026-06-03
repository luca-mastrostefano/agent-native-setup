"""Interrupting a scaffold rolls back only what this run created."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_native_setup import cli
from agent_native_setup.config import WizardConfig
from agent_native_setup.scaffold import Scaffolder


def test_rollback_removes_new_files_and_prunes_dirs(tmp_path: Path) -> None:
    (tmp_path / "keep.md").write_text("mine\n")
    sc = Scaffolder(tmp_path)
    sc.write("new.md", "x")
    sc.write("docs/inner.md", "y")
    sc.write("keep.md", "override")  # pre-existing, not --force → skipped

    removed = sc.rollback()

    assert removed == 2
    assert not (tmp_path / "new.md").exists()
    assert not (tmp_path / "docs").exists()  # emptied dir pruned
    assert (tmp_path / "keep.md").read_text() == "mine\n"  # untouched


def test_rollback_keeps_preexisting_dir_with_other_files(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "human.md").write_text("hand-written\n")
    sc = Scaffolder(tmp_path)
    sc.write("docs/generated.md", "z")

    sc.rollback()

    assert not (tmp_path / "docs" / "generated.md").exists()
    assert (tmp_path / "docs" / "human.md").exists()  # dir not pruned, file kept


def test_main_rolls_back_on_interrupt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(config: WizardConfig, sc: Scaffolder) -> None:
        raise KeyboardInterrupt

    # ai_context runs first and creates AGENTS.md; docs blows up mid-build.
    monkeypatch.setattr(cli.docs, "generate", boom)

    rc = cli.main(["demo", "-o", str(tmp_path), "-y", "--no-git"])

    assert rc == 130
    assert not (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / "CLAUDE.md").exists()
