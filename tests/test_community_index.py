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
        json.dumps(
            {"name": "myprof", "version": "1.0.0", "extends": "default", "description": "My setup"}
        ),
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
