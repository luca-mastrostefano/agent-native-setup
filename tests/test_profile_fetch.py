"""Profile fetch (RFC 2026-07-04): resolve a profile from a git URL, on per-artifact content-hash
trust. A local git repo (`git+file://`, allowlisted for the test) stands in for a remote."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from agent_native_setup import cli, profiles, update
from agent_native_setup.config import WizardConfig
from agent_native_setup.scaffold import Scaffolder


class _Console:
    def __init__(self) -> None:
        self.text = ""

    def print(self, *args: object, **_kw: object) -> None:
        self.text += " ".join(str(a) for a in args) + "\n"


@pytest.fixture(autouse=True)
def _redirect_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep the cache, trust store, and user dir out of real ~/.config; allow file:// for the test.
    monkeypatch.setattr(profiles, "CACHE_ROOT", tmp_path / "cache")
    monkeypatch.setattr(profiles, "TRUST_STORE", tmp_path / "trusted.json")
    monkeypatch.setattr(profiles, "USER_PROFILE_DIR", tmp_path / "userprofiles")
    monkeypatch.setattr(profiles, "ALLOWED_TRANSPORTS", ("https", "ssh", "file"))


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _make_git_profile(root: Path, name: str, extra: dict | None = None) -> str:
    r = root / name
    (r / "templates" / "docs").mkdir(parents=True)
    pj = {
        "name": name,
        "version": "1.0.0",
        "description": "x",
        **(extra or {}),
    }
    (r / "profile.json").write_text(json.dumps(pj), encoding="utf-8")
    (r / "templates/docs/notes.md").write_text("hi\n", encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "add", "-A")
    _git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x")
    return f"git+file://{r}"


def _local_profile(root: Path, name: str, extra: dict | None = None) -> profiles.Profile:
    r = root / name
    (r / "templates").mkdir(parents=True)
    pj = {
        "name": name,
        "version": "1.0.0",
        "description": "x",
        **(extra or {}),
    }
    (r / "profile.json").write_text(json.dumps(pj), encoding="utf-8")
    (r / "templates/x.md").write_text("hi\n", encoding="utf-8")
    return profiles.load(r, source=str(r))  # a local path source → trusted provenance


# --- URL parsing / transport allowlist ------------------------------------------------------


def test_parse_url_splits_ref_and_subdir_without_ssh_ambiguity() -> None:
    assert profiles._parse_git_url("git+https://h/r.git@v1.2.0#subdir=team") == (
        "https://h/r.git",
        "v1.2.0",
        "team",
    )
    assert profiles._parse_git_url("git+ssh://git@h/r.git") == ("ssh://git@h/r.git", "", "")
    assert profiles._parse_git_url("git+ssh://git@h/r.git@v2") == ("ssh://git@h/r.git", "v2", "")


def test_rejects_ext_file_and_ftp_transports(monkeypatch: pytest.MonkeyPatch) -> None:
    # Restore the *production* allowlist (the fixture widened it for file:// clone tests) so the
    # file::/file:// rejection — a stated §1 mitigation — is actually exercised.
    monkeypatch.setattr(profiles, "ALLOWED_TRANSPORTS", ("https", "ssh"))
    with pytest.raises(profiles.ProfileError, match="expected git"):
        profiles._parse_git_url("git+ext::sh -c payload")  # no :// → rejected before git
    for url in ("git+file:///etc/x", "git+ftp://h/r.git"):
        with pytest.raises(profiles.ProfileError, match="transport"):
            profiles._parse_git_url(url)


def test_rejects_a_subdir_that_escapes_the_cache() -> None:
    with pytest.raises(profiles.ProfileError, match="subdir"):
        profiles._parse_git_url("git+https://h/r.git#subdir=../../../../etc")


def test_rejects_an_option_injecting_ref() -> None:
    with pytest.raises(profiles.ProfileError, match="ref"):
        profiles._parse_git_url("git+https://h/r.git@-bINJECT")


def test_offline_falls_back_to_the_cache(tmp_path: Path) -> None:
    repos = tmp_path / "repos"
    url = _make_git_profile(repos, "team")  # a moving ref (no @tag) → normally re-fetches
    assert profiles.resolve(url).name == "team"  # populates the cache
    shutil.rmtree(repos / "team")  # the "remote" is now unreachable
    console = _Console()
    assert profiles.resolve(url, console=console).name == "team"  # served from cache
    assert "cached copy" in console.text


# --- fetch + trust --------------------------------------------------------------------------


def test_fetch_and_load_a_git_profile(tmp_path: Path) -> None:
    url = _make_git_profile(tmp_path / "repos", "team")
    prof = profiles.resolve(url)
    assert prof is not None and prof.name == "team" and prof.source == url


def test_consent_safe_fetched_passes_freely(tmp_path: Path) -> None:
    prof = profiles.resolve(_make_git_profile(tmp_path / "repos", "team"))  # only .md → safe
    assert profiles.consent(prof, allow_code=False, interactive=False, console=_Console())


def test_consent_unsafe_fetched_gates_records_and_remembers(tmp_path: Path) -> None:
    url = _make_git_profile(tmp_path / "repos", "team", {"session_start": ["curl x | sh"]})
    prof = profiles.resolve(url)
    blocked = _Console()
    assert not profiles.consent(prof, allow_code=False, interactive=False, console=blocked)
    assert "code-carrying" in blocked.text and "curl x | sh" not in blocked.text  # reason, not cmd
    assert profiles.consent(prof, allow_code=True, interactive=False, console=_Console())  # consent
    assert profiles.content_hash(prof) in json.loads(profiles.TRUST_STORE.read_text())  # recorded
    assert profiles.consent(
        prof, allow_code=False, interactive=False, console=_Console()
    )  # remembered


def test_local_unsafe_profile_needs_no_consent(tmp_path: Path) -> None:
    prof = _local_profile(
        tmp_path / "local", "team", {"session_start": ["echo hi"]}
    )  # unsafe, local
    assert profiles.consent(prof, allow_code=False, interactive=False, console=_Console())


def test_content_hash_is_stable_and_change_sensitive(tmp_path: Path) -> None:
    a = _local_profile(tmp_path / "a", "p")
    b = _local_profile(tmp_path / "b", "p")
    assert profiles.content_hash(a) == profiles.content_hash(b)  # identical content → same hash
    (b.root / "templates/x.md").write_text("CHANGED\n", encoding="utf-8")
    changed = profiles.load(b.root, source=str(b.root))
    assert profiles.content_hash(changed) != profiles.content_hash(a)


def test_profile_add_installs_only_the_applied_surface(tmp_path: Path) -> None:
    repo = tmp_path / "repos" / "team"
    url = _make_git_profile(tmp_path / "repos", "team")
    (repo / "SCRATCH.md").write_text(
        "not part of the profile\n", encoding="utf-8"
    )  # top-level noise
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "scratch")

    assert (
        profiles._add(argparse.Namespace(url=url, name="myteam", allow_code=False), _Console()) == 0
    )
    dest = profiles.USER_PROFILE_DIR / "myteam"
    files = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())
    assert files == ["profile.json", "templates/docs/notes.md"]  # no SCRATCH.md, no .git/


def test_untrust_revokes_by_name(tmp_path: Path) -> None:
    url = _make_git_profile(tmp_path / "repos", "team", {"session_start": ["x"]})
    prof = profiles.resolve(url)
    profiles.consent(prof, allow_code=True, interactive=False, console=_Console())
    assert json.loads(profiles.TRUST_STORE.read_text())  # trusted
    assert profiles._untrust(argparse.Namespace(ref="team"), _Console()) == 0
    assert json.loads(profiles.TRUST_STORE.read_text()) == {}  # revoked


# --- update re-fetch + re-consent (RFC §6) --------------------------------------------------


def _config(target: Path) -> WizardConfig:
    return WizardConfig(
        project_name="demo", output_dir=target, languages=["python"], init_git=False
    )


def test_update_regates_when_a_fetched_profile_advances_to_unsafe(tmp_path: Path) -> None:
    repo = tmp_path / "repos" / "team"
    url = _make_git_profile(tmp_path / "repos", "team")  # scaffolds from a SAFE version
    target = tmp_path / "proj"
    target.mkdir()
    cli.build(_config(target), Scaffolder(target), profiles.resolve(url))
    _git(target, "init", "-q")
    _git(target, "add", "-A")
    _git(target, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "scaffold")

    # the moving ref advances to add a session_start hook → now unsafe
    d = json.loads((repo / "profile.json").read_text())
    d["version"], d["session_start"] = "1.1.0", ["curl x | sh"]
    (repo / "profile.json").write_text(json.dumps(d), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "add hook")

    assert update.run(target, dry_run=False, console=_Console()) == 2  # re-gated, not applied
    assert update.run(target, dry_run=False, console=_Console(), assume_yes=True) == 0  # consented
