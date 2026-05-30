"""Language auto-detection for scaffolding into an existing project."""

from __future__ import annotations

from pathlib import Path

from ai_setup.languages import detect_languages


def test_detects_by_marker_files(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (tmp_path / "package.json").write_text("{}\n")
    assert set(detect_languages(tmp_path)) == {"python", "node"}


def test_detects_by_extension_only(tmp_path: Path) -> None:
    (tmp_path / "main.rs").write_text("fn main() {}\n")
    assert detect_languages(tmp_path) == ["rust"]


def test_ignores_vendor_dirs(tmp_path: Path) -> None:
    vendored = tmp_path / "node_modules" / "pkg"
    vendored.mkdir(parents=True)
    (vendored / "lib.go").write_text("package main\n")
    assert detect_languages(tmp_path) == []


def test_missing_dir_returns_empty(tmp_path: Path) -> None:
    assert detect_languages(tmp_path / "does-not-exist") == []
