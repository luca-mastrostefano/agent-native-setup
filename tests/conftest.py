"""Shared pytest fixtures.

The engine no longer vendors the flagship baseline — `builtin:agent-native-baseline`
resolves by fetching a pinned git URL and verifying it against `baseline-pin.json`'s hash
(RFC 2026-07-08). To keep the suite hermetic (offline, no network), point
`builtin_baseline_root` at a checked-in **fixture** copy of the baseline instead. This is a
test-only stub — never shipped — and it preserves the real behavior that matters: `resolve`
still records `source="builtin:agent-native-baseline"`, so default-scaffold tests stay
faithful. Tests marked `real_baseline_fetch` opt out to exercise the true fetch+verify path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_native_setup import profiles

BASELINE_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "agent-native-baseline"


@pytest.fixture(autouse=True)
def _stub_builtin_baseline(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("real_baseline_fetch"):
        return
    monkeypatch.setattr(profiles, "builtin_baseline_root", lambda console=None: BASELINE_FIXTURE)
