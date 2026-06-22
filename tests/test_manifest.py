"""The provenance manifest (.agent-native-setup.json) records what generated a project."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agent_native_setup import cli
from agent_native_setup.config import WizardConfig
from agent_native_setup.manifest import MANIFEST_PATH
from agent_native_setup.scaffold import Scaffolder


def _build(tmp_path: Path, **overrides: object) -> Path:
    config = WizardConfig(project_name="demo", output_dir=tmp_path, init_git=False, **overrides)
    cli.build(config, Scaffolder(config.target))
    return tmp_path


def _manifest(root: Path) -> dict:
    return json.loads((root / MANIFEST_PATH).read_text(encoding="utf-8"))


def test_manifest_records_version_and_resolved_config(tmp_path: Path) -> None:
    m = _manifest(_build(tmp_path, languages=["python"], runner="make"))
    assert m["scaffolder"] == "agent-native-setup"
    assert isinstance(m["version"], str) and m["version"]  # whatever __version__ reports
    cfg = m["config"]
    assert cfg["languages"] == ["python"]
    assert cfg["runner"] == "make"
    assert cfg["include_docs"] is True
    assert cfg["project_name"] == "demo"


def test_manifest_file_fingerprint_matches_disk(tmp_path: Path) -> None:
    root = _build(tmp_path, languages=["python"])
    m = _manifest(root)
    rel = ".claude/agents/code-reviewer.md"  # a regenerable, wizard-owned file
    assert rel in m["files"]
    on_disk = (root / rel).read_text(encoding="utf-8").encode("utf-8")
    assert m["files"][rel] == "sha256:" + hashlib.sha256(on_disk).hexdigest()


def test_manifest_records_symlink_target_not_a_hash(tmp_path: Path) -> None:
    # CLAUDE.md is a symlink to AGENTS.md; the manifest records the target, not bytes.
    m = _manifest(_build(tmp_path, languages=["python"], ai_tools=["claude"]))
    assert m["files"]["CLAUDE.md"] == "symlink:AGENTS.md"


def test_manifest_records_the_merged_agents_md(tmp_path: Path) -> None:
    # When AGENTS.md is folded into an existing one, that bypasses sc.write — it must
    # still be fingerprinted, and the fingerprint must match the merged bytes on disk.
    (tmp_path / "AGENTS.md").write_text("# Existing contract\n", encoding="utf-8")
    root = _build(tmp_path, languages=["python"])
    m = _manifest(root)
    on_disk = (root / "AGENTS.md").read_text(encoding="utf-8").encode("utf-8")
    assert m["files"]["AGENTS.md"] == "sha256:" + hashlib.sha256(on_disk).hexdigest()


def test_manifest_does_not_list_itself(tmp_path: Path) -> None:
    m = _manifest(_build(tmp_path, languages=["python"]))
    assert MANIFEST_PATH not in m["files"]


def test_transient_onboarding_files_are_created_but_not_recorded(tmp_path: Path) -> None:
    # ONBOARDING.md and the /onboard command self-delete during onboarding, so the
    # baseline must not list them — else a later update would resurrect what the user
    # deliberately removed. They're still written to disk; just kept out of the manifest.
    root = _build(tmp_path, languages=["python"])
    assert (root / "ONBOARDING.md").exists()
    assert (root / ".claude/commands/onboard.md").exists()
    m = _manifest(root)
    assert "ONBOARDING.md" not in m["files"]
    assert ".claude/commands/onboard.md" not in m["files"]
    assert ".claude/commands/review.md" in m["files"]  # a permanent command still is


def test_skipped_file_is_not_recorded(tmp_path: Path) -> None:
    # We only own what we wrote: a pre-existing file we skip (no --force) must not get a
    # fingerprint, or a future update would clobber a file the wizard never generated.
    (tmp_path / "README.md").write_text("my own readme\n", encoding="utf-8")
    m = _manifest(_build(tmp_path, languages=["python"]))
    assert "README.md" not in m["files"]  # preserved, skipped → not ours


def test_force_records_the_new_content_not_the_original(tmp_path: Path) -> None:
    # A wizard-owned file that pre-exists and is force-overwritten must be fingerprinted
    # with the NEW bytes, so update reads it as pristine-from-this-run, not stale.
    rel = ".editorconfig"  # wizard-owned, written unconditionally, not preserve
    (tmp_path / rel).write_text("# stale\n", encoding="utf-8")
    config = WizardConfig(
        project_name="demo", output_dir=tmp_path, init_git=False, languages=["python"]
    )
    cli.build(config, Scaffolder(config.target, force=True))
    m = _manifest(tmp_path)
    on_disk = (tmp_path / rel).read_text(encoding="utf-8")
    assert on_disk != "# stale\n"  # actually overwritten
    assert m["files"][rel] == "sha256:" + hashlib.sha256(on_disk.encode("utf-8")).hexdigest()


def test_seed_lists_user_owned_files_update_must_not_refresh(tmp_path: Path) -> None:
    # The `seed` set tells `update` which generated files the user owns once written —
    # preserve=True files (README, .gitignore) plus the seed=True ones (the architecture
    # overview, the backlog, the dated bootstrap RFC). Refreshing any would clobber the
    # user's content.
    m = _manifest(_build(tmp_path, languages=["python"]))
    seed = set(m["seed"])
    assert "README.md" in seed  # preserve=True
    assert ".gitignore" in seed  # preserve=True
    assert "docs/architecture/overview.md" in seed  # seed=True
    assert "docs/improvements.md" in seed  # seed=True
    assert any(p.endswith("-adopt-agent-native-setup.md") for p in seed)  # dated bootstrap RFC


def test_managed_files_are_not_seed(tmp_path: Path) -> None:
    # The enforcement scripts, the agent library, and the RFC template are "managed":
    # absent from `seed`, so update refreshes them (that's the whole point — fixes
    # propagate). The symlinked contracts are managed too.
    m = _manifest(_build(tmp_path, languages=["python"], ai_tools=["claude"]))
    seed = set(m["seed"])
    assert "tools/checks/sync_rfc_status.py" not in seed
    assert ".claude/agents/code-reviewer.md" not in seed
    assert "docs/rfc/TEMPLATE.md" not in seed  # improve the template → it propagates
    assert "CLAUDE.md" not in seed  # a symlink — managed


def test_seed_is_a_subset_of_recorded_files(tmp_path: Path) -> None:
    # Every seed path must also be a recorded file: update reads its fingerprint to know
    # whether it's pristine, and a seed entry with no fingerprint would be meaningless.
    m = _manifest(_build(tmp_path, languages=["python"]))
    assert set(m["seed"]) <= set(m["files"])


def test_preexisting_preserve_file_is_not_seed(tmp_path: Path) -> None:
    # A preserve=True file that already existed is skipped, so it's never recorded — and
    # therefore never listed as seed (we only own, and only track, what we wrote).
    (tmp_path / "README.md").write_text("my own readme\n", encoding="utf-8")
    m = _manifest(_build(tmp_path, languages=["python"]))
    assert "README.md" not in m["files"]
    assert "README.md" not in m["seed"]


def test_manifest_always_written_even_for_a_bare_scaffold(tmp_path: Path) -> None:
    # Provenance accrues for any scaffold, not just full ones.
    root = _build(
        tmp_path,
        languages=["python"],
        include_agents=False,
        include_docs=False,
        include_quality=False,
        include_ci=False,
    )
    m = _manifest(root)
    assert "AGENTS.md" in m["files"]  # the contract is always written, so always recorded
    assert m["config"]["include_ci"] is False
