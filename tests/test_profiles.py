"""Profiles (RFC 2026-06-23, Phase 1): resolve/validate a profile, overlay it as seed on the
default scaffold, record it in the manifest, and preserve it across an update."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agent_native_setup import cli, profiles, update
from agent_native_setup.config import WizardConfig
from agent_native_setup.manifest import MANIFEST_PATH
from agent_native_setup.scaffold import Scaffolder


class _Console:
    def __init__(self) -> None:
        self.text = ""

    def print(self, *args: object, **_kw: object) -> None:
        self.text += " ".join(str(a) for a in args) + "\n"


def _make_profile(
    root: Path,
    name: str,
    files: dict[str, str],
    *,
    version: str = "1.0.0",
    extends: str = "default",
) -> profiles.Profile:
    d = root / name
    (d / "templates").mkdir(parents=True)
    (d / "profile.json").write_text(
        json.dumps({"name": name, "version": version, "extends": extends, "description": "x"}),
        encoding="utf-8",
    )
    for rel, content in files.items():
        p = d / "templates" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return profiles.load(d, source=name)


def _config(target: Path) -> WizardConfig:
    return WizardConfig(
        project_name="demo", output_dir=target, languages=["python"], init_git=False
    )


# --- resolve / load -------------------------------------------------------------------------


def test_resolve_default_is_none_and_missing_errors(tmp_path: Path) -> None:
    assert profiles.resolve("default") is None
    assert profiles.resolve("") is None
    with pytest.raises(profiles.ProfileError, match="not found"):
        profiles.resolve(str(tmp_path / "nope"))


def test_load_requires_name_version_and_supported_extends(tmp_path: Path) -> None:
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "profile.json").write_text(json.dumps({"name": "x"}), encoding="utf-8")  # no version
    with pytest.raises(profiles.ProfileError, match="required"):
        profiles.load(bad)
    (bad / "profile.json").write_text(
        json.dumps({"name": "x", "version": "1.0.0", "extends": None}), encoding="utf-8"
    )  # extends: null → standalone, not supported in Phase 1
    with pytest.raises(profiles.ProfileError, match="supported"):
        profiles.load(bad)


def test_resolve_from_user_dir_by_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(profiles, "USER_PROFILE_DIR", tmp_path / "profiles")
    _make_profile(tmp_path / "profiles", "team", {"docs/x.md": "hi\n"})
    resolved = profiles.resolve("team")
    assert resolved is not None and resolved.name == "team" and resolved.source == "team"


# --- overlay / apply ------------------------------------------------------------------------


def test_apply_overrides_a_base_managed_file_and_makes_it_seed(tmp_path: Path) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    config = _config(target)
    sc = Scaffolder(target)
    cli.build(config, sc)  # default scaffold — INSTRUCTION.md is managed
    assert "INSTRUCTION.md" in sc.recorded and "INSTRUCTION.md" not in sc.seed

    prof = _make_profile(tmp_path, "team", {"INSTRUCTION.md": "# Team method\n"})
    profiles.apply(prof, config, sc)

    assert (target / "INSTRUCTION.md").read_text(encoding="utf-8") == "# Team method\n"
    assert "INSTRUCTION.md" in sc.seed  # the child claimed it → now seed, not refreshed on update


def test_apply_renders_j2_and_ships_other_files_verbatim(tmp_path: Path) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    config = _config(target)
    sc = Scaffolder(target)
    cli.build(config, sc)

    prof = _make_profile(
        tmp_path,
        "team",
        {
            "docs/team.md.j2": "project={{ project_name }}\n",  # rendered, .j2 stripped
            ".github/workflows/team.yml": "run: ${{ secrets.TOKEN }}\n",  # must stay verbatim
        },
    )
    profiles.apply(prof, config, sc)

    assert (target / "docs/team.md").read_text(encoding="utf-8") == "project=demo\n"
    assert not (target / "docs/team.md.j2").exists()  # the .j2 suffix is stripped
    # A literal ${{ ... }} survives because non-.j2 files are not run through Jinja.
    assert (target / ".github/workflows/team.yml").read_text(encoding="utf-8") == (
        "run: ${{ secrets.TOKEN }}\n"
    )


def test_overlay_leaves_a_preexisting_user_file_alone(tmp_path: Path) -> None:
    # A file that pre-existed the scaffold is the user's — overlay must not clobber it (no force).
    target = tmp_path / "proj"
    target.mkdir()
    (target / "keep.md").write_text("user content\n", encoding="utf-8")
    sc = Scaffolder(target)
    sc.overlay("keep.md", "profile content\n")
    assert (target / "keep.md").read_text(encoding="utf-8") == "user content\n"
    assert "keep.md" in sc.skipped and "keep.md" not in sc.seed
    # With --force, the profile overlay wins and is recorded as seed.
    forced = Scaffolder(target, force=True)
    forced.overlay("keep.md", "profile content\n")
    assert (target / "keep.md").read_text(encoding="utf-8") == "profile content\n"
    assert "keep.md" in forced.seed


# --- integration: build + manifest + update -------------------------------------------------


def test_build_with_profile_records_block_and_seeds_overlay(tmp_path: Path) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    config = _config(target)
    prof = _make_profile(tmp_path, "team", {".claude/agents/team.md": "# team\n"})
    cli.build(config, Scaffolder(target), prof)

    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    block = m["profile"]
    assert {k: block[k] for k in ("name", "version", "extends", "source")} == prof.manifest_block()
    assert block["files"] == [".claude/agents/team.md"]  # exactly what the profile owns
    assert ".claude/agents/team.md" in m["seed"]
    assert (target / ".claude/agents/team.md").read_text(encoding="utf-8") == "# team\n"


def _git(target: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-C",
            str(target),
            "-c",
            "user.email=t@e",
            "-c",
            "user.name=t",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        check=True,
        capture_output=True,
    )


def _commit(target: Path) -> None:
    _git(target, "init", "-q")
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "baseline", "--no-verify")


def test_update_preserves_the_profile_block_and_overlaid_seed(tmp_path: Path) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    config = _config(target)
    prof = _make_profile(tmp_path, "team", {".claude/agents/team.md": "# team\n"})
    cli.build(config, Scaffolder(target), prof)
    _commit(target)

    assert update.run(target, dry_run=False, console=_Console()) == 0

    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert m["profile"]["name"] == "team"  # block survives the update
    assert ".claude/agents/team.md" in m["profile"]["files"]
    assert ".claude/agents/team.md" in m["seed"]  # overlay carried forward, not dropped
    assert (target / ".claude/agents/team.md").read_text(
        encoding="utf-8"
    ) == "# team\n"  # untouched


def test_update_keeps_a_profile_override_of_a_base_managed_file(tmp_path: Path) -> None:
    # A profile that overrides a base *managed* file (INSTRUCTION.md) must keep its content on
    # update — the base must NOT refresh back over it (the override is now seed/child-owned).
    target = tmp_path / "proj"
    target.mkdir()
    config = _config(target)
    prof = _make_profile(tmp_path, "team", {"INSTRUCTION.md": "# Team method\n"})
    cli.build(config, Scaffolder(target), prof)
    assert (target / "INSTRUCTION.md").read_text(encoding="utf-8") == "# Team method\n"
    _commit(target)

    assert update.run(target, dry_run=False, console=_Console()) == 0
    assert (target / "INSTRUCTION.md").read_text(encoding="utf-8") == "# Team method\n"  # kept
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert "INSTRUCTION.md" in m["seed"] and "INSTRUCTION.md" in m["profile"]["files"]


def test_update_does_not_accumulate_stale_default_seed_for_a_profiled_project(
    tmp_path: Path,
) -> None:
    # Regression: the overlay restore must touch ONLY profile-owned files, not the whole seed
    # set — else a renamed default seed file (the date-stamped bootstrap RFC) is wrongly carried
    # into the manifest on a cross-date update, accruing a stale entry every time.
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), _make_profile(tmp_path, "team", {"x.md": "x\n"}))
    # Simulate an earlier scaffold: re-date the bootstrap RFC on disk + in the manifest.
    rfc_dir = target / "docs/rfc/active"
    [boot] = list(rfc_dir.glob("*-adopt-agent-native-setup.md"))
    new_rel, old_rel = f"docs/rfc/active/{boot.name}", "docs/rfc/active/2026-01-01-adopt.md"
    (target / old_rel).write_text(boot.read_text(encoding="utf-8"), encoding="utf-8")
    boot.unlink()
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    m["files"][old_rel] = m["files"].pop(new_rel)
    m["seed"] = [old_rel if s == new_rel else s for s in m["seed"]]
    (target / MANIFEST_PATH).write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
    _commit(target)

    assert update.run(target, dry_run=False, console=_Console()) == 0
    nm = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    adopts = [f for f in nm["files"] if f.endswith("-adopt.md") or "adopt-agent-native" in f]
    assert len(adopts) == 1  # exactly one bootstrap RFC tracked — no stale carry-forward
    assert "x.md" in nm["seed"]  # the profile overlay IS still preserved


# --- authoring CLI --------------------------------------------------------------------------


def test_profile_init_scaffolds_a_skeleton(tmp_path: Path) -> None:
    assert cli.main(["profile", "init", "myteam", "-o", str(tmp_path)]) == 0
    root = tmp_path / "myteam"
    manifest = json.loads((root / "profile.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "myteam" and manifest["extends"] == "default"
    assert (root / "templates").is_dir() and (root / "README.md").exists()
    # It's immediately loadable as a (empty) profile.
    assert profiles.load(root).name == "myteam"
    # Re-running onto an existing dir refuses rather than clobbering.
    assert cli.main(["profile", "init", "myteam", "-o", str(tmp_path)]) == 2


def test_profile_list_reports_user_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(profiles, "USER_PROFILE_DIR", tmp_path / "profiles")
    assert cli.main(["profile", "list"]) == 0
    assert "No profiles" in capsys.readouterr().out
    _make_profile(tmp_path / "profiles", "team", {"docs/x.md": "hi\n"})
    assert cli.main(["profile", "list"]) == 0
    assert "team" in capsys.readouterr().out


def test_scaffold_with_unknown_profile_exits_2(tmp_path: Path) -> None:
    rc = cli.main(["demo", "-o", str(tmp_path / "out"), "-y", "--no-git", "--profile", "nope"])
    assert rc == 2
    assert not (tmp_path / "out" / "AGENTS.md").exists()  # nothing scaffolded on a bad profile
