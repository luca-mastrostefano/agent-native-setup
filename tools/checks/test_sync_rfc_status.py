"""Tests for the rfc-status folder-sync helper (stdlib unittest)."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

_HELPER = Path(__file__).resolve().parent / "sync_rfc_status.py"
_spec = importlib.util.spec_from_file_location("sync_rfc_status", _HELPER)
assert _spec and _spec.loader
sync_rfc_status = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync_rfc_status)


def _rfc(status: str) -> str:
    return f"# Title\n\n- **Status:** {status}\n"


class ParseStatus(unittest.TestCase):
    def test_reads_status_keyword(self) -> None:
        self.assertEqual(sync_rfc_status.parse_status(_rfc("Accepted")), "accepted")

    def test_missing_status_is_none(self) -> None:
        self.assertIsNone(sync_rfc_status.parse_status("# Title\n"))


class TargetFolder(unittest.TestCase):
    def test_known_statuses_map_to_folders(self) -> None:
        self.assertEqual(sync_rfc_status.target_folder("proposed"), "current")
        self.assertEqual(sync_rfc_status.target_folder("done"), "done")
        self.assertEqual(sync_rfc_status.target_folder("superseded"), "superseded")

    def test_unknown_status_is_none(self) -> None:
        self.assertIsNone(sync_rfc_status.target_folder("draft"))


class FindMoves(unittest.TestCase):
    def test_flags_rfc_sitting_in_the_wrong_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "current").mkdir()
            (root / "done").mkdir()
            (root / "current" / "a.md").write_text(_rfc("Done"))
            (root / "current" / "b.md").write_text(_rfc("Accepted"))
            moves = sync_rfc_status.find_moves(root)
            expected = (root / "current" / "a.md", root / "done" / "a.md")
            self.assertEqual(moves, [expected])


if __name__ == "__main__":
    unittest.main()
