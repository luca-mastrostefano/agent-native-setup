"""Offline tests for check_baseline_pin: the vendored-copy/pin agreement logic."""

from __future__ import annotations

import json
import shutil
import tempfile
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


if __name__ == "__main__":
    unittest.main()
