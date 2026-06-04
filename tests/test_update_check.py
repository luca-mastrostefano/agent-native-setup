"""The best-effort 'newer version available' check — advisory, never raises."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_native_setup import update_check


class _Console:
    def __init__(self) -> None:
        self.printed: list[str] = []

    def print(self, msg: str) -> None:
        self.printed.append(msg)


def test_is_newer_handles_v_prefix_dev_and_garbage() -> None:
    assert update_check._is_newer("v0.3.0", "0.2.0")
    assert update_check._is_newer("v0.3.0", "0.3.0.dev2")  # a dev build is older than release
    assert not update_check._is_newer("v0.2.0", "0.2.0")  # same -> not newer
    assert not update_check._is_newer("v0.2.0", "0.3.0")  # installed ahead (bleeding edge)
    assert not update_check._is_newer("not-a-version", "0.2.0")  # unparseable -> no nag


def test_notifies_when_a_newer_release_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(update_check, "_cache_path", lambda: tmp_path / "c.json")
    monkeypatch.setattr(update_check, "_fetch_latest_tag", lambda: "v9.9.9")
    monkeypatch.setattr(update_check, "_installed_version", lambda: "0.1.0")
    con = _Console()
    update_check.maybe_notify(con, now=1000.0)
    assert any("uv tool upgrade agent-native-setup" in m for m in con.printed)


def test_silent_when_current(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(update_check, "_cache_path", lambda: tmp_path / "c.json")
    monkeypatch.setattr(update_check, "_fetch_latest_tag", lambda: "v0.1.0")
    monkeypatch.setattr(update_check, "_installed_version", lambda: "0.1.0")
    con = _Console()
    update_check.maybe_notify(con, now=1000.0)
    assert con.printed == []


def test_network_error_is_a_silent_noop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(update_check, "_cache_path", lambda: tmp_path / "c.json")

    def boom() -> str:
        raise OSError("offline")

    monkeypatch.setattr(update_check, "_fetch_latest_tag", boom)
    monkeypatch.setattr(update_check, "_installed_version", lambda: "0.1.0")
    con = _Console()
    update_check.maybe_notify(con, now=1000.0)  # must not raise
    assert con.printed == []


def test_cache_avoids_a_second_fetch_within_the_day(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(update_check, "_cache_path", lambda: tmp_path / "c.json")
    monkeypatch.setattr(update_check, "_installed_version", lambda: "0.1.0")
    calls = {"n": 0}

    def fetch() -> str:
        calls["n"] += 1
        return "v9.9.9"

    monkeypatch.setattr(update_check, "_fetch_latest_tag", fetch)
    con = _Console()
    update_check.maybe_notify(con, now=1000.0)
    update_check.maybe_notify(con, now=1001.0)  # within TTL -> served from cache
    assert calls["n"] == 1
