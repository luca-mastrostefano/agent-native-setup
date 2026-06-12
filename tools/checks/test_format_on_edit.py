"""Tests for the format-on-edit hook helper (stdlib unittest)."""

import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_HELPER = Path(__file__).resolve().parent / "format_on_edit.py"
_spec = importlib.util.spec_from_file_location("format_on_edit", _HELPER)
assert _spec and _spec.loader
format_on_edit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(format_on_edit)

EXT, CMD = sorted(format_on_edit.FORMATTERS.items())[0]


class FormatCommand(unittest.TestCase):
    def test_known_extension_gets_formatter_plus_path(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=EXT) as f:
            with mock.patch.object(format_on_edit.shutil, "which", lambda _: "/bin/x"):
                cmd = format_on_edit.format_command(f.name)
        self.assertEqual(cmd, [*CMD, f.name])

    def test_unknown_extension_is_skipped(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".nope") as f:
            self.assertIsNone(format_on_edit.format_command(f.name))

    def test_missing_file_is_skipped(self) -> None:
        self.assertIsNone(format_on_edit.format_command("no/such/file" + EXT))

    def test_missing_formatter_binary_is_skipped(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=EXT) as f:
            with mock.patch.object(format_on_edit.shutil, "which", lambda _: None):
                self.assertIsNone(format_on_edit.format_command(f.name))


class Main(unittest.TestCase):
    def test_bad_json_on_stdin_still_exits_zero(self) -> None:
        with mock.patch.object(format_on_edit.sys, "stdin", io.StringIO("{nope")):
            self.assertEqual(format_on_edit.main(), 0)

    def test_event_without_file_path_exits_zero(self) -> None:
        with mock.patch.object(format_on_edit.sys, "stdin", io.StringIO("{}")):
            self.assertEqual(format_on_edit.main(), 0)


if __name__ == "__main__":
    unittest.main()
