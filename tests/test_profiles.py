"""Profiles (RFC 2026-06-23): resolve/validate a profile, overlay it on the default scaffold
(managed by default, seed when listed), record it in the manifest, and refresh its managed
files on update when the profile ships a new version."""

from __future__ import annotations

import json
import shutil
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
    seed: tuple[str, ...] = (),
    onboarding: tuple[str, ...] = (),
    session_start: tuple[str, ...] = (),
    by_path: bool = False,
) -> profiles.Profile:
    d = root / name
    (d / "templates").mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "name": name,
        "version": version,
        "extends": extends,
        "description": "x",
    }
    if seed:
        manifest["seed"] = list(seed)
    if onboarding:
        manifest["onboarding"] = list(onboarding)
    if session_start:
        manifest["session_start"] = list(session_start)
    (d / "profile.json").write_text(json.dumps(manifest), encoding="utf-8")
    for rel, content in files.items():
        p = d / "templates" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    # by_path records a real path source, so `update` can re-resolve the profile.
    return profiles.load(d, source=str(d) if by_path else name)


def _bump_profile(
    pdir: Path,
    *,
    version: str,
    files: dict[str, str] | None = None,
    session_start: list[str] | None = None,
) -> None:
    """Mutate a profile dir in place to simulate the author shipping a new version."""
    data = json.loads((pdir / "profile.json").read_text(encoding="utf-8"))
    data["version"] = version
    if session_start is not None:
        data["session_start"] = session_start
    (pdir / "profile.json").write_text(json.dumps(data), encoding="utf-8")
    for rel, content in (files or {}).items():
        p = pdir / "templates" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


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


def test_apply_overrides_a_base_managed_file(tmp_path: Path) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    config = _config(target)
    sc = Scaffolder(target)
    cli.build(config, sc)  # default scaffold — INSTRUCTION.md is managed

    prof = _make_profile(tmp_path, "team", {"INSTRUCTION.md": "# Team method\n"})
    profiles.apply(prof, config, sc)

    assert (target / "INSTRUCTION.md").read_text(encoding="utf-8") == "# Team method\n"  # wins
    assert "INSTRUCTION.md" not in sc.seed  # managed by default → refreshed from the profile


def test_apply_marks_managed_and_seed_files(tmp_path: Path) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    config = _config(target)
    sc = Scaffolder(target)
    cli.build(config, sc)

    prof = _make_profile(
        tmp_path, "team", {"managed.md": "m\n", "once.md": "o\n"}, seed=("once.md",)
    )
    profiles.apply(prof, config, sc)

    assert "managed.md" in sc.recorded and "managed.md" not in sc.seed  # refreshed on update
    assert "once.md" in sc.seed  # listed in `seed` → write-once


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


def test_build_with_profile_records_the_block_and_owned_files(tmp_path: Path) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    config = _config(target)
    prof = _make_profile(tmp_path, "team", {".claude/agents/team.md": "# team\n"})
    cli.build(config, Scaffolder(target), prof)

    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    block = m["profile"]
    assert {k: block[k] for k in ("name", "version", "extends", "source")} == prof.manifest_block()
    assert block["files"] == [".claude/agents/team.md"]  # exactly what the profile owns
    assert ".claude/agents/team.md" in m["files"]
    assert ".claude/agents/team.md" not in m["seed"]  # managed by default (refreshed on update)
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


def test_update_preserves_the_profile_block_and_files(tmp_path: Path) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    config = _config(target)
    prof = _make_profile(tmp_path, "team", {".claude/agents/team.md": "# team\n"}, by_path=True)
    cli.build(config, Scaffolder(target), prof)
    _commit(target)

    assert update.run(target, dry_run=False, console=_Console()) == 0

    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert m["profile"]["name"] == "team"  # block survives the update
    assert (
        ".claude/agents/team.md" in m["profile"]["files"] and ".claude/agents/team.md" in m["files"]
    )
    assert (target / ".claude/agents/team.md").read_text(
        encoding="utf-8"
    ) == "# team\n"  # untouched


def test_update_keeps_a_profile_override_of_a_base_managed_file(tmp_path: Path) -> None:
    # A profile that overrides a base *managed* file (INSTRUCTION.md) must keep its content on
    # update — the base must NOT refresh back over it (the profile re-applies and wins).
    target = tmp_path / "proj"
    target.mkdir()
    config = _config(target)
    prof = _make_profile(tmp_path, "team", {"INSTRUCTION.md": "# Team method\n"}, by_path=True)
    cli.build(config, Scaffolder(target), prof)
    assert (target / "INSTRUCTION.md").read_text(encoding="utf-8") == "# Team method\n"
    _commit(target)

    assert update.run(target, dry_run=False, console=_Console()) == 0
    assert (target / "INSTRUCTION.md").read_text(encoding="utf-8") == "# Team method\n"  # kept
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert "INSTRUCTION.md" in m["profile"]["files"] and "INSTRUCTION.md" not in m["seed"]


