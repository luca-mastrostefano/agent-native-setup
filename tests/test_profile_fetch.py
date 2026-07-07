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


# --- release-asset transport (RFC 2026-07-07-profile-releases-and-stats) --------------------


def _tar_bytes(members: dict[str, bytes], **kw: object) -> bytes:
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _good_asset() -> bytes:
    return _tar_bytes(
        {
            "profile.json": b'{"name": "assetprof", "version": "1.0.0", "description": "d"}',
            "templates/docs/x.md": b"hi\n",
        }
    )


def _serve(monkeypatch: pytest.MonkeyPatch, payload: bytes) -> list[str]:
    """Fake urllib for _try_release_asset; records requested URLs."""
    import io
    import urllib.request

    urls: list[str] = []

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a: object) -> None: ...

    def fake_urlopen(url, timeout=None):
        urls.append(str(url))
        return _Resp(payload)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return urls


def test_asset_transport_preferred_for_pinned_github_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    urls = _serve(monkeypatch, _good_asset())

    def no_git(*a: object, **k: object):
        raise AssertionError("clone must not run when the asset succeeds")

    monkeypatch.setattr(profiles.subprocess, "run", no_git)
    root = profiles._fetch_git("git+https://github.com/acme/prof.git@v1.0.0", _Console())
    assert (root / "profile.json").is_file() and (root / "templates/docs/x.md").is_file()
    assert urls == [
        "https://github.com/acme/prof/releases/download/v1.0.0/agent-native-profile.tar.gz"
    ]
    # Pinned → cached forever: a second resolve touches neither network nor git.
    urls.clear()
    root2 = profiles._fetch_git("git+https://github.com/acme/prof.git@v1.0.0", _Console())
    assert root2 == root and urls == []


def test_asset_transport_skipped_for_branches_subdirs_and_other_hosts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[str] = []
    monkeypatch.setattr(profiles, "_try_release_asset", lambda *a, **k: called.append("x") or False)
    for spec in (
        "git+https://github.com/acme/prof.git@main",  # moving ref
        "git+https://gitlab.com/acme/prof.git@v1.0.0",  # other host (checked inside helper)
        "git+https://github.com/acme/mono.git@v1.0.0#subdir=p",  # monorepo
    ):
        with pytest.raises(profiles.ProfileError):
            profiles._fetch_git(spec, _Console(), transport="asset")
    # branch + subdir never even consult the asset path; the host check lives in the helper
    assert len(called) == 1  # only the gitlab case reached the helper


