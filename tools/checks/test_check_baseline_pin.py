"""Offline tests for check_baseline_pin: the vendored-copy/pin agreement logic."""

from __future__ import annotations

import json
import shutil
import tempfile
import typing
import unittest
from pathlib import Path

import check_baseline_pin


def _write_profile(root: Path, *, version: str = "1.2.3") -> Path:
    d = root / "prof"
    (d / "templates" / "docs").mkdir(parents=True)
    (d / "templates" / "docs" / "note.md").write_text("hi\n", encoding="utf-8")
    (d / "profile.json").write_text(
        json.dumps({"name": "base", "version": version, "description": "d"}),
        encoding="utf-8",
    )
    return d


def _write_pin(
    root: Path, *, tag: str = "v1.2.3", content_hash: str, url: str | None = None
) -> Path:
    p = root / "pin.json"
    p.write_text(
        json.dumps(
            {
                "name": "base",
                "repo": "https://example.invalid/base",
                "url": url or f"git+https://example.invalid/base.git@{tag}",
                "tag": tag,
                "content_hash": content_hash,
            }
        ),
        encoding="utf-8",
    )
    return p


class CheckBaselinePinTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self._old = (check_baseline_pin.PIN_PATH, check_baseline_pin.VENDORED)
        self.addCleanup(self._restore)
        self.vendored = _write_profile(self.tmp)
        from agent_native_setup import profiles

        self.hash = profiles.content_hash(profiles.load(self.vendored))
        check_baseline_pin.VENDORED = self.vendored

    def _restore(self) -> None:
        check_baseline_pin.PIN_PATH, check_baseline_pin.VENDORED = self._old

    def test_matching_pin_passes_offline(self) -> None:
        check_baseline_pin.PIN_PATH = _write_pin(self.tmp, content_hash=self.hash)
        self.assertEqual(check_baseline_pin.main(["--offline"]), 0)

    def test_hash_mismatch_fails(self) -> None:
        check_baseline_pin.PIN_PATH = _write_pin(self.tmp, content_hash="0" * 64)
        self.assertEqual(check_baseline_pin.main(["--offline"]), 1)

    def test_version_tag_mismatch_fails(self) -> None:
        check_baseline_pin.PIN_PATH = _write_pin(self.tmp, tag="v9.9.9", content_hash=self.hash)
        self.assertEqual(check_baseline_pin.main(["--offline"]), 1)

    def test_non_https_or_tagless_url_fails(self) -> None:
        for url in ("git+ssh://example.invalid/base.git@v1.2.3", "git+https://x.git@v0.0.0"):
            check_baseline_pin.PIN_PATH = _write_pin(self.tmp, content_hash=self.hash, url=url)
            self.assertEqual(check_baseline_pin.main(["--offline"]), 1)


class _FakeProfiles:
    """A stand-in for the profiles module, exercising _check_remote's branches offline."""

    class ProfileError(Exception): ...

    CACHE_ROOT = Path("/nonexistent")

    def __init__(self, *, hash_value: str | None):
        self._hash = hash_value  # None → resolve raises (fetch failure)
        self.cache_during_resolve: Path | None = None

    def resolve(self, url: str) -> object:
        self.cache_during_resolve = self.CACHE_ROOT
        if self._hash is None:
            raise self.ProfileError("clone failed")
        return object()

    def content_hash(self, _prof: object) -> str:
        return self._hash


class CheckRemoteTest(unittest.TestCase):
    """The network half — the check's primary purpose is noticing a moved tag."""

    PIN: typing.ClassVar[dict] = {
        "tag": "v1.2.3",
        "repo": "https://x",
        "url": "git+https://x.git@v1.2.3",
        "content_hash": "a" * 64,
    }

    def test_matching_remote_passes_and_uses_an_empty_cache(self) -> None:
        fake = _FakeProfiles(hash_value="a" * 64)
        self.assertEqual(check_baseline_pin._check_remote(fake, self.PIN), [])
        # The fetch must go through a throwaway cache — a warm ~/.cache would serve the
        # pinned (immutable) ref forever and a moved tag could never be observed.
        self.assertNotEqual(fake.cache_during_resolve, Path("/nonexistent"))
        self.assertEqual(fake.CACHE_ROOT, Path("/nonexistent"))  # restored after

    def test_moved_tag_is_reported(self) -> None:
        problems = check_baseline_pin._check_remote(_FakeProfiles(hash_value="b" * 64), self.PIN)
        self.assertEqual(len(problems), 1)
        self.assertIn("the tag moved or the pin is stale", problems[0])

    def test_fetch_failure_is_reported_not_raised(self) -> None:
        problems = check_baseline_pin._check_remote(_FakeProfiles(hash_value=None), self.PIN)
        self.assertEqual(len(problems), 1)
        self.assertIn("could not be fetched", problems[0])


if __name__ == "__main__":
    unittest.main()
