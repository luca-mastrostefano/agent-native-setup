"""Tests for the structural migrations `update` replays before regenerating."""

from __future__ import annotations

from pathlib import Path

from agent_native_setup import migrations


def _rfc(target: Path, folder: str, name: str, body: str = "x") -> None:
    d = target / "docs" / "rfc" / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body, encoding="utf-8")


def test_rfc_lifecycle_rename_moves_current_and_done_into_active(tmp_path: Path) -> None:
    _rfc(tmp_path, "current", "a.md", "accepted rfc")
    _rfc(tmp_path, "done", "b.md", "done rfc")
    (tmp_path / "docs/rfc/current/.gitkeep").write_text("", encoding="utf-8")

    actions = migrations.apply_all(tmp_path)

    assert (tmp_path / "docs/rfc/active/a.md").read_text() == "accepted rfc"
    assert (tmp_path / "docs/rfc/active/b.md").read_text() == "done rfc"
    assert not (tmp_path / "docs/rfc/current").exists()  # drained folder removed
    assert not (tmp_path / "docs/rfc/done").exists()
    assert any("a.md" in a for a in actions)


def test_migration_is_idempotent_and_a_noop_on_the_new_layout(tmp_path: Path) -> None:
    # A repo already on the new layout (no current/ or done/) is untouched.
    _rfc(tmp_path, "active", "keep.md", "already active")
    assert migrations.apply_all(tmp_path) == []
    assert (tmp_path / "docs/rfc/active/keep.md").read_text() == "already active"


def test_migration_does_not_clobber_an_existing_destination(tmp_path: Path) -> None:
    # If active/ already holds a same-named RFC, the legacy one is left in place rather
    # than overwriting the user's current file.
    _rfc(tmp_path, "current", "dup.md", "legacy version")
    _rfc(tmp_path, "active", "dup.md", "current version")

    migrations.apply_all(tmp_path)

    assert (tmp_path / "docs/rfc/active/dup.md").read_text() == "current version"
    assert (tmp_path / "docs/rfc/current/dup.md").read_text() == "legacy version"
