"""Force a decision when a commit makes a structural change (mechanical enforcement).

`AGENTS.md` requires an RFC before changing architecture, adding a dependency, or
anything hard to reverse. This `commit-msg` hook fires on the structural signals
we can detect mechanically and is satisfied by *either* an RFC staged in the same
commit *or* a logged waiver in the commit message:

    RFC-Not-Needed: <reason>

It never writes or moves RFCs — authoring stays with the contributor and
`sync_rfc_status.py` handles moves. The RFC that introduced it lives in `docs/rfc/`.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

WAIVER_RE = re.compile(r"^\s*RFC-Not-Needed:\s*(\S.*?)\s*$", re.IGNORECASE | re.MULTILINE)
_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_DEPS_ARRAY_RE = re.compile(r"(?ms)^\s*dependencies\s*=\s*\[(.*?)\]")


def _git(*args: str) -> str | None:
    """Run a git command; return stdout, or None if it fails."""
    try:
        out = subprocess.run(["git", *args], check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout


def _normalize(spec: str) -> str | None:
    """PEP 503 normalized distribution name from a PEP 508 requirement string."""
    match = _NAME_RE.match(spec)
    return re.sub(r"[-_.]+", "-", match.group(1)).lower() if match else None


def _raw_deps(text: str) -> list[str]:
    try:
        import tomllib

        data = tomllib.loads(text)
        return data.get("project", {}).get("dependencies", []) or []
    except ModuleNotFoundError:  # Python 3.10 has no tomllib; parse the array directly.
        match = _DEPS_ARRAY_RE.search(text)
        return re.findall(r"""["']([^"']+)["']""", match.group(1)) if match else []
    except Exception:
        return []


def dep_names(text: str) -> set[str]:
    """Normalized names in ``[project.dependencies]`` of a pyproject.toml string."""
    return {name for spec in _raw_deps(text) if (name := _normalize(spec))}


def _staged() -> list[tuple[str, str]]:
    """(status, path) for each staged change; path is the post-rename name."""
    out = _git("diff", "--cached", "--name-status") or ""
    changes: list[tuple[str, str]] = []
    for line in out.splitlines():
        fields = line.split("\t")
        if len(fields) >= 2:
            changes.append((fields[0][0], fields[-1]))
    return changes


def _added_dependencies() -> bool:
    staged = _git("show", ":pyproject.toml")
    if staged is None:
        return False
    head = _git("show", "HEAD:pyproject.toml") or ""
    return bool(dep_names(staged) - dep_names(head))


def find_triggers(changes: list[tuple[str, str]]) -> list[str]:
    """Human-readable list of the structural triggers this commit hit."""
    triggers: list[str] = []
    paths = [p for _, p in changes]
    if any(p == "pyproject.toml" for p in paths) and _added_dependencies():
        triggers.append("new dependency in pyproject.toml")
    if any(p.startswith("docs/architecture/") for p in paths):
        triggers.append("change under docs/architecture/")
    for status, path in changes:
        parts = Path(path).parts
        if status == "A" and len(parts) == 3 and parts[0] == "src" and parts[2] == "__init__.py":
            triggers.append(f"new top-level src package ({parts[1]})")
    return triggers


def is_satisfied(changes: list[tuple[str, str]], message: str) -> bool:
    staged_rfc = any(
        path.startswith("docs/rfc/current/") and path.endswith(".md")
        for status, path in changes
        if status != "D"
    )
    return staged_rfc or bool(WAIVER_RE.search(message))


def main(argv: list[str]) -> int:
    message = Path(argv[0]).read_text(encoding="utf-8") if argv else ""
    changes = _staged()
    triggers = find_triggers(changes)
    if not triggers or is_satisfied(changes, message):
        return 0

    bullet = "\n".join(f"  - {t}" for t in triggers)
    print(
        "RFC check: this commit makes a structural change but includes no RFC.\n\n"
        f"Triggered by:\n{bullet}\n\n"
        "Do one of:\n"
        "  - add an RFC under docs/rfc/current/ (see docs/rfc/TEMPLATE.md), or\n"
        "  - record why none is needed with a commit-message trailer:\n"
        "        RFC-Not-Needed: <reason>",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
