"""The update gate: how an installed→latest version pair is classified."""

from __future__ import annotations

import pytest

from agent_native_setup import versioning
from agent_native_setup.versioning import AUTOPILOT, DOWNGRADE, GATED, NOOP


@pytest.mark.parametrize(
    ("installed", "latest", "expected"),
    [
        # same version → nothing to do
        ("0.5.1", "0.5.1", NOOP),
        # installed newer than the tool → refuse (don't regenerate older templates)
        ("0.6.0", "0.5.1", DOWNGRADE),
        ("1.2.0", "0.9.0", DOWNGRADE),
        # 0.x: a PATCH is compatible, a MINOR is the breaking boundary
        ("0.4.2", "0.4.9", AUTOPILOT),
        ("0.4.2", "0.5.0", GATED),
        ("0.5.0", "0.5.1", AUTOPILOT),
        # the 1.0 graduation is itself a boundary
        ("0.9.3", "1.0.0", GATED),
        # 1.0+: a MINOR is compatible, a MAJOR is the breaking boundary
        ("1.2.0", "1.9.0", AUTOPILOT),
        ("1.6.0", "2.0.0", GATED),
        # multi-boundary spans are still just "gated" (the runbook orders the steps)
        ("1.2.0", "3.0.0", GATED),
    ],
)
def test_decide_classifies_the_update(installed: str, latest: str, expected: str) -> None:
    assert versioning.decide(installed, latest) == expected


def test_unknown_installed_version_is_conservative() -> None:
    # A 0.0.0 / unparseable installed version sorts before every real release, so any real
    # latest is a different series → gated (never auto-applies across an unknown boundary).
    assert versioning.decide("0.0.0", "0.5.1") == GATED
    assert versioning.decide("not-a-version", "1.2.0") == GATED


def test_dev_builds_compare_correctly() -> None:
    # A dev build past the latest release is "nothing to do" (never nagged); a dev build of
    # the same series as latest is autopilot.
    assert versioning.decide("0.5.2.dev4+gabc", "0.5.1") == DOWNGRADE  # ahead of the release
    assert versioning.decide("0.5.0", "0.5.1.dev2+gabc") == AUTOPILOT  # same 0.5 series


def test_breaking_series_boundary_rule() -> None:
    p = versioning.parse
    # pre-1.0: keyed on the minor
    assert versioning.breaking_series(p("0.4.9")) == versioning.breaking_series(p("0.4.0"))
    assert versioning.breaking_series(p("0.4.0")) != versioning.breaking_series(p("0.5.0"))
    # 1.0+: keyed on the major
    assert versioning.breaking_series(p("1.2.0")) == versioning.breaking_series(p("1.9.9"))
    assert versioning.breaking_series(p("1.9.9")) != versioning.breaking_series(p("2.0.0"))
