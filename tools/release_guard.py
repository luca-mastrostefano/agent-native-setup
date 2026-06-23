"""Release-time version guard (RFC 2026-06-23): keep the release version label honest.

Run before `gh release create` (wired into `task release`). It reuses the update gate's own
`versioning.breaking_series`, so a release that *activates* an `agent`/`manual` migration
can't ship as a compatible bump — the `--check` nudge and the changelog stay truthful. This
is label honesty, not a safety net: the engine already gates a mistagged migration downstream
(`update.run`'s `bool(agent_steps)`).

Blocks a non-forward version and an under-bump (a migration without a breaking-series bump);
warns on a breaking bump with no migration. `RELEASE_FORCE=1` downgrades blocks to warnings.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from agent_native_setup import migrations, versioning


def evaluate(version: str, latest_tag: str, registry: list) -> tuple[list[str], list[str]]:
    """Return ``(blocks, warnings)`` for cutting ``version`` after ``latest_tag``. Pure — the
    I/O (reading the latest tag, exiting) lives in ``main()`` — so the policy is unit-tested."""
    v = versioning.parse(version.lstrip("v"))
    latest = versioning.parse(latest_tag.lstrip("v")) if latest_tag else versioning.parse("0.0.0")
    blocks: list[str] = []
    warnings: list[str] = []

    if v <= latest:
        blocks.append(f"{version} is not ahead of the latest release {latest_tag or '(none)'}")

    # Migrations this release activates: half-open at the top, so an entry staged for a future
    # version (> v) is not "activated" by this release and is correctly ignored.
    activated = [
        m
        for m in registry
        if m.kind in ("agent", "manual") and latest < versioning.parse(m.version) <= v
    ]
    crosses = versioning.breaking_series(v) != versioning.breaking_series(latest)
    if activated and not crosses:
        named = "; ".join(f"{m.version} — {m.describe}" for m in activated)
        blocks.append(
            f"this release activates a breaking migration, but {latest_tag or '(none)'} → "
            f"{version} stays in series {versioning.breaking_series(v)}: {named}. Bump across a "
            "breaking-series boundary (pre-1.0 the minor, 1.0+ the major)."
        )
    if crosses and not activated:
        warnings.append(
            f"{latest_tag or '(none)'} → {version} crosses a breaking boundary but adds no "
            "agent/manual migration — intentional, or a forgotten migration?"
        )
    return blocks, warnings


def _latest_release_tag() -> str | None:
    """The latest published release tag, read from the **remote** (not stale local tags).
    Returns the tag on success, ``""`` when there are confirmed zero releases (a legitimate
    first release), or ``None`` when it can't be determined (gh missing or errored) — the
    caller must *not* treat that as ``0.0.0``, which would silently disable the forward check.
    The most-recent release is the highest version under this project's linear tag history."""
    try:
        out = subprocess.run(
            ["gh", "release", "list", "--limit", "1", "--json", "tagName"],
            capture_output=True,
            text=True,
        )
    except OSError:  # gh not installed
        return None
    if out.returncode != 0:  # auth/network error (an empty release list is still returncode 0)
        return None
    data = json.loads(out.stdout or "[]")
    return data[0]["tagName"] if data else ""


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: release_guard.py VERSION", file=sys.stderr)
        return 2
    version = argv[0]
    forced = bool(os.environ.get("RELEASE_FORCE"))

    latest = _latest_release_tag()
    if latest is None:  # couldn't reach the remote — don't silently disable the forward check
        msg = "could not determine the latest release (is gh installed and authenticated?)"
        if not forced:
            print(
                f"release-guard: blocked: {msg} — fix it, or set RELEASE_FORCE=1.", file=sys.stderr
            )
            return 1
        print(f"release-guard: override: {msg}", file=sys.stderr)
        latest = ""

    blocks, warnings = evaluate(version, latest, migrations.MIGRATIONS)
    for warning in warnings:
        print(f"release-guard: warning: {warning}", file=sys.stderr)
    for block in blocks:
        print(f"release-guard: {'override' if forced else 'blocked'}: {block}", file=sys.stderr)
    if blocks and not forced:
        print(
            "release-guard: refusing — fix the version, or set RELEASE_FORCE=1 to override.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
