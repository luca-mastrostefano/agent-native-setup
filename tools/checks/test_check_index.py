"""check_index: a listed profile that no longer resolves or validates fails the check."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import check_index


def _write_index(root: Path, entries: list[dict]) -> Path:
    idx = root / "index.json"
    idx.write_text(json.dumps({"profiles": entries}), encoding="utf-8")
    return idx


def _write_profile(root: Path, name: str, *, template: str = "hi\n") -> Path:
    d = root / name
    (d / "templates" / "docs").mkdir(parents=True)
    (d / "templates" / "docs" / "note.md.j2").write_text(template, encoding="utf-8")
    (d / "profile.json").write_text(
        json.dumps({"name": name, "version": "1.0.0", "extends": "default", "description": "d"}),
        encoding="utf-8",
    )
    return d


class CheckIndexTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_an_entry_without_a_url_fails(self) -> None:
        # resolve("") is the built-in default — a listing that names nothing is broken, not ok.
        idx = _write_index(self.tmp, [{"name": "hollow"}])
        self.assertEqual(check_index.main(["--index", str(idx)]), 1)

    def test_valid_entries_pass(self) -> None:
        # Local-path entries keep the test offline; git+ entries exercise the same resolve().
        prof = _write_profile(self.tmp, "good")
        idx = _write_index(self.tmp, [{"name": "good", "url": str(prof)}])
        self.assertEqual(check_index.main(["--index", str(idx)]), 0)

    def test_a_dead_url_fails(self) -> None:
        idx = _write_index(self.tmp, [{"name": "gone", "url": str(self.tmp / "missing")}])
        self.assertEqual(check_index.main(["--index", str(idx)]), 1)

    def test_a_profile_that_no_longer_validates_fails(self) -> None:
        # Resolves fine, but a template references an undefined variable — strict render catches
        # the rot exactly like `profile validate`.
        prof = _write_profile(self.tmp, "stale", template="{{ no_such_variable.oops }}\n")
        idx = _write_index(self.tmp, [{"name": "stale", "url": str(prof)}])
        self.assertEqual(check_index.main(["--index", str(idx)]), 1)

    def test_one_broken_entry_fails_even_among_good_ones(self) -> None:
        good = _write_profile(self.tmp, "good")
        idx = _write_index(
            self.tmp,
            [
                {"name": "good", "url": str(good)},
                {"name": "gone", "url": str(self.tmp / "missing")},
            ],
        )
        self.assertEqual(check_index.main(["--index", str(idx)]), 1)


if __name__ == "__main__":
    unittest.main()
