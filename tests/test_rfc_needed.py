"""The rfc-needed commit-msg hook: structural change must carry an RFC or waiver."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "checks" / "rfc_needed.py"

PYPROJECT_BASE = """\
[project]
name = "demo"
dependencies = [
    "questionary>=2.0",
]
"""

_spec = importlib.util.spec_from_file_location("rfc_needed", SCRIPT)
assert _spec and _spec.loader
rfc_needed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rfc_needed)


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "tester")
    (tmp_path / "pyproject.toml").write_text(PYPROJECT_BASE)
    git(tmp_path, "add", "pyproject.toml")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def run_hook(repo: Path, message: str) -> int:
    msg = repo / "COMMIT_MSG"
    msg.write_text(message, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(msg)], cwd=repo, capture_output=True, text=True
    ).returncode


def _add_dep(repo: Path, spec: str = "requests>=2") -> None:
    path = repo / "pyproject.toml"
    path.write_text(
        path.read_text().replace('"questionary>=2.0",', f'"questionary>=2.0",\n    "{spec}",')
    )
    git(repo, "add", "pyproject.toml")


def test_dependency_add_without_rfc_fails(repo: Path) -> None:
    _add_dep(repo)
    assert run_hook(repo, "feat: add requests") == 1


def test_dependency_add_with_waiver_passes(repo: Path) -> None:
    _add_dep(repo)
    assert run_hook(repo, "feat: add requests\n\nRFC-Not-Needed: tooling-only helper") == 0


def test_dependency_add_with_staged_rfc_passes(repo: Path) -> None:
    _add_dep(repo)
    rfc = repo / "docs" / "rfc" / "current" / "2026-06-01-requests.md"
    rfc.parent.mkdir(parents=True)
    rfc.write_text("# Use requests\n\n- **Status:** Accepted\n")
    git(repo, "add", str(rfc))
    assert run_hook(repo, "feat: add requests") == 0


def test_version_bump_does_not_fire(repo: Path) -> None:
    path = repo / "pyproject.toml"
    path.write_text(path.read_text().replace("questionary>=2.0", "questionary>=2.1"))
    git(repo, "add", "pyproject.toml")
    assert run_hook(repo, "chore: bump questionary") == 0


def test_architecture_change_fires(repo: Path) -> None:
    arch = repo / "docs" / "architecture" / "overview.md"
    arch.parent.mkdir(parents=True)
    arch.write_text("# Architecture\n")
    git(repo, "add", str(arch))
    assert run_hook(repo, "docs: architecture") == 1


def test_new_top_level_src_package_fires(repo: Path) -> None:
    pkg = repo / "src" / "widget" / "__init__.py"
    pkg.parent.mkdir(parents=True)
    pkg.write_text("")
    git(repo, "add", str(pkg))
    assert run_hook(repo, "feat: new package") == 1


def test_subpackage_does_not_fire(repo: Path) -> None:
    sub = repo / "src" / "widget" / "sub" / "__init__.py"
    sub.parent.mkdir(parents=True)
    sub.write_text("")
    git(repo, "add", str(sub))
    assert run_hook(repo, "feat: subpackage") == 0


def test_clean_commit_passes(repo: Path) -> None:
    (repo / "README.md").write_text("hi\n")
    git(repo, "add", "README.md")
    assert run_hook(repo, "docs: readme") == 0


def test_dep_names_normalizes_and_strips_specifiers() -> None:
    text = (
        "[project]\n"
        'dependencies = ["Foo_Bar>=1.0", "baz[extra]~=2", "qux ; python_version<\'3.11\'"]\n'
    )
    assert rfc_needed.dep_names(text) == {"foo-bar", "baz", "qux"}
