"""Community profile index (RFC 2026-07-04-community-index): discovery via search / list
--community / publish. The index fetch is stubbed through the on-disk cache — no network."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

import pytest

from agent_native_setup import profiles

_ENTRIES = [
    {
        "name": "acme-backend",
        "url": "git+https://github.com/acme/backend.git@v1",
        "description": "Acme Python backend house style",
        "tags": ["python", "backend"],
    },
    {
        "name": "web-strict",
        "url": "git+https://github.com/x/web.git@v2",
        "description": "Strict TS/React setup",
        "tags": ["node"],
    },
]


class _Console:
    def __init__(self) -> None:
        self.text = ""

    def print(self, *args: object, **_kw: object) -> None:
        self.text += " ".join(str(a) for a in args) + "\n"


@pytest.fixture(autouse=True)
def _tmp_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(profiles, "_index_cache_path", lambda: tmp_path / "index-cache.json")


def _seed(tmp_path: Path, entries: list[dict]) -> None:
    (tmp_path / "index-cache.json").write_text(
        json.dumps({"checked_at": time.time(), "url": profiles.INDEX_URL, "entries": entries}),
        encoding="utf-8",
    )


def test_search_matches_name_description_and_tags(tmp_path: Path) -> None:
    _seed(tmp_path, _ENTRIES)
    by_tag = _Console()
    profiles._search(argparse.Namespace(query="python"), by_tag)  # name + desc + tag
    assert "acme-backend" in by_tag.text and "web-strict" not in by_tag.text
    by_desc = _Console()
    profiles._search(argparse.Namespace(query="react"), by_desc)  # description only
    assert "web-strict" in by_desc.text


def test_search_reports_no_match(tmp_path: Path) -> None:
    _seed(tmp_path, _ENTRIES)
    c = _Console()
    profiles._search(argparse.Namespace(query="zzz-nope"), c)
    assert "No community profiles match" in c.text


def test_search_says_listing_is_not_vetting(tmp_path: Path) -> None:
    _seed(tmp_path, _ENTRIES)
    c = _Console()
    profiles._search(argparse.Namespace(query="acme"), c)
    assert "isn't vetting" in c.text and "asks for consent" in c.text  # discovery ≠ endorsement


def test_search_escapes_markup_in_untrusted_fields(tmp_path: Path) -> None:
    # An entry's fields are attacker-controlled remote data — console markup must be escaped, not
    # interpreted (else an entry could forge a "verified"-looking line).
    _seed(tmp_path, [{"name": "x", "url": "git+https://h/r.git", "description": "[red]spoof[/]"}])
    c = _Console()
    profiles._search(argparse.Namespace(query="x"), c)
    assert "\\[red]" in c.text  # escaped, inert


def test_list_community_shows_the_whole_index(tmp_path: Path) -> None:
    _seed(tmp_path, _ENTRIES)
    c = _Console()
    profiles._list(argparse.Namespace(community=True), c)
    assert "acme-backend" in c.text and "web-strict" in c.text


def test_fetch_index_serves_from_cache(tmp_path: Path) -> None:
    _seed(tmp_path, _ENTRIES)
    assert [e["name"] for e in profiles._fetch_index(time.time())] == ["acme-backend", "web-strict"]


def test_fetch_index_is_silent_and_data_only_for_a_non_http_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A file:// (or any non-http) index URL is never fetched — data-only, http(s) guard → [].
    monkeypatch.setenv(profiles.INDEX_ENV, "file:///etc/passwd")
    assert profiles._fetch_index(time.time()) == []


def test_an_index_url_is_not_privileged(tmp_path: Path) -> None:
    # A malicious entry url still flows through resolve's transport allowlist when `add`-ed.
    with pytest.raises(profiles.ProfileError):
        profiles.resolve("git+ext::sh -c payload")


def test_publish_validates_infers_url_and_tag_and_emits_entry(tmp_path: Path) -> None:
    prof = tmp_path / "myprof"
    (prof / "templates").mkdir(parents=True)
    (prof / "profile.json").write_text(
        json.dumps({"name": "myprof", "version": "1.0.0", "description": "My setup"}),
        encoding="utf-8",
    )
    (prof / "templates/x.md").write_text("hi\n", encoding="utf-8")
    for a in (
        ["init", "-q"],
        ["add", "-A"],
        ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
        ["remote", "add", "origin", "https://github.com/me/myprof.git"],
        ["tag", "v1.0.0"],
    ):
        subprocess.run(["git", "-C", str(prof), *a], check=True, capture_output=True)

    c = _Console()
    assert profiles._publish(argparse.Namespace(path=str(prof), url=None), c) == 0
    assert "git+https://github.com/me/myprof.git@v1.0.0" in c.text  # inferred remote + tag
    assert '"name": "myprof"' in c.text  # ready-to-PR entry


def test_the_committed_index_is_well_formed() -> None:
    # A PR that adds a malformed entry to contributions/index.json fails here (lightweight CI gate;
    # doesn't resolve URLs — that needs the network).
    idx = Path(__file__).resolve().parent.parent / "contributions" / "index.json"
    profs = json.loads(idx.read_text(encoding="utf-8"))["profiles"]
    assert profs, "the committed index is empty"
    for e in profs:
        assert e.get("name") and e.get("description"), e
        assert e.get("url", "").startswith("git+http"), e  # a git+https/ssh URL


# --- adopt-by-name: `add <name>` / `show <name>` fall back to the index (RFC §6) ---------------


def _local_profile(tmp_path: Path, name: str = "acme-backend") -> Path:
    d = tmp_path / "src-profile"
    (d / "templates" / "docs").mkdir(parents=True)
    (d / "templates" / "docs" / "x.md").write_text("hi\n", encoding="utf-8")
    (d / "profile.json").write_text(
        json.dumps({"name": name, "version": "1.0.0", "description": "d"}),
        encoding="utf-8",
    )
    return d


def _stub_fetch(monkeypatch: pytest.MonkeyPatch, src: Path) -> None:
    """Stand in for the network clone: the git+ URL 'fetches' to a prepared local dir. The
    profile still loads with the git+ source, so provenance/consent behave as for a real fetch."""
    monkeypatch.setattr(profiles, "_fetch_git", lambda spec, console: src)


_URL = "git+https://github.com/acme/backend.git@v1"


def test_show_falls_back_to_an_index_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_fetch(monkeypatch, _local_profile(tmp_path))
    _seed(tmp_path, [{"name": "acme-backend", "url": _URL, "description": "d"}])
    c = _Console()
    assert profiles._show(argparse.Namespace(ref="acme-backend"), c) == 0
    assert "community index" in c.text  # the redirection is visible
    assert "acme-backend[/] 1.0.0" in c.text  # rendered by the normal show path


def test_add_falls_back_to_an_index_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_fetch(monkeypatch, _local_profile(tmp_path))
    _seed(tmp_path, [{"name": "acme-backend", "url": _URL, "description": "d"}])
    monkeypatch.setattr(profiles, "USER_PROFILE_DIR", tmp_path / "userdir")
    c = _Console()
    rc = profiles._add(argparse.Namespace(url="acme-backend", name=None, allow_code=False), c)
    assert rc == 0  # the profile is safe (one .md) — no consent needed
    assert (tmp_path / "userdir" / "acme-backend" / "profile.json").is_file()


def test_index_name_fallback_keeps_the_transport_allowlist(tmp_path: Path) -> None:
    # A poisoned index can point a NAME at any URL — but that URL still flows through the same
    # allowlist as a hand-typed one, so an ext:: transport is rejected, not executed.
    for url, match in [
        ("git+ext://sh -c payload", "transport"),  # transport allowlist
        ("git+ext::sh -c payload", "expected git"),  # not even URL-shaped
    ]:
        _seed(tmp_path, [{"name": "evil", "url": url, "description": "d"}])
        with pytest.raises(profiles.ProfileError, match=match):
            profiles._resolve_ref("evil", _Console())


def test_a_non_git_index_url_is_refused(tmp_path: Path) -> None:
    # A path-shaped entry would resolve as a trusted-LOCAL profile — provenance is keyed on the
    # git+ scheme — and skip the consent gate entirely. Refused, never resolved.
    src = _local_profile(tmp_path, name="python-best")
    (src / "templates" / ".claude").mkdir()
    (src / "templates" / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    _seed(tmp_path, [{"name": "python-best", "url": str(src), "description": "d"}])
    with pytest.raises(profiles.ProfileError, match="not a git\\+ URL"):
        profiles._resolve_ref("python-best", _Console())


def test_a_broken_local_profile_is_not_shadowed_by_the_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Locals always win — including a local profile that exists but fails to load: the user needs
    # its parse error, not a silent redirect to whatever the index lists under that name.
    userdir = tmp_path / "userdir"
    (userdir / "acme-backend").mkdir(parents=True)
    (userdir / "acme-backend" / "profile.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(profiles, "USER_PROFILE_DIR", userdir)
    _seed(tmp_path, [{"name": "acme-backend", "url": _URL, "description": "d"}])
    c = _Console()
    with pytest.raises(profiles.ProfileError, match="can't read"):
        profiles._resolve_ref("acme-backend", c)
    assert "community index" not in c.text


def test_redirect_line_escapes_markup_in_the_index_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The redirect line prints attacker-controlled index data — markup must be inert, as in search.
    _stub_fetch(monkeypatch, _local_profile(tmp_path))
    _seed(
        tmp_path,
        [{"name": "acme-backend", "url": "git+https://h/[red]r[/].git", "description": "d"}],
    )
    c = _Console()
    profiles._resolve_ref("acme-backend", c)
    assert "\\[red]" in c.text  # escaped, inert


def test_pathlike_and_unknown_refs_never_consult_the_index(tmp_path: Path) -> None:
    _seed(tmp_path, [{"name": "some/dir", "url": str(tmp_path), "description": "d"}])
    with pytest.raises(profiles.ProfileError, match="not found"):
        profiles._resolve_ref("some/dir", _Console())  # path-shaped → no index lookup
    with pytest.raises(profiles.ProfileError, match="not found"):
        profiles._resolve_ref("not-listed", _Console())  # bare name, no entry → original error


# --- public stats sidecar (RFC 2026-07-07-profile-releases-and-stats) -----------------------


def _tmp_stats(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: dict | None) -> None:
    monkeypatch.setattr(profiles, "_stats_cache_path", lambda: tmp_path / "stats-cache.json")
    if payload is None:
        monkeypatch.setattr(profiles, "_fetch_stats", lambda now: {})
    else:
        monkeypatch.setattr(profiles, "_fetch_stats", lambda now: payload)


def test_search_ranks_by_downloads_and_shows_stats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entries = [
        {"name": "small", "url": "git+https://x/a.git", "description": "python d", "tags": []},
        {"name": "big", "url": "git+https://x/b.git", "description": "python d", "tags": []},
    ]
    monkeypatch.setattr(profiles, "_fetch_index", lambda now: entries)
    _tmp_stats(
        tmp_path, monkeypatch, {"big": {"stars": 7, "downloads": 340}, "small": {"stars": 1}}
    )
    c = _Console()
    assert profiles._search(argparse.Namespace(query="python"), c) == 0
    assert c.text.index("big") < c.text.index("small")  # downloads rank first
    assert "340" in c.text and "★ 7" in c.text and "★ 1" in c.text


def test_stats_are_advisory_display_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # No stats reachable → listings render exactly as before, nothing raises.
    entries = [{"name": "a", "url": "git+https://x/a.git", "description": "d", "tags": []}]
    monkeypatch.setattr(profiles, "_fetch_index", lambda now: entries)
    _tmp_stats(tmp_path, monkeypatch, None)
    c = _Console()
    assert profiles._search(argparse.Namespace(query="d"), c) == 0
    assert "a" in c.text and "★" not in c.text


def test_fetch_stats_caches_and_fails_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import urllib.request

    monkeypatch.setattr(profiles, "_stats_cache_path", lambda: tmp_path / "stats-cache.json")
    calls: list[str] = []

    class _Resp:
        def __init__(self, data: bytes) -> None:
            self._d = data

        def read(self, n: int) -> bytes:
            return self._d

        def __enter__(self):
            return self

        def __exit__(self, *a: object) -> None: ...

    def fake_urlopen(url, timeout=None):
        calls.append(str(url))
        return _Resp(json.dumps({"profiles": {"p": {"stars": 3, "downloads": 9}}}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert profiles._fetch_stats(1000.0) == {"p": {"stars": 3, "downloads": 9}}
    assert profiles._fetch_stats(1000.0 + 60) == {"p": {"stars": 3, "downloads": 9}}
    assert len(calls) == 1  # served from the daily cache

    def broken(url, timeout=None):
        raise OSError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", broken)
    assert profiles._fetch_stats(1000.0 + 90_000) == {}  # stale → refetch fails → silent {}


def test_check_index_flags_asset_tag_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib.util
    import sys as _sys

    spec = importlib.util.spec_from_file_location(
        "check_index", Path(__file__).parent.parent / "tools/checks/check_index.py"
    )
    check_index = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    assert spec and spec.loader
    _sys.modules["check_index"] = check_index
    spec.loader.exec_module(check_index)

    # Two transports resolving to different content → the poisoning diagnosis.
    a, b = tmp_path / "a", tmp_path / "b"
    for d, body in ((a, "one\n"), (b, "two\n")):
        (d / "templates").mkdir(parents=True)
        (d / "templates/x.md").write_text(body, encoding="utf-8")
        (d / "profile.json").write_text(
            json.dumps({"name": "p", "version": "1.0.0", "description": "d"}), encoding="utf-8"
        )

    def fake_fetch(url, console, *, transport="auto"):
        return a if transport == "asset" else b

    monkeypatch.setattr(check_index.profiles, "_fetch_git", fake_fetch)
    err = check_index._asset_equivalence("git+https://github.com/x/y.git@v1", _Console())
    assert err and "possible poisoning" in err

    # Equivalent content → no finding; missing asset → no finding.
    def same_fetch(url, console, *, transport="auto"):
        return a

    monkeypatch.setattr(check_index.profiles, "_fetch_git", same_fetch)
    assert check_index._asset_equivalence("git+https://github.com/x/y.git@v1", _Console()) is None

    def no_asset(url, console, *, transport="auto"):
        if transport == "asset":
            raise check_index.profiles.ProfileError("no release asset")
        return a

    monkeypatch.setattr(check_index.profiles, "_fetch_git", no_asset)
    assert check_index._asset_equivalence("git+https://github.com/x/y.git@v1", _Console()) is None
