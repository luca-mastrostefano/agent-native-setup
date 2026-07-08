#!/usr/bin/env python3
"""Verify the baseline pin against its release and the test fixture (RFC 2026-07-08).

The engine no longer vendors ``agent-native-baseline``; it fetches the pinned URL and
verifies the bytes against ``profiles/baseline-pin.json`` (tag + content hash) at runtime.
Its canonical home is the profile's own repo. Three things must agree, or the trust story
("the default scaffold is exactly the reviewed, tagged artifact") silently breaks:

1. the **test fixture** (``tests/fixtures/agent-native-baseline`` — what the suite runs
   against) hashes to the pin's ``content_hash``, so the fixture can't drift from the pinned
   release the engine actually fetches (offline — also asserted by the test suite);
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
FIXTURE = Path("tests/fixtures/agent-native-baseline")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--offline", action="store_true", help="skip fetching the pinned tag")
    args = ap.parse_args(argv)

    from agent_native_setup import profiles  # after arg parsing, so --help works anywhere

    pin = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    problems: list[str] = []

    if not pin["url"].startswith("git+https://") or f"@{pin['tag']}" not in pin["url"]:
        problems.append(f"pin url {pin['url']!r} is not a git+https ref of tag {pin['tag']!r}")

    local = profiles.load(FIXTURE)
    local_hash = profiles.content_hash(local)
    if local_hash != pin["content_hash"]:
        problems.append(
            f"fixture hash {local_hash[:12]}… != pinned {pin['content_hash'][:12]}… — "
            "re-sync tests/fixtures/agent-native-baseline with the pinned release "
            "(and re-tag + bump the pin together if the templates changed)"
        )
    if f"v{local.version}" != pin["tag"]:
        problems.append(f"fixture version {local.version} does not match pin tag {pin['tag']}")

    # The pin duplicates the baseline's own `transient` set (RFC 2026-07-08 §4) so `profile
    # save` can exclude first-run files without fetching the baseline. That copy is outside the
    # hashed surface (content_hash covers profile.json + templates/, not the pin), so guard it
    # here — else a release could bump the hash+tag but leave `transient` stale, and `save`
    # would silently snapshot a self-deleting file.
    if sorted(pin.get("transient", [])) != sorted(local.transient):
        problems.append(
            f"pin 'transient' {sorted(pin.get('transient', []))} != fixture transient "
            f"{sorted(local.transient)} — re-sync the pin's transient list with the release"
        )

    if not args.offline and not problems:
        problems += _check_remote(profiles, pin)

    if problems:
        for p in problems:
            print(f"BROKEN: {p}")
        print("\nthe baseline fixture/tag and its pin disagree — fix before releasing.")
        return 1
    scope = "offline checks" if args.offline else "fixture, pin, and tagged artifact"
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
