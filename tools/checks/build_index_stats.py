#!/usr/bin/env python3
"""Precompute the community-index stats sidecar (RFC 2026-07-07-profile-releases-and-stats).

For every GitHub-hosted index entry, query the public API for stars and the summed
``download_count`` of ``agent-native-profile.tar.gz`` assets across all releases (the
ordering metric), and write ``contributions/stats.json``. Run daily by the
``index-stats`` workflow, which publishes the file to the data-only ``stats`` branch —
display data only; a listing's stats grant no trust.

Usage: ``python tools/checks/build_index_stats.py [--index PATH] [--out PATH]``.
Failures per entry degrade to omitted fields; a wholly unreachable API exits non-zero so
the daily run is visibly red rather than silently publishing an empty file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ASSET_NAME = "agent-native-profile.tar.gz"
_REPO_RE = re.compile(r"^git\+https://github\.com/([^/]+/[^/#@]+?)(?:\.git)?(?:@[^#]*)?(?:#.*)?$")


def _api(path: str) -> object:
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Accept": "application/vnd.github+json",
            **(
                {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"}
                if os.environ.get("GITHUB_TOKEN")
                else {}
            ),
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read(5_000_000))


def stats_for(repo: str) -> dict:
    out: dict = {}
    info = _api(f"/repos/{repo}")
    if isinstance(info, dict) and isinstance(info.get("stargazers_count"), int):
        out["stars"] = info["stargazers_count"]
    if isinstance(info, dict) and isinstance(info.get("forks_count"), int):
        out["forks"] = info["forks_count"]  # a fork = someone extending the profile
    releases = _api(f"/repos/{repo}/releases?per_page=100")
    if isinstance(releases, list):
        out["downloads"] = sum(
            a.get("download_count", 0)
            for r in releases
            if isinstance(r, dict)
            for a in r.get("assets", [])
            if isinstance(a, dict) and a.get("name") == ASSET_NAME
        )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--index", default="contributions/index.json")
    ap.add_argument("--out", default="contributions/stats.json")
    args = ap.parse_args(argv)

    entries = json.loads(Path(args.index).read_text(encoding="utf-8"))["profiles"]
    profiles: dict[str, dict] = {}
    failures = 0
    for e in entries:
        m = _REPO_RE.match(str(e.get("url", "")))
        if not m:
            continue  # non-GitHub host — no public stats available
        try:
            profiles[str(e["name"])] = stats_for(m.group(1))
            print(f"{e['name']}: {profiles[str(e['name'])]}")
        except Exception as exc:  # per-entry degradation, visible in the log
            failures += 1
            print(f"WARN {e['name']}: {exc}", file=sys.stderr)
    if entries and not profiles and failures:
        print("no stats could be computed — API unreachable?", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"profiles": profiles}, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(profiles)} profile(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