def test_asset_falls_back_to_clone_on_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error
    import urllib.request

    def raise_404(url, timeout=None):
        raise urllib.error.HTTPError(str(url), 404, "nf", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", raise_404)
    src = _make_git_profile(tmp_path, "fallback")  # git+file:// → helper rejects host, clone wins
    prof = profiles.resolve(src, console=_Console())
    assert prof is not None and prof.name == "fallback"


def test_traversal_asset_errors_loudly_and_writes_nothing_outside(tmp_path: Path) -> None:
    # The canonical attack, proven at the extraction layer (review: the first cut let the
    # stdlib FilterError fall through to a silent clone fallback — and the old test only
    # passed because an unmocked real clone failed).
    hostile = tmp_path / "evil.tar.gz"
    hostile.write_bytes(_tar_bytes({"../escape.txt": b"x"}))
    into = tmp_path / "jail" / "extract"
    into.parent.mkdir()
    with pytest.raises(profiles.ProfileError, match="escape attempt"):
        profiles._extract_asset(hostile, into)
    assert not (tmp_path / "jail" / "escape.txt").exists()  # nothing landed outside
    assert not (tmp_path / "escape.txt").exists()


def test_hostile_asset_via_fetch_is_loud_never_a_silent_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve(monkeypatch, _tar_bytes({"../escape.txt": b"x"}))

    def no_git(*a: object, **k: object):
        raise AssertionError("an attacking asset must never silently fall back to clone")

    monkeypatch.setattr(profiles.subprocess, "run", no_git)
    with pytest.raises(profiles.ProfileError, match="escape attempt"):
        profiles._fetch_git("git+https://github.com/acme/evil.git@v1.0.0", _Console())


def test_ineligible_asset_falls_back_to_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Big/odd-but-not-hostile assets must not make a benign profile unresolvable: the
    # clone reproduces the same tag safely (review: two-class refusal policy).
    _serve(monkeypatch, _tar_bytes({f"templates/f{i}.md": b"x" for i in range(2_001)}))
    cloned: list[str] = []

    def fake_clone(cmd, **kw):
        cloned.append(cmd[1])
        if cmd[1] == "clone":
            dest = Path(cmd[-1])
            (dest / "templates").mkdir(parents=True)
            (dest / "profile.json").write_text(
                '{"name": "big", "version": "1.0.0", "description": "d"}', encoding="utf-8"
            )
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(profiles.subprocess, "run", fake_clone)
    root = profiles._fetch_git("git+https://github.com/acme/big.git@v1.0.0", _Console())
    assert (root / "profile.json").is_file() and "clone" in cloned


def test_extract_asset_two_class_refusals(tmp_path: Path) -> None:
    import io
    import tarfile

    # Ineligible (→ clone fallback): symlink member, member-count bomb, size bomb.
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("profile.json")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    link_tar = tmp_path / "link.tar.gz"
    link_tar.write_bytes(buf.getvalue())
    with pytest.raises(profiles._AssetIneligible, match="not a regular file"):
        profiles._extract_asset(link_tar, tmp_path / "o1")

    many = tmp_path / "many.tar.gz"
    many.write_bytes(_tar_bytes({f"templates/f{i}.md": b"x" for i in range(2_001)}))
    with pytest.raises(profiles._AssetIneligible, match="members"):
        profiles._extract_asset(many, tmp_path / "o3")

    big = tmp_path / "big.tar.gz"
    big.write_bytes(_tar_bytes({"templates/a.bin": b"\0" * 61_000_000}))
    with pytest.raises(profiles._AssetIneligible, match="extraction cap"):
        profiles._extract_asset(big, tmp_path / "o4")

    # Attacks (→ loud ProfileError): duplicates, including normalization-equal spoofing.
    dup = tmp_path / "dup.tar.gz"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in ("profile.json", "./profile.json"):
            info = tarfile.TarInfo(name)
            info.size = 2
            tar.addfile(info, io.BytesIO(b"{}"))
    dup.write_bytes(buf.getvalue())
    with pytest.raises(profiles.ProfileError, match="duplicate"):
        profiles._extract_asset(dup, tmp_path / "o2")

    # Weird-but-handled: a member path through a file raises legibly, not a traceback.
    odd = tmp_path / "odd.tar.gz"
    odd.write_bytes(_tar_bytes({"profile.json": b"{}", "profile.json/..": b"x"}))
    with pytest.raises((profiles.ProfileError, profiles._AssetIneligible)):
        profiles._extract_asset(odd, tmp_path / "o5")


def test_publish_release_packs_the_tag_tree_not_the_working_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tarfile

    prof = tmp_path / "myprof"
    (prof / "templates").mkdir(parents=True)
    (prof / "templates/x.md").write_text("tagged\n", encoding="utf-8")
    (prof / "profile.json").write_text(
        json.dumps({"name": "myprof", "version": "1.0.0", "description": "d"}),
        encoding="utf-8",
    )
    for a in (
        ["init", "-q", "-b", "main"],
        ["add", "-A"],
        ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
        ["tag", "v1.0.0"],
    ):
        subprocess.run(["git", "-C", str(prof), *a], check=True, capture_output=True)
    (prof / "templates/x.md").write_text("DIRTY — must not ship\n", encoding="utf-8")

    captured: dict[str, bytes] = {}
    real_run = profiles.subprocess.run

    def fake_run(cmd, **kw):
        if cmd[0] == "gh":  # capture the asset instead of talking to GitHub
            captured["asset"] = Path(cmd[4]).read_bytes()
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, **kw)

    monkeypatch.setattr(profiles.subprocess, "run", fake_run)
    c = _Console()
    assert profiles._publish_release(prof, "v1.0.0", c) == 0
    assert "Release asset published" in c.text
    asset = tmp_path / "got.tar.gz"
    asset.write_bytes(captured["asset"])
    with tarfile.open(asset) as tar:
        names = tar.getnames()
        body = tar.extractfile("templates/x.md").read()  # type: ignore[union-attr]
    assert "profile.json" in names
    assert body == b"tagged\n"  # the tag's tree — the dirty edit didn't ship


