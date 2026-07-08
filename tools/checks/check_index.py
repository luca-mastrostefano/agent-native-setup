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


def _asset_equivalence(url: str, console) -> str | None:
    """The poisoning tripwire (RFC 2026-07-07): when a listed pinned GitHub entry publishes
    a release asset, fetch the entry through BOTH transports into throwaway caches and
    compare content hashes. Returns an error string on mismatch, ``None`` when equivalent
    or when no asset exists (clone-only entries are fine)."""
    import tempfile

    hashes: dict[str, str] = {}
    for transport in ("asset", "clone"):
        with tempfile.TemporaryDirectory() as tmp:
            old_root = profiles.CACHE_ROOT
            profiles.CACHE_ROOT = Path(tmp)
            try:
                root = profiles._fetch_git(url, console, transport=transport)
                hashes[transport] = profiles.content_hash(profiles.load(root))
            except profiles.ProfileError as exc:
                if transport == "asset":
                    if str(exc).startswith("no release asset"):
                        return None  # clone-only entry, nothing to compare
                    return (  # a refused (hostile) asset is itself the poisoning signal
                        f"asset transport refused: {exc} — possible poisoning. Delist the "
                        "entry and notify the author."
                    )
                return f"clone transport failed during equivalence check: {exc}"
            finally:
                profiles.CACHE_ROOT = old_root
    if hashes["asset"] != hashes["clone"]:
        return (
            f"asset != tag ({hashes['asset'][:12]}… vs {hashes['clone'][:12]}…): possible "
            "poisoning — the release asset does not match the tag's tree. Delist the entry "
            "and notify the author."
        )
    return None


def check_index(index_path: Path) -> int:
    from rich.console import Console  # a hard dep of the package — render markup, don't leak it

    entries = json.loads(index_path.read_text(encoding="utf-8"))["profiles"]
    console = Console()
    failures: list[str] = []
    for e in entries:
        name, url = e.get("name", "?"), e.get("url", "")
        try:
            # A content_hash is only stable for an immutable ref, so a git+ listing must pin an
            # @<tag> (RFC 2026-07-08 §1) — this also resolves community-index's open @ref
            # question. Real entries are always git+ (the offline unit tests use local-path
            # stand-ins, which have no ref to pin), so scope the pin check to git+ URLs.
            if url.startswith("git+"):
                _clone_url, ref, _subdir = profiles._parse_git_url(url)
                if not profiles._pinned(ref):
                    raise profiles.ProfileError(
                        f"url is not pinned to an immutable @<tag> (got ref {ref!r}) — a listing "
                        "must pin a tag so its content_hash is stable (append e.g. @v1.0.0)"
                    )
            prof = profiles.resolve(url, console=console)
            if prof is None:
                raise profiles.ProfileError("resolved to the built-in default")
            rc = profiles._validate(argparse.Namespace(path=str(prof.root)), console)
            if rc != 0:
                raise profiles.ProfileError("profile validate failed (see above)")
            if prof.name != name:
                raise profiles.ProfileError(
                    f"listed as {name!r} but the fetched profile.json says {prof.name!r} — "
                    "a listing must carry the profile's own name (possible impersonation "
                    "or a stale entry)"
                )
            # Declared == fetched (RFC 2026-07-08 §5): required for the canonical index, so a
            # force-moved tag / swapped asset fails CI instead of the next adopter. The message
            # prints the correct value so a stale entry is a copy-paste fix.
            declared = e.get("content_hash")
            actual = profiles.content_hash(prof)
            if not declared:
                raise profiles.ProfileError(
                    f'missing content_hash — add "content_hash": "{actual}" to the entry '
                    "(the vetted-bytes hash; `profile publish` emits it)"
                )
            if declared != actual:
                raise profiles.ProfileError(
                    f"content_hash mismatch: listed {str(declared)[:12]}… != fetched "
                    f"{actual[:12]}… — the tag moved or the entry is stale. Correct hash: {actual}"
                )
            if url.startswith("git+https://github.com/"):
                mismatch = _asset_equivalence(url, console)
                if mismatch:
                    raise profiles.ProfileError(mismatch)
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
