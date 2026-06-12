"""The tests-needed commit-msg hook: a source change must stage a test or a waiver."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "checks" / "tests_needed.py"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "tester")
    src = tmp_path / "src" / "pkg"
    src.mkdir(parents=True)
    (src / "app.py").write_text("x = 1\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def run_hook(repo: Path, message: str) -> int:
    msg = repo / "COMMIT_MSG"
    msg.write_text(message, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(msg)], cwd=repo, capture_output=True, text=True
    ).returncode


def _change_src(repo: Path) -> None:
    (repo / "src" / "pkg" / "app.py").write_text("x = 2\n")
    git(repo, "add", "src/pkg/app.py")


def test_source_change_without_test_fails(repo: Path) -> None:
    _change_src(repo)
    assert run_hook(repo, "feat: change x") == 1


def test_source_change_with_staged_test_passes(repo: Path) -> None:
    _change_src(repo)
    test = repo / "tests" / "test_app.py"
    test.parent.mkdir()
    test.write_text("def test_x() -> None:\n    assert True\n")
    git(repo, "add", "tests/test_app.py")
    assert run_hook(repo, "feat: change x") == 0


def test_waiver_passes(repo: Path) -> None:
    _change_src(repo)
    assert run_hook(repo, "chore: rename\n\nTests-Not-Needed: mechanical rename") == 0


def test_doc_change_does_not_fire(repo: Path) -> None:
    (repo / "README.md").write_text("hi\n")
    git(repo, "add", "README.md")
    assert run_hook(repo, "docs: readme") == 0


def test_pure_deletion_does_not_fire(repo: Path) -> None:
    git(repo, "rm", "-q", "src/pkg/app.py")
    assert run_hook(repo, "chore: drop app") == 0
