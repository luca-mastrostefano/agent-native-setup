#!/usr/bin/env python3
"""Verify the vendored flagship matches its pinned release (RFC 2026-07-05 §5, stage B3).

The engine ships a vendored copy of ``agent-native-baseline`` in the wheel; its canonical
home is the profile's own repo, pinned by ``profiles/baseline-pin.json`` (tag + content
hash). Three things must agree, or the trust story ("installing the tool is consenting to
exactly the reviewed, tagged artifact") silently breaks:

1. the **vendored copy**'s content hash equals the pin's ``content_hash`` (offline — also
   asserted by the test suite);
2. the **pinned tag**, fetched from the profile repo, loads/validates and hashes to the
   same value (network — run by the ``index-check`` workflow and ``task check-baseline``);
3. the pin's ``url`` is a ``git+https`` ref carrying the pin's ``tag``.

Run from the repo root: ``python tools/checks/check_baseline_pin.py`` (``--offline`` skips
the fetch).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PIN_PATH = Path("profiles/baseline-pin.json")
VENDORED = Path("profiles/agent-native-baseline")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--offline", action="store_true", help="skip fetching the pinned tag")
    args = ap.parse_args(argv)

    from agent_native_setup import profiles  # after arg parsing, so --help works anywhere

    pin = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    problems: list[str] = []

    if not pin["url"].startswith("git+https://") or f"@{pin['tag']}" not in pin["url"]:
        problems.append(f"pin url {pin['url']!r} is not a git+https ref of tag {pin['tag']!r}")

    local = profiles.load(VENDORED)
    local_hash = profiles.content_hash(local)
    if local_hash != pin["content_hash"]:
        problems.append(
            f"vendored copy hash {local_hash[:12]}… != pinned {pin['content_hash'][:12]}… — "
            "re-tag the profile repo and update profiles/baseline-pin.json together"
        )
    if f"v{local.version}" != pin["tag"]:
        problems.append(f"vendored version {local.version} does not match pin tag {pin['tag']}")

    if not args.offline and not problems:
        problems += _check_remote(profiles, pin)

    if problems:
        for p in problems:
            print(f"BROKEN: {p}")
        print("\nthe vendored baseline and its pin disagree — fix before releasing.")
        return 1
    scope = "offline checks" if args.offline else "vendored copy, pin, and tagged artifact"
    print(f"baseline pin OK ({scope}): {pin['tag']} = {pin['content_hash'][:12]}…")
    return 0


def _check_remote(profiles, pin: dict) -> list[str]:
    """Fetch the pinned tag and compare — through an **empty cache**, or a pinned (immutable)
    ref would be served from `~/.cache` forever and "the tag moved" (this check's whole
    purpose) could never be observed on a warm machine (review of B3)."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        old_root = profiles.CACHE_ROOT
        profiles.CACHE_ROOT = Path(tmp)
        try:
            remote = profiles.resolve(pin["url"])
            assert remote is not None
            remote_hash = profiles.content_hash(remote)
        except profiles.ProfileError as exc:
            return [f"pinned tag could not be fetched/loaded: {exc}"]
        finally:
            profiles.CACHE_ROOT = old_root
    if remote_hash != pin["content_hash"]:
        return [
            f"pinned tag {pin['tag']} at {pin['repo']} hashes to {remote_hash[:12]}… "
            f"!= pinned {pin['content_hash'][:12]}… — the tag moved or the pin is stale"
        ]
    return []


if __name__ == "__main__":
    sys.exit(main())
