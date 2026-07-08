"""Stage B (RFC 2026-07-05 §7-B): the default scaffold flows through the flagship (fetched by
pin, RFC 2026-07-08) — byte-identical output, builtin provenance, updates + fold end to end."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
    assert "extends" not in m["profile"]  # the field is gone from the format
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


def test_update_never_clobbers_folded_content(tmp_path: Path) -> None:
    # Review of #55 finding 1: a fold target is implicitly seed, so update's clean-tree
    # regeneration can't reclassify it as managed and refresh away the preserved content.
    import subprocess

    target = tmp_path / "proj"
    target.mkdir()
    (target / "AGENTS.md").write_text("# precious team rules\n", encoding="utf-8")
    assert cli.main(["demo", "-o", str(target), "-y", "--languages", "python"]) == 0
    merged = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert "precious team rules" in merged
    subprocess.run(["git", "add", "-A"], cwd=target, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i"],
        cwd=target,
        check=True,
        capture_output=True,
    )
    assert update.run(target, dry_run=False, console=_Console()) == 0
    assert (target / "AGENTS.md").read_text(encoding="utf-8") == merged  # fold survives


def test_greenfield_composed_profile_never_folds_its_own_base(tmp_path: Path) -> None:
    # Review of #55 finding 2: files the SAME run's base layer wrote are superseded, not
    # "preserved" — the fold keys on genuinely pre-existing files only.
    import json as _json

    d = tmp_path / "team"
    (d / "templates").mkdir(parents=True)
    (d / "templates" / "AGENTS.md").write_text("team contract\n", encoding="utf-8")
    (d / "profile.json").write_text(
        _json.dumps(
            {
                "name": "team",
                "version": "1.0.0",
                "links": {"CLAUDE.md": "AGENTS.md"},
            }
        ),
        encoding="utf-8",
    )
    target = tmp_path / "proj"
    args = ["demo", "-o", str(target), "-y", "--no-git", "--languages", "python"]
    rc = cli.main([*args, "--profile", str(d)])
    assert rc == 0
    agents = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert agents == "team contract\n"  # superseded cleanly
    assert "Preserved from your original" not in agents


def test_interrupt_after_fold_restores_the_users_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Review of #55 finding 3: the fold snapshots what it overwrites/unlinks, so rollback
    # puts the user's AGENTS.md and CLAUDE.md back byte-for-byte.
    target = tmp_path / "proj"
    target.mkdir()
    (target / "AGENTS.md").write_text("# precious team rules\n", encoding="utf-8")
    (target / "CLAUDE.md").write_text("claude memory\n", encoding="utf-8")

    real_write = cli.manifest.write

    def boom(*a: object, **k: object) -> None:  # last step of build → everything else ran
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.manifest, "write", boom)
    rc = cli.main(["demo", "-o", str(target), "-y", "--no-git", "--languages", "python"])
    monkeypatch.setattr(cli.manifest, "write", real_write)
    assert rc == 130
    assert (target / "AGENTS.md").read_text(encoding="utf-8") == "# precious team rules\n"
    assert (target / "CLAUDE.md").read_text(encoding="utf-8") == "claude memory\n"
    assert not (target / "CLAUDE.md").is_symlink()