def test_update_does_not_accumulate_stale_default_seed_for_a_profiled_project(
    tmp_path: Path,
) -> None:
    # Regression: the overlay restore must touch ONLY profile-owned files, not the whole seed
    # set — else a renamed default seed file (the date-stamped bootstrap RFC) is wrongly carried
    # into the manifest on a cross-date update, accruing a stale entry every time.
    target = tmp_path / "proj"
    target.mkdir()
    prof = _make_profile(tmp_path, "team", {"x.md": "x\n"}, by_path=True)
    cli.build(_config(target), Scaffolder(target), prof)
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
    assert "x.md" in nm["files"]  # the profile overlay IS still preserved (managed)


# --- Phase 2: the profile-update path -------------------------------------------------------


def test_update_refreshes_a_managed_profile_file_on_a_compatible_bump(tmp_path: Path) -> None:
    # The headline: ship a new (compatible) profile version, and `update` pulls the new file.
    prof = _make_profile(tmp_path, "team", {"docs/house.md": "v1\n"}, version="0.1.0", by_path=True)
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    _commit(target)

    _bump_profile(prof.root, version="0.1.1", files={"docs/house.md": "v2\n"})  # same 0.1 series
    assert update.run(target, dry_run=False, console=_Console()) == 0

    assert (target / "docs/house.md").read_text(encoding="utf-8") == "v2\n"  # refreshed
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert m["profile"]["version"] == "0.1.1"  # new version recorded


def test_update_refreshes_a_profile_override_of_a_base_seed_file(tmp_path: Path) -> None:
    # Regression: a profile can *manage* a file the base ships as seed (e.g. README.md). The
    # managed overlay must clear the base's seed mark, or a new profile version never refreshes.
    prof = _make_profile(
        tmp_path, "team", {"README.md": "team v1\n"}, version="0.1.0", by_path=True
    )
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert "README.md" not in m["seed"]  # the managed overlay overrode the base seed mark
    assert "README.md" in m["profile"]["files"]
    _commit(target)

    _bump_profile(prof.root, version="0.1.1", files={"README.md": "team v2\n"})
    assert update.run(target, dry_run=False, console=_Console()) == 0
    assert (target / "README.md").read_text(
        encoding="utf-8"
    ) == "team v2\n"  # refreshed, not frozen


def test_update_reports_an_edited_profile_file_as_a_conflict(tmp_path: Path) -> None:
    # A profile file the user edited is never clobbered — it's surfaced as a conflict instead.
    prof = _make_profile(tmp_path, "team", {"docs/house.md": "v1\n"}, version="0.1.0", by_path=True)
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    (target / "docs/house.md").write_text("my own edit\n", encoding="utf-8")
    _commit(target)

    _bump_profile(prof.root, version="0.1.1", files={"docs/house.md": "v2\n"})
    console = _Console()
    assert update.run(target, dry_run=False, console=console) == 0
    assert (target / "docs/house.md").read_text(encoding="utf-8") == "my own edit\n"  # kept
    assert "docs/house.md" in console.text  # surfaced for the user to reconcile


def test_update_does_not_refresh_a_seed_profile_file(tmp_path: Path) -> None:
    # A file listed in the profile's `seed` is write-once — a new version does NOT touch it.
    prof = _make_profile(
        tmp_path,
        "team",
        {"starter.md": "v1\n"},
        version="0.1.0",
        seed=("starter.md",),
        by_path=True,
    )
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    _commit(target)

    _bump_profile(prof.root, version="0.1.1", files={"starter.md": "v2\n"})
    assert update.run(target, dry_run=False, console=_Console()) == 0
    assert (target / "starter.md").read_text(encoding="utf-8") == "v1\n"  # frozen, not refreshed


def test_a_breaking_profile_bump_gates_then_proceeds_with_yes(tmp_path: Path) -> None:
    prof = _make_profile(tmp_path, "team", {"docs/house.md": "v1\n"}, version="1.0.0", by_path=True)
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    _commit(target)

    _bump_profile(prof.root, version="2.0.0", files={"docs/house.md": "v2\n"})  # breaking (major)
    console = _Console()
    assert update.run(target, dry_run=False, console=console, assume_yes=False) == 2  # refused
    assert "needs confirmation" in console.text and "profile team 1.0.0 → 2.0.0" in console.text
    assert (target / "docs/house.md").read_text(encoding="utf-8") == "v1\n"  # nothing changed

    assert update.run(target, dry_run=False, console=_Console(), assume_yes=True) == 0  # confirmed
    assert (target / "docs/house.md").read_text(encoding="utf-8") == "v2\n"