def test_publish_release_requires_a_tag(tmp_path: Path) -> None:
    c = _Console()
    assert profiles._publish_release(tmp_path, None, c) == 2
    assert "needs the current commit tagged" in c.text


def test_publish_degrades_gracefully_without_gh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # RFC: --release without gh must still print the shareable entry (review: the first
    # cut aborted before printing and raised a raw FileNotFoundError).
    prof = tmp_path / "p"
    (prof / "templates").mkdir(parents=True)
    (prof / "templates/x.md").write_text("hi\n", encoding="utf-8")
    (prof / "profile.json").write_text(
        json.dumps({"name": "p", "version": "1.0.0", "description": "d"}), encoding="utf-8"
    )
    for a in (
        ["init", "-q", "-b", "main"],
        ["add", "-A"],
        ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
        ["tag", "v1.0.0"],
    ):
        subprocess.run(["git", "-C", str(prof), *a], check=True, capture_output=True)

    real_run = profiles.subprocess.run

    def no_gh(cmd, **kw):
        if cmd[0] == "gh":
            raise FileNotFoundError(2, "not found", "gh")
        return real_run(cmd, **kw)

    monkeypatch.setattr(profiles.subprocess, "run", no_gh)
    c = _Console()
    rc = profiles._publish(
        argparse.Namespace(path=str(prof), url="git+https://x/p.git", release=True), c
    )
    assert rc == 1  # failure signalled…
    assert "Add this entry" in c.text  # …but the entry printed first
    assert "needs gh on PATH" in c.text or "--release needs" in c.text


# --- publish tail: the index PR (RFC 2026-07-07-publish-opens-the-index-pr) -------------------


def _index_bare(tmp_path: Path) -> Path:
    """A bare 'canonical index repo' with a house-style index.json on main."""
    content = (
        "{\n"
        '  "profiles": [\n'
        "    {\n"
        '      "name": "existing",\n'
        '      "url": "git+https://github.com/o/existing.git@v1.0.0",\n'
        '      "description": "d",\n'
        '      "author": "a",\n'
        '      "tags": ["x"]\n'
        "    }\n"
        "  ]\n"
        "}\n"
    )
    work = tmp_path / "index-work"
    (work / "contributions").mkdir(parents=True)
    (work / "contributions" / "index.json").write_text(content, encoding="utf-8")
    _git(work, "init", "-q", "-b", "main")
    _git(work, "add", "-A")
    _git(work, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "seed")
    bare = tmp_path / "index.git"
    subprocess.run(
        ["git", "clone", "-q", "--bare", str(work), str(bare)], check=True, capture_output=True
    )
    return bare


