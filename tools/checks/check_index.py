"""Check every community-index entry still resolves and validates (catches listing rot).

The committed ``contributions/index.json`` is a curated list of profile URLs
(RFC 2026-07-04-community-index). Shape is enforced offline by the unit tests; what they
can't catch is **rot** — a repo deleted or moved, a tag gone, a profile that no longer
loads. This script fetches each entry and runs the same load + strict-render validation as
``profile validate``, so a broken listing fails CI instead of failing the next adopter.

Run by ``.github/workflows/index-check.yml`` (weekly, on PRs touching ``contributions/``,
and on demand) and locally via ``task check-index`` — needs the network for git+ entries.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))  # find the package from a checkout (deps still needed)

from agent_native_setup import profiles  # noqa: E402


def check_index(index_path: Path) -> int:
    from rich.console import Console  # a hard dep of the package — render markup, don't leak it

    entries = json.loads(index_path.read_text(encoding="utf-8"))["profiles"]
    console = Console()
    failures: list[str] = []
    for e in entries:
        name, url = e.get("name", "?"), e.get("url", "")
        try:
            prof = profiles.resolve(url, console=console)
            if prof is None:
                raise profiles.ProfileError("resolved to the built-in default")
            rc = profiles._validate(argparse.Namespace(path=str(prof.root)), console)
            if rc != 0:
                raise profiles.ProfileError("profile validate failed (see above)")
            print(f"ok: {name} ({prof.name} {prof.version})")
        except profiles.ProfileError as exc:
            failures.append(f"{name}: {exc}")
            print(f"BROKEN: {name}: {exc}")
    if failures:
        print(f"\n{len(failures)}/{len(entries)} listed profile(s) no longer resolve+validate —")
        print("fix or remove the entries above from contributions/index.json.")
        return 1
    print(f"\nall {len(entries)} listed profile(s) resolve and validate.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--index",
        default=str(REPO_ROOT / "contributions" / "index.json"),
        help="index file to check (default: the committed one)",
    )
    args = p.parse_args(argv)
    return check_index(Path(args.index))


if __name__ == "__main__":
    sys.exit(main())
