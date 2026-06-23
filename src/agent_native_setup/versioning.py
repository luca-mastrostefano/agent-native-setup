"""Version comparison and the update gate (RFC 2026-06-22).

The gate keys on the **breaking series**, not literally the major — because semver's `0.x`
is special: pre-1.0 a *minor* bump is the breaking signal, 1.0+ the major is. Same series →
autopilot (the contract promised nothing breaking); a series change → gated (confirm +
agent-assisted migration). The version *declares* difficulty; the per-file fingerprints
(see ``update.classify``) verify it — so a mislabel can't silently overwrite an edited file.
"""

from __future__ import annotations

from packaging.version import InvalidVersion, Version

# update.decide() outcomes
NOOP = "noop"  # already current
DOWNGRADE = "downgrade"  # installed tool is older than the project's scaffolding
AUTOPILOT = "autopilot"  # same breaking series — apply automatically
GATED = "gated"  # series changed — confirm + (maybe) agent-assisted migration


def parse(v: str) -> Version:
    """Best-effort parse. An unparseable or unknown version sorts as ``0.0.0`` —
    conservative: it precedes every real release, so everything is in-span and the gate
    fires rather than silently auto-applying across an unknown boundary."""
    try:
        return Version(v)
    except InvalidVersion:
        return Version("0.0.0")


def breaking_series(v: Version) -> tuple[int, ...]:
    """The compatibility series a version belongs to. Pre-1.0 the *minor* is the breaking
    boundary (``0.4`` vs ``0.5`` differ); 1.0+ the *major* is (``1.9`` vs ``2.0`` differ).
    Two versions auto-apply across each other iff their series are equal."""
    return (v.major,) if v.major >= 1 else (0, v.minor)


def decide(installed: str, latest: str) -> str:
    """Classify an ``installed`` → ``latest`` update as NOOP / DOWNGRADE / AUTOPILOT / GATED."""
    iv, lv = parse(installed), parse(latest)
    if lv < iv:
        return DOWNGRADE
    if lv == iv:
        return NOOP
    return GATED if breaking_series(iv) != breaking_series(lv) else AUTOPILOT