def _fake_gh(monkeypatch: pytest.MonkeyPatch, bare: Path, pr_calls: list) -> None:
    """gh faked at the seams: `repo clone` becomes a git clone of the local bare fixture,
    `pr create` is captured; git commands stay real (the direct-push path is exercised)."""
    real_run = profiles.subprocess.run

    def fake_run(cmd, **kw):
        if cmd[0] == "gh" and cmd[1:3] == ["repo", "clone"]:
            return real_run(
                ["git", "clone", "-q", "--branch", cmd[-1], str(bare), cmd[4]],
                capture_output=True,
                text=True,
            )
        if cmd[0] == "gh" and cmd[1:3] == ["pr", "create"]:
            pr_calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "https://github.com/o/r/pull/9\n", "")
        if cmd[0] == "gh" and cmd[1:3] == ["repo", "fork"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[0] == "gh" and cmd[1:2] == ["api"]:
            return subprocess.CompletedProcess(cmd, 0, "someone\n", "")
        return real_run(cmd, **kw)

    monkeypatch.setattr(profiles.subprocess, "run", fake_run)


def _entry(name: str, url: str) -> dict:
    return {"name": name, "url": url, "description": "d2", "author": "me", "tags": ["a", "b"]}


def test_index_pr_inserts_the_entry_and_touches_nothing_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bare = _index_bare(tmp_path)
    pr_calls: list = []
    _fake_gh(monkeypatch, bare, pr_calls)
    c = _Console()
    profiles._open_index_pr(
        _entry("newprof", "git+https://github.com/me/newprof.git@v0.1.0"),
        "o",
        "r",
        "main",
        "contributions/index.json",
        c,
    )
    assert "Index PR opened" in c.text
    (call,) = pr_calls
    assert call[call.index("--repo") + 1] == "o/r"
    assert call[call.index("--head") + 1] == "index-newprof-v0.1.0"  # direct push, no fork
    shown = subprocess.run(
        ["git", "-C", str(bare), "show", "index-newprof-v0.1.0:contributions/index.json"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    data = json.loads(shown)["profiles"]
    assert [e["name"] for e in data] == ["newprof", "existing"]
    # House style: the new entry is a compact block; every pre-existing line is untouched.
    assert '      "tags": ["a", "b"]\n' in shown
    original = (tmp_path / "index-work" / "contributions" / "index.json").read_text(
        encoding="utf-8"
    )
    assert set(original.splitlines()) <= set(shown.splitlines())


def test_index_pr_bump_swaps_only_the_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bare = _index_bare(tmp_path)
    pr_calls: list = []
    _fake_gh(monkeypatch, bare, pr_calls)
    c = _Console()
    profiles._open_index_pr(
        _entry("existing", "git+https://github.com/o/existing.git@v2.0.0"),
        "o",
        "r",
        "main",
        "contributions/index.json",
        c,
    )
    shown = subprocess.run(
        ["git", "-C", str(bare), "show", "index-existing-v2.0.0:contributions/index.json"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "@v2.0.0" in shown and "@v1.0.0" not in shown
    assert '"description": "d"' in shown  # prose left to the human, not regenerated
    subject = subprocess.run(
        ["git", "-C", str(bare), "log", "-1", "--format=%s", "index-existing-v2.0.0"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert subject == "chore(index): bump existing to v2.0.0"


def test_index_pr_refuses_to_repoint_a_listed_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The hijack shape: same name, different repo, dressed as a routine version bump.
    bare = _index_bare(tmp_path)
    pr_calls: list = []
    _fake_gh(monkeypatch, bare, pr_calls)
    with pytest.raises(profiles.ProfileError, match="repointing"):
        profiles._open_index_pr(
            _entry("existing", "git+https://github.com/evil/existing.git@v1.0.1"),
            "o",
            "r",
            "main",
            "contributions/index.json",
            _Console(),
        )
    assert not pr_calls
    branches = subprocess.run(
        ["git", "-C", str(bare), "branch"], capture_output=True, text=True, check=True
    ).stdout
    assert "index-" not in branches  # nothing left the machine


def test_index_pr_refuses_a_republish_of_the_same_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bare = _index_bare(tmp_path)
    _fake_gh(monkeypatch, bare, [])
    with pytest.raises(profiles.ProfileError, match="already listed at this exact version"):
        profiles._open_index_pr(
            _entry("existing", "git+https://github.com/o/existing.git@v1.0.0"),
            "o",
            "r",
            "main",
            "contributions/index.json",
            _Console(),
        )


def test_index_pr_degrades_when_the_anchor_is_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A reformat of the index (compact JSON, no `"profiles": [` line) must be a legible
    # refusal, never a broken PR.
    bare = _index_bare(tmp_path)
    work = tmp_path / "index-work"
    idx = work / "contributions" / "index.json"
    idx.write_text(
        json.dumps(json.loads(idx.read_text(encoding="utf-8")), separators=(",", ":")),
        encoding="utf-8",
    )
    _git(work, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-aqm", "reformat")
    _git(work, "push", "-q", str(bare), "main")
    _fake_gh(monkeypatch, bare, [])
    with pytest.raises(profiles.ProfileError, match=r"anchor|splice"):
        profiles._open_index_pr(
            _entry("newprof", "git+https://github.com/me/newprof.git@v0.1.0"),
            "o",
            "r",
            "main",
            "contributions/index.json",
            _Console(),
        )


def test_offer_skips_private_index_and_respects_decline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _entry("p", "git+https://github.com/me/p.git@v1.0.0")

    def boom(*a, **kw):  # any subprocess/confirm call would be a leak
        raise AssertionError("must not be reached")

    monkeypatch.setattr(profiles.subprocess, "run", boom)
    monkeypatch.setattr(profiles, "_confirm_index_pr", boom)
    monkeypatch.setenv(profiles.INDEX_ENV, "https://internal.example/index.json")
    assert profiles._offer_index_pr(entry, _Console()) == 0  # non-GitHub index: silent skip

    monkeypatch.delenv(profiles.INDEX_ENV)
    monkeypatch.setattr(profiles, "_confirm_index_pr", lambda name, slug: False)
    assert profiles._offer_index_pr(entry, _Console()) == 0  # declined: nothing runs


def test_publish_offers_the_index_pr_only_on_a_tty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    prof = tmp_path / "p"
    (prof / "templates").mkdir(parents=True)
    (prof / "templates" / "x.md").write_text("hi\n", encoding="utf-8")
    (prof / "profile.json").write_text(
        json.dumps({"name": "p", "version": "1.0.0", "description": "d"}), encoding="utf-8"
    )
    _git(prof, "init", "-q", "-b", "main")
    _git(prof, "add", "-A")
    _git(prof, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x")
    _git(prof, "remote", "add", "origin", "git@github.com:me/p.git")
    _git(prof, "tag", "v1.0.0")
    offered: list = []
    monkeypatch.setattr(profiles, "_offer_index_pr", lambda e, c: offered.append(e) or 0)
    monkeypatch.setattr(
        profiles, "_publish_author", lambda root: "someone"
    )  # keep gh/git config out of the test
    c = _Console()
    args = argparse.Namespace(path=str(prof), url=None, release=False)
    assert profiles._publish(args, c) == 0
    assert not offered  # pytest stdin is not a TTY — publish stays scriptable

    class _Tty:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(sys, "stdin", _Tty())
    assert profiles._publish(args, c) == 0
    assert offered and offered[0]["name"] == "p"
    assert offered[0]["url"] == "git+https://github.com/me/p.git@v1.0.0"  # ssh normalized
    assert offered[0]["author"] == "someone"


def test_infer_git_url_normalizes_github_ssh_but_keeps_other_hosts(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "remote", "add", "origin", "git@github.com:me/prof.git")
    assert profiles._infer_git_url(repo) == "git+https://github.com/me/prof.git"
    _git(repo, "remote", "set-url", "origin", "git@git.example.com:me/prof.git")
    assert profiles._infer_git_url(repo) == "git+ssh://git@git.example.com/me/prof.git"


def test_publish_warns_when_the_listing_url_is_ssh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prof = tmp_path / "p"
    (prof / "templates").mkdir(parents=True)
    (prof / "templates" / "x.md").write_text("hi\n", encoding="utf-8")
    (prof / "profile.json").write_text(
        json.dumps({"name": "p", "version": "1.0.0", "description": "d"}), encoding="utf-8"
    )
    _git(prof, "init", "-q", "-b", "main")
    _git(prof, "add", "-A")
    _git(prof, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x")
    _git(prof, "remote", "add", "origin", "git@git.example.com:me/p.git")
    _git(prof, "tag", "v1.0.0")
    monkeypatch.setattr(profiles, "_publish_author", lambda root: "someone")
    c = _Console()
    assert profiles._publish(argparse.Namespace(path=str(prof), url=None, release=False), c) == 0
    assert "git+ssh:// listing URL" in c.text


def test_publish_author_prefers_gh_login_then_git_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Tess")

    def gh_ok(cmd, **kw):
        assert cmd[:2] == ["gh", "api"]
        return subprocess.CompletedProcess(cmd, 0, "octo\n", "")

    monkeypatch.setattr(profiles.subprocess, "run", gh_ok)
    assert profiles._gh_login() == "octo"
    monkeypatch.undo()

    real_run = profiles.subprocess.run

    def no_gh(cmd, **kw):
        if cmd[0] == "gh":
            raise FileNotFoundError(2, "not found", "gh")
        return real_run(cmd, **kw)

    monkeypatch.setattr(profiles.subprocess, "run", no_gh)
    assert profiles._publish_author(repo) == "Tess"
