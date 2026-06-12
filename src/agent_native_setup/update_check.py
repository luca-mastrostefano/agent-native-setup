"""Best-effort 'a newer version is available' check.

Run at the end of a successful interactive scaffold. It is *advisory only*: every path
swallows errors, so an offline machine, a slow network, or a GitHub hiccup is a silent
no-op — it must never block, delay, or fail the run.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

_REPO = "luca-mastrostefano/agent-native-setup"
_RELEASES_API = f"https://api.github.com/repos/{_REPO}/releases/latest"
_CACHE_TTL = 24 * 60 * 60  # check GitHub at most once a day
# Failures are cached too (with a shorter TTL) so an offline machine pays the
# network timeout once an hour, not on every run.
_FAILURE_TTL = 60 * 60
_TIMEOUT = 1.5  # seconds — fail fast rather than make the user wait


def _cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(base) / "agent-native-setup" / "update-check.json"


def _installed_version() -> str:
    try:
        return version("agent-native-setup")
    except PackageNotFoundError:
        return "0.0.0"


def _fetch_latest_tag() -> str | None:
    """The latest release tag from GitHub (e.g. 'v0.3.0'), or None on any failure."""
    req = urllib.request.Request(_RELEASES_API, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # fixed https URL, not user input
        data = json.load(resp)
    tag = data.get("tag_name")
    return tag if isinstance(tag, str) else None


def _latest_with_cache(now: float) -> str | None:
    """Latest tag, served from a <24h cache when possible to avoid a call every run."""
    path = _cache_path()
    try:
        cached: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        ttl = _CACHE_TTL if cached.get("latest") else _FAILURE_TTL
        if now - cached.get("checked_at", 0) < ttl:
            return cached.get("latest")
    except (OSError, ValueError):
        pass
    try:
        latest = _fetch_latest_tag()
    except Exception:  # network/API failure — cache it so we don't re-pay the timeout
        latest = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"checked_at": now, "latest": latest}), encoding="utf-8")
    except OSError:
        pass
    return latest


def _is_newer(latest: str, installed: str) -> bool:
    from packaging.version import InvalidVersion, Version

    try:
        return Version(latest.lstrip("v")) > Version(installed)
    except InvalidVersion:
        return False


def maybe_notify(console: Any, *, now: float | None = None) -> None:
    """Print a one-line upgrade hint if a newer release exists. Silent on any error."""
    try:
        latest = _latest_with_cache(now if now is not None else time.time())
        if latest and _is_newer(latest, _installed_version()):
            console.print(
                f"\n[dim]A newer agent-native-setup ([/][bold]{latest}[/][dim]) is "
                "available — run [/][bold]uv tool upgrade agent-native-setup[/][dim].[/]"
            )
    except Exception:  # advisory only — a failed check must never break the run
        pass
