"""Tests for the release-time version guard (tools/release_guard.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from agent_native_setup.migrations import MIGRATIONS, Migration

_GUARD = Path(__file__).resolve().parents[1] / "tools" / "release_guard.py"
_spec = importlib.util.spec_from_file_location("release_guard", _GUARD)
assert _spec and _spec.loader
release_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_guard)


def _agent(version: str) -> Migration:
    return Migration(version, "agent", f"split at {version}", instructions="do it")


def _auto(version: str) -> Migration:
    return Migration(version, "auto", f"move at {version}")


def test_blocks_a_non_forward_release() -> None:
    blocks, _ = release_guard.evaluate("0.6.0", "v0.6.0", [])  # re-releasing the latest
    assert any("not ahead" in b for b in blocks)
    blocks, _ = release_guard.evaluate("0.5.9", "v0.6.0", [])  # going backwards
    assert any("not ahead" in b for b in blocks)


def test_blocks_an_under_bump_that_activates_a_migration() -> None:
    # An agent migration shipped as a same-series patch (0.6.0 → 0.6.1) — the label would lie.
    blocks, _ = release_guard.evaluate("0.6.1", "v0.6.0", [_agent("0.6.1")])
    assert any("breaking" in b.lower() for b in blocks)


def test_allows_a_migration_with_a_breaking_bump() -> None:
    # 0.6 → 0.7 crosses the 0.x boundary, so an agent migration at 0.7.0 is honestly labelled.
    blocks, warnings = release_guard.evaluate("0.7.0", "v0.6.0", [_agent("0.7.0")])
    assert blocks == [] and warnings == []


def test_warns_on_a_breaking_bump_with_no_migration() -> None:
    blocks, warnings = release_guard.evaluate("0.7.0", "v0.6.0", [])
    assert blocks == []  # allowed
    assert any("forgotten migration" in w for w in warnings)  # but flagged for a look


def test_auto_migrations_do_not_trigger_the_block() -> None:
    # auto steps are idempotent/no-judgment, so they may ship in a compatible bump.
    blocks, _ = release_guard.evaluate("0.6.1", "v0.6.0", [_auto("0.6.1")])
    assert blocks == []


def test_future_tagged_migration_is_not_activated() -> None:
    # A migration staged for 0.8.0 is not activated by a 0.7.0 release (half-open interval).
    blocks, _ = release_guard.evaluate("0.7.0", "v0.6.0", [_agent("0.8.0")])
    assert blocks == []


def test_clean_patch_passes() -> None:
    blocks, warnings = release_guard.evaluate("0.6.1", "v0.6.0", [])
    assert blocks == [] and warnings == []


def test_manual_migration_also_blocks_an_under_bump() -> None:
    # `manual` is a breaking kind like `agent`, on the same code path.
    manual = Migration("0.6.1", "manual", "hand step", instructions="do it by hand")
    blocks, _ = release_guard.evaluate("0.6.1", "v0.6.0", [manual])
    assert any("breaking" in b.lower() for b in blocks)


def test_the_real_registry_releases_cleanly_at_its_versions() -> None:
    # Dogfood: the shipped registry's 0.6.0 split migration is consistent with the v0.6.0 cut.
    blocks, _ = release_guard.evaluate("0.6.0", "v0.5.1", MIGRATIONS)
    assert blocks == []


# --- main(): exit codes, the override, and safe degradation ----------------------------


def test_main_blocks_a_bad_version_without_force(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release_guard, "_latest_release_tag", lambda: "v0.6.0")
    monkeypatch.delenv("RELEASE_FORCE", raising=False)
    assert release_guard.main(["0.6.0"]) == 1  # non-forward → blocked


def test_main_override_downgrades_a_block_to_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release_guard, "_latest_release_tag", lambda: "v0.6.0")
    monkeypatch.setenv("RELEASE_FORCE", "1")
    assert release_guard.main(["0.6.0"]) == 0  # blocked, but overridden


def test_main_passes_a_clean_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release_guard, "_latest_release_tag", lambda: "v0.6.0")
    monkeypatch.delenv("RELEASE_FORCE", raising=False)
    assert release_guard.main(["0.6.1"]) == 0


def test_main_requires_a_version_arg() -> None:
    assert release_guard.main([]) == 2


def test_main_refuses_when_the_latest_release_cant_be_determined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # gh missing/offline → None. Treating that as 0.0.0 would silently disable the forward
    # check, so the guard refuses instead (unless forced).
    monkeypatch.setattr(release_guard, "_latest_release_tag", lambda: None)
    monkeypatch.delenv("RELEASE_FORCE", raising=False)
    assert release_guard.main(["0.7.0"]) == 1
    monkeypatch.setenv("RELEASE_FORCE", "1")
    assert release_guard.main(["0.7.0"]) == 0  # override proceeds
