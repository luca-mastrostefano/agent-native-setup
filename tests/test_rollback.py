"""Interrupting a scaffold rolls back only what this run created."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_native_setup import cli
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


def test_rollback_restores_force_overwritten_file(tmp_path: Path) -> None:
    (tmp_path / "keep.md").write_text("mine\n")
    sc = Scaffolder(tmp_path, force=True)
    sc.write("keep.md", "generated")
    assert (tmp_path / "keep.md").read_text() == "generated"

    sc.rollback()

    assert (tmp_path / "keep.md").read_text() == "mine\n"


def test_rollback_restores_file_replaced_by_symlink(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("contract\n")
    (tmp_path / "CLAUDE.md").write_text("hand-written\n")
    sc = Scaffolder(tmp_path, force=True)
    sc.symlink("CLAUDE.md", "AGENTS.md")
    assert (tmp_path / "CLAUDE.md").is_symlink()

    sc.rollback()

    assert not (tmp_path / "CLAUDE.md").is_symlink()
    assert (tmp_path / "CLAUDE.md").read_text() == "hand-written\n"


def test_rollback_restores_symlink_overwritten_by_write(tmp_path: Path) -> None:
    # A force write() onto a pre-existing symlink must replace the link (not write
    # through it), and rollback must bring the link back with its target untouched.
    (tmp_path / "real.md").write_text("target content\n")
    (tmp_path / "config.md").symlink_to("real.md")
    sc = Scaffolder(tmp_path, force=True)
    sc.write("config.md", "generated")
    assert not (tmp_path / "config.md").is_symlink()
    assert (tmp_path / "real.md").read_text() == "target content\n"  # not written through

    sc.rollback()

    assert os.readlink(tmp_path / "config.md") == "real.md"
    assert (tmp_path / "real.md").read_text() == "target content\n"


def test_rollback_restores_replaced_symlink_target(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("x\n")
    (tmp_path / "OLD.md").write_text("old\n")
    (tmp_path / "CLAUDE.md").symlink_to("OLD.md")
    sc = Scaffolder(tmp_path, force=True)
    sc.symlink("CLAUDE.md", "AGENTS.md")

    sc.rollback()

    assert os.readlink(tmp_path / "CLAUDE.md") == "OLD.md"


def test_main_rolls_back_on_interrupt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Post-flip (RFC 2026-07-05 §7-B) the default path scaffolds the flagship profile, so
    # the mid-build interrupt fires inside profiles.apply after some files landed.
    real_apply = cli.profiles.apply
    state = {"n": 0}

    def boom(*a: object, **k: object) -> object:
        state["n"] += 1
        if state["n"] == 1:
            orig_overlay = a[2].overlay

            def exploding_overlay(rel: str, content: str, **kw: object) -> bool:
                if rel.startswith("docs/"):
                    raise KeyboardInterrupt
                return orig_overlay(rel, content, **kw)

            a[2].overlay = exploding_overlay  # type: ignore[method-assign]
        return real_apply(*a, **k)

    monkeypatch.setattr(cli.profiles, "apply", boom)

    rc = cli.main(["demo", "-o", str(tmp_path), "-y", "--no-git"])

    assert rc == 130
    assert not (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / "CLAUDE.md").exists()
