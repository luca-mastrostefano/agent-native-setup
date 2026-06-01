"""The docs-sync commit-msg hook: a new component must touch arch docs or waive."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "checks" / "docs_sync.py"

_spec = importlib.util.spec_from_file_location("docs_sync", SCRIPT)
assert _spec and _spec.loader
docs_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(docs_sync)


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "tester")
    (tmp_path / "README.md").write_text("init\n")
    git(tmp_path, "add", "README.md")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def run_hook(repo: Path, message: str) -> int:
    msg = repo / "COMMIT_MSG"
    msg.write_text(message, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(msg)], cwd=repo, capture_output=True, text=True
    ).returncode


def _add_package(repo: Path, name: str = "widget") -> None:
    pkg = repo / "src" / name / "__init__.py"
    pkg.parent.mkdir(parents=True)
    pkg.write_text("")
    git(repo, "add", "src")


def test_new_package_without_doc_fails(repo: Path) -> None:
    _add_package(repo)
    assert run_hook(repo, "feat: widget") == 1


def test_new_package_with_arch_doc_passes(repo: Path) -> None:
    _add_package(repo)
    arch = repo / "docs" / "architecture" / "overview.md"
    arch.parent.mkdir(parents=True)
    arch.write_text("# Architecture\n\n## Components\n- widget\n")
    git(repo, "add", "docs")
    assert run_hook(repo, "feat: widget") == 0


def test_new_package_with_waiver_passes(repo: Path) -> None:
    _add_package(repo)
    assert run_hook(repo, "feat: widget\n\nDocs-Not-Needed: internal helper") == 0


def test_subpackage_does_not_fire(repo: Path) -> None:
    sub = repo / "src" / "widget" / "sub" / "__init__.py"
    sub.parent.mkdir(parents=True)
    sub.write_text("")
    git(repo, "add", "src")
    assert run_hook(repo, "feat: subpackage") == 0


def test_editing_existing_code_does_not_fire(repo: Path) -> None:
    core = repo / "src" / "widget" / "core.py"
    core.parent.mkdir(parents=True)
    (repo / "src" / "widget" / "__init__.py").write_text("")
    core.write_text("x = 1\n")
    git(repo, "add", "src")
    git(repo, "commit", "-q", "-m", "add widget")
    core.write_text("x = 2\n")
    git(repo, "add", str(core))
    assert run_hook(repo, "fix: tweak widget") == 0


def test_clean_commit_passes(repo: Path) -> None:
    (repo / "notes.md").write_text("hi\n")
    git(repo, "add", "notes.md")
    assert run_hook(repo, "docs: notes") == 0


def test_find_triggers_only_fires_on_top_level_adds() -> None:
    changes = [
        ("A", "src/widget/__init__.py"),
        ("A", "src/widget/sub/__init__.py"),
        ("M", "src/other/__init__.py"),
        ("A", "src/foo/core.py"),
    ]
    assert docs_sync.find_triggers(changes) == ["new top-level src package (widget)"]
