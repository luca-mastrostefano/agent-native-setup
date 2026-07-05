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
import json
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
    "CLAUDE.md",
    "GEMINI.md",
    "CONTRIBUTING.md",
    "INSTRUCTION.md",
    ".claude/agents/code-reviewer.md",
    ".claude/commands/onboard.md",
    "README.md",
    "docs/architecture/overview.md",
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
        # Discriminator cells: each flips ONE conjunct of a compound gate that every other
        # cell leaves co-varying, so a wrong gate translation cannot pass the matrix.
        (
            "bare-tools",  # claude present but agents off; ci on but GHA off; quality on but
            # security off; docs on but no dependabot language (html)
            dict(
                languages=["html"],
                ai_tools=["claude"],
                include_agents=False,
                include_security=False,
                use_github_actions=False,
            ),
        ),
        (
            "legacy-no-quality",  # existing repo but quality off -> no blame-ignore-revs
            dict(languages=["python"], existing_project=True, include_quality=False),
        ),
        (
            "gemini-only",  # the gemini-only nested-symlink-note variant
            dict(languages=["python"], ai_tools=["gemini"]),
        ),
        (
            "open-ci",  # gha on with security off -> the plain CI tooling bullet
            dict(languages=["node"], include_security=False),
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


def test_built_templates_are_current(tmp_path: Path) -> None:
    """`build.py` output is committed — a generator-constant change without a rebuild fails
    here with the exact command to run. Builds into a scratch dir: the working tree is never
    mutated, so the failure signal is repeatable and parallel-safe."""
    import subprocess
    import sys

    out = tmp_path / "templates"
    proc = subprocess.run(
        [sys.executable, str(FLAGSHIP / "build.py"), "--out", str(out)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"build.py failed:\n{proc.stderr}"
    fresh = {p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob("*") if p.is_file()}
    committed_root = FLAGSHIP / "templates"
    committed = {
        p.relative_to(committed_root).as_posix(): p.read_bytes()
        for p in committed_root.rglob("*")
        if p.is_file()
    }
    # Every built file must exist, byte-identical, in the committed tree (hand-written .j2
    # templates may exist beyond the built set; orphans of RENAMED build outputs are caught
    # because build.py owns every path it ever emitted via the committed build manifest).
    for rel, content in fresh.items():
        assert rel in committed, f"built template {rel} is not committed — run build.py"
        assert committed[rel] == content, (
            f"{rel} is stale — run: python profiles/agent-native-baseline/build.py"
        )
    built_list = json.loads((FLAGSHIP / ".built-manifest.json").read_text(encoding="utf-8"))
    assert sorted(fresh) == sorted(built_list), (
        "build manifest out of date — run: python profiles/agent-native-baseline/build.py"
    )
    for rel in built_list:
        assert rel in fresh, f"orphaned built template {rel} — removed from PORTS but committed"
