"""Tests for the structural migrations `update` replays before regenerating."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_native_setup import migrations
from agent_native_setup.migrations import Migration


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


def test_contract_split_is_a_real_agent_migration_at_0_6_0() -> None:
    # The AGENTS.md → INSTRUCTION.md split is an agent-assisted step shipped at the 0.5→0.6
    # breaking boundary; it surfaces only when that boundary is crossed.
    steps = migrations.steps_in_span("0.5.1", "0.6.0")
    assert [m.kind for m in steps] == ["agent"]
    assert "INSTRUCTION.md" in steps[0].instructions
    assert migrations.steps_in_span("0.6.0", "0.6.1") == []  # not crossed → not surfaced


def test_apply_all_runs_only_auto_steps(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # agent/manual steps are never performed by the tool — apply_all touches auto only.
    ran: list[str] = []

    def _auto(target: Path, *, apply: bool = True) -> list[str]:
        ran.append("auto")
        return ["did auto"]

    registry = [
        Migration("1.0.0", "auto", "an auto move", apply=_auto),
        Migration("2.0.0", "agent", "an agent step", instructions="do it by hand"),
    ]
    monkeypatch.setattr(migrations, "MIGRATIONS", registry)
    actions = migrations.apply_all(tmp_path)
    assert actions == ["did auto"] and ran == ["auto"]  # the agent step was skipped


def test_steps_in_span_selects_and_orders_agent_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = [
        Migration("3.0.0", "agent", "third", instructions="c"),
        Migration("0.5.0", "auto", "an auto move (excluded — not agent/manual)"),
        Migration("2.0.0", "agent", "second", instructions="b"),
        Migration("1.0.0", "manual", "first", instructions="a"),
    ]
    monkeypatch.setattr(migrations, "MIGRATIONS", registry)

    # A 0.9 → 3.0 span crosses 1.0, 2.0, 3.0 — all three, ascending; the auto step excluded.
    chosen = migrations.steps_in_span("0.9.0", "3.0.0")
    assert [m.describe for m in chosen] == ["first", "second", "third"]

    # A narrower span picks only the boundaries inside it (exclusive of installed).
    assert [m.version for m in migrations.steps_in_span("1.0.0", "2.0.0")] == ["2.0.0"]
    assert migrations.steps_in_span("3.0.0", "3.0.0") == []  # nothing newer than installed