def test_update_degrades_when_the_profile_cannot_be_re_resolved(tmp_path: Path) -> None:
    # If the profile source is gone at update time, the base still updates and the profile's
    # files are kept frozen, with a warning — not a crash, not a silent drop.
    prof = _make_profile(tmp_path, "team", {"docs/house.md": "v1\n"}, version="0.1.0", by_path=True)
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    _commit(target)

    shutil.rmtree(prof.root)  # the profile directory no longer exists
    console = _Console()
    assert update.run(target, dry_run=False, console=console) == 0
    assert "couldn't be re-resolved" in console.text  # warned
    assert (target / "docs/house.md").read_text(encoding="utf-8") == "v1\n"  # kept frozen
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert m["profile"]["name"] == "team"  # provenance preserved


# --- Phase 3: profile-contributed startup (onboarding + SessionStart hooks) -----------------


def _session_hooks(target: Path) -> list[str]:
    s = json.loads((target / ".claude/settings.json").read_text(encoding="utf-8"))
    return [h["command"] for h in s["hooks"]["SessionStart"][0]["hooks"]]


def test_load_validates_session_start_is_a_string_list(tmp_path: Path) -> None:
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "profile.json").write_text(
        json.dumps(
            {"name": "x", "version": "1.0.0", "extends": "default", "session_start": "echo"}
        ),
        encoding="utf-8",
    )
    with pytest.raises(profiles.ProfileError, match="session_start"):
        profiles.load(bad)


def test_profile_onboarding_steps_fold_into_onboarding_md(tmp_path: Path) -> None:
    prof = _make_profile(tmp_path, "team", {}, onboarding=("Run `task team-setup`.", "Join #eng."))
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)

    body = (target / "ONBOARDING.md").read_text(encoding="utf-8")
    assert "Run `task team-setup`." in body and "Join #eng." in body
    assert body.index("task team-setup") < body.index("Delete this file")  # before the cleanup step
    # ONBOARDING.md is transient — never recorded, so update can't resurrect it after onboarding.
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert "ONBOARDING.md" not in m["files"]


def test_profile_session_start_hooks_append_to_settings(tmp_path: Path) -> None:
    prof = _make_profile(tmp_path, "team", {}, session_start=("echo team-reminder",))
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)

    hooks = _session_hooks(target)
    assert hooks[-1] == "echo team-reminder"  # appended after the built-in hooks
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert m["profile"]["session_start"] == [
        "echo team-reminder"
    ]  # recorded (for degraded updates)


def test_update_refreshes_changed_session_start_hooks(tmp_path: Path) -> None:
    prof = _make_profile(
        tmp_path, "team", {}, version="0.1.0", session_start=("echo v1",), by_path=True
    )
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    _commit(target)

    _bump_profile(prof.root, version="0.1.1", session_start=["echo v2"])
    assert update.run(target, dry_run=False, console=_Console()) == 0
    hooks = _session_hooks(target)
    assert "echo v2" in hooks and "echo v1" not in hooks  # refreshed to the new hook


def test_session_start_without_claude_warns_instead_of_silently_dropping(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # SessionStart hooks need Claude's .claude/ config; targeting only cursor means there's
    # nowhere to put them — so warn rather than record hooks that never run.
    prof = _make_profile(tmp_path, "team", {}, session_start=("echo x",), by_path=True)
    target = tmp_path / "proj"
    rc = cli.main(
        [
            "demo",
            "-o",
            str(target),
            "-y",
            "--no-git",
            "--tools",
            "cursor",
            "--profile",
            str(prof.root),
        ]
    )
    assert rc == 0
    assert "session_start hooks" in capsys.readouterr().out  # warned
    assert not (target / ".claude/settings.json").exists()  # no Claude settings to hold them


def test_degraded_update_keeps_session_start_hooks(tmp_path: Path) -> None:
    # If the profile is gone at update time, its recorded hooks must survive — the base must not
    # regenerate settings.json *without* them.
    prof = _make_profile(
        tmp_path, "team", {}, version="0.1.0", session_start=("echo keepme",), by_path=True
    )
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    _commit(target)

    shutil.rmtree(prof.root)  # profile source gone
    console = _Console()
    assert update.run(target, dry_run=False, console=console) == 0
    assert "couldn't be re-resolved" in console.text
    assert "echo keepme" in _session_hooks(target)  # NOT stripped by the base refresh


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
