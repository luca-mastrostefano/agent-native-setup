"""Stage B (RFC 2026-07-05 §7-B): the default scaffold flows through the vendored flagship —
byte-identical output, builtin provenance, updates and the engine fold working end to end."""

from __future__ import annotations

import json
from pathlib import Path

from agent_native_setup import cli, update
from agent_native_setup.config import WizardConfig
from agent_native_setup.scaffold import Scaffolder

MANIFEST = ".agent-native-setup.json"


class _Console:
    def print(self, *a: object, **k: object) -> None: ...


def _tree(root: Path) -> dict[str, object]:
    out: dict[str, object] = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if rel == MANIFEST or rel.startswith(".git/"):
            continue
        out[rel] = (
            ("link", str(p.readlink()))
            if p.is_symlink()
            else (p.read_bytes() if p.is_file() else None)
        )
    return out


def test_default_scaffold_is_byte_identical_and_builtin_provenanced(tmp_path: Path) -> None:
    flipped = tmp_path / "flipped"
    rc = cli.main(["demo", "-o", str(flipped), "-y", "--no-git", "--languages", "python,node"])
    assert rc == 0
    # The pre-flip output: the generators, driven directly.
    legacy = tmp_path / "legacy"
    config = WizardConfig(
        project_name="demo",
        output_dir=legacy,
        languages=["python", "node"],
        init_git=False,
        first_run_banner=True,  # the CLI default (argparse), unlike the dataclass's
        is_git=False,
        os_name=__import__("platform").system().lower(),
    )
    cli.build(config, Scaffolder(legacy), None)
    assert _tree(flipped) == _tree(legacy)  # the stage-A gate, live in the real CLI

    m = json.loads((flipped / MANIFEST).read_text(encoding="utf-8"))
    assert m["profile"]["source"] == "builtin:agent-native-baseline"
    assert m["profile"]["extends"] is None  # the flagship is standalone
    assert m["profile"]["name"] == "agent-native-baseline"


def test_flipped_project_updates_cleanly(tmp_path: Path) -> None:
    target = tmp_path / "proj"
    assert cli.main(["demo", "-o", str(target), "-y", "--languages", "python"]) == 0
    import subprocess

    subprocess.run(["git", "add", "-A"], cwd=target, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=target,
        check=True,
        capture_output=True,
    )
    # Re-resolves builtin: provenance, replays answers, finds nothing to change.
    assert update.run(target, dry_run=True, console=_Console()) == 0


def test_answer_flag_targets_the_baseline_without_dash_dash_profile(tmp_path: Path) -> None:
    target = tmp_path / "proj"
    args = ["demo", "-o", str(target), "-y", "--no-git", "--languages", "python"]
    rc = cli.main([*args, "--answer", "runner=task"])
    assert rc == 0
    assert (target / "Taskfile.yml").is_file() and not (target / "Makefile").exists()
    m = json.loads((target / MANIFEST).read_text(encoding="utf-8"))
    assert m["profile"]["answers"]["runner"] == "task"  # replayed on update


def test_brownfield_fold_matches_the_generators(tmp_path: Path) -> None:
    # A repo with a real AGENTS.md and CLAUDE.md: both paths must fold identically.
    def seed(root: Path) -> None:
        root.mkdir()
        (root / "AGENTS.md").write_text("# Our old rules\nbe kind\n", encoding="utf-8")
        (root / "CLAUDE.md").write_text("claude notes\n", encoding="utf-8")

    flipped, legacy = tmp_path / "flipped", tmp_path / "legacy"
    seed(flipped), seed(legacy)
    assert cli.main(["demo", "-o", str(flipped), "-y", "--no-git", "--languages", "python"]) == 0
    config = WizardConfig(
        project_name="demo",
        output_dir=legacy,
        languages=["python"],
        init_git=False,
        first_run_banner=True,
        has_readme=False,
        has_agents_md=True,
        os_name=__import__("platform").system().lower(),
    )
    cli.build(config, Scaffolder(legacy), None)
    assert _tree(flipped) == _tree(legacy)
    merged = (flipped / "AGENTS.md").read_text(encoding="utf-8")
    assert "Preserved from your original AGENTS.md" in merged
    assert "Preserved from your original CLAUDE.md" in merged
    assert (flipped / "CLAUDE.md").is_symlink()
