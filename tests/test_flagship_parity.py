"""Stage-A parity harness (RFC 2026-07-05 §7-A): the flagship profile must reproduce the
generators' output byte-for-byte before it can replace them.

The gate is **incremental**: ``PORTED`` is the set of output paths already extracted into
``profiles/agent-native-baseline/templates/``. For every matrix cell and every ported path,
either both trees contain identical bytes or both lack the file (absence parity — the
conditional-inclusion cases). Coverage is reported on every run; stage A completes when
``PORTED`` equals the full generated tree and the assertion flips to whole-tree equality.
The generators remain the source of truth until then (``build.py`` derives verbatim ported
files from their constants, so drift in either direction fails here).
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest

from agent_native_setup import cli, profiles
from agent_native_setup.config import WizardConfig
from agent_native_setup.generators import docs as docs_gen
from agent_native_setup.scaffold import Scaffolder

FLAGSHIP = Path(__file__).resolve().parent.parent / "profiles" / "agent-native-baseline"

# Output paths already extracted — grow this set file by file; never shrink it.
PORTED = {
    ".claude/README.md",
    ".claude/agents/planner.md",
    ".claude/agents/rfc-reviewer.md",
    ".claude/commands/review.md",
    ".claude/commands/rfc.md",
    ".claude/commands/update-agent-scaffolding.md",
    ".cursor/rules/agent-contract.mdc",
    ".editorconfig",
    ".git-blame-ignore-revs",
    ".gitattributes",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/copilot-instructions.md",
    "SECURITY.md",
    "docs/README.md",
    "docs/rfc/TEMPLATE.md",
    "tools/checks/docs_sync.py",
    "tools/checks/rfc_needed.py",
    "tools/checks/sync_rfc_status.py",
    "tools/checks/test_docs_sync.py",
    "tools/checks/test_rfc_needed.py",
    "tools/checks/test_sync_rfc_status.py",
    "tools/checks/test_tests_needed.py",
    "tools/checks/tests_needed.py",
}

# Paths the two trees legitimately never compare (provenance differs by design).
EXCLUDED = {".agent-native-setup.json"}

PINNED_DAY = "2026-01-01"


def _matrix() -> list[tuple[str, dict]]:
    """Config cells: languages x tools x part toggles x runner/adopt. Grows with coverage."""
    return [
        (
            "full",
            dict(
                languages=["python", "node"],
                ai_tools=["claude", "cursor", "copilot", "gemini"],
            ),
        ),
        (
            "lean",
            dict(
                languages=[],
                ai_tools=["claude"],
                include_docs=False,
                include_quality=False,
                include_ci=False,
                include_security=False,
            ),
        ),
        (
            "taskful",
            dict(
                languages=["python"], ai_tools=["claude", "gemini"], runner="task", adoption="full"
            ),
        ),
        (
            "brownfield",
            dict(languages=["node"], ai_tools=["claude", "copilot"], existing_project=True),
        ),
        (
            "no-agents",
            dict(languages=["go"], ai_tools=["cursor"], include_agents=False),
        ),
    ]


def _config(target: Path, **over: object) -> WizardConfig:
    base: dict = dict(
        project_name="demo",
        output_dir=target,
        description="a demo",
        languages=["python"],
        init_git=False,
    )
    base.update(over)
    return WizardConfig(**base)


def config_to_answers(config: WizardConfig) -> dict[str, object]:
    """The config -> answers translation (RFC 2026-07-05 §7-C, reified early): every recorded
    config choice maps onto a flagship prompt answer. This function becomes the migration
    table at stage C — keep it total over the choice surface."""
    return {
        "languages": list(config.languages),
        "tools": list(config.ai_tools),
        "include_agents": config.include_agents,
        "include_docs": config.include_docs,
        "include_quality": config.include_quality,
        "include_ci": config.include_ci,
        "include_security": config.include_security,
        "github_actions": config.use_github_actions,
        "hooks": config.git_hooks,
        "runner": config.runner,
        "adopt": config.adoption,
    }


def _tree(root: Path) -> dict[str, object]:
    """rel -> bytes for files, ('link', target) for symlinks."""
    out: dict[str, object] = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if rel in EXCLUDED or rel.startswith(".git/"):
            continue
        if p.is_symlink():
            out[rel] = ("link", str(p.readlink()))
        elif p.is_file():
            out[rel] = p.read_bytes()
    return out


def _pin_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Day(datetime.date):
        @classmethod
        def today(cls) -> "datetime.date":
            return datetime.date.fromisoformat(PINNED_DAY)

    monkeypatch.setattr(docs_gen, "date", _Day)


@pytest.mark.parametrize(("cell", "over"), _matrix())
def test_flagship_matches_generators_on_ported_files(
    cell: str, over: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_clock(monkeypatch)
    gen_dir, flag_dir = tmp_path / "gen", tmp_path / "flag"
    cli.build(_config(gen_dir, **over), Scaffolder(gen_dir), None)

    flagship = profiles.load(FLAGSHIP)
    config = _config(flag_dir, **over)
    cli.build(
        config,
        Scaffolder(flag_dir),
        flagship,
        answers=config_to_answers(config),
        profile_date=PINNED_DAY,
    )

    gen_tree, flag_tree = _tree(gen_dir), _tree(flag_dir)
    for rel in sorted(PORTED):
        in_gen, in_flag = rel in gen_tree, rel in flag_tree
        assert in_gen == in_flag, (
            f"[{cell}] {rel}: present in {'generators' if in_gen else 'flagship'} only"
        )
        if in_gen:
            assert gen_tree[rel] == flag_tree[rel], f"[{cell}] {rel}: bytes differ"

    covered = len([r for r in gen_tree if r in PORTED])
    print(f"[parity:{cell}] ported {covered}/{len(gen_tree)} generated files")


def test_flagship_profile_loads_and_validates() -> None:
    import argparse

    prof = profiles.load(FLAGSHIP)
    assert prof.standalone and prof.name == "agent-native-baseline"

    class _Console:
        text = ""

        def print(self, *a: object, **_k: object) -> None:
            self.text += " ".join(str(x) for x in a) + "\n"

    assert profiles._validate(argparse.Namespace(path=str(FLAGSHIP)), _Console()) == 0


def test_built_templates_are_current() -> None:
    """`build.py` output is committed — a generator-constant change without a rebuild fails
    here with the exact command to run."""
    import subprocess
    import sys
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "templates"
        import shutil

        shutil.copytree(FLAGSHIP / "templates", snapshot)
        subprocess.run(
            [sys.executable, str(FLAGSHIP / "build.py")], check=True, capture_output=True
        )
        current = {
            p.relative_to(FLAGSHIP / "templates").as_posix(): p.read_bytes()
            for p in (FLAGSHIP / "templates").rglob("*")
            if p.is_file()
        }
        snapped = {
            p.relative_to(snapshot).as_posix(): p.read_bytes()
            for p in snapshot.rglob("*")
            if p.is_file()
        }
        assert current == snapped, (
            "built templates are stale — run: python profiles/agent-native-baseline/build.py"
        )
