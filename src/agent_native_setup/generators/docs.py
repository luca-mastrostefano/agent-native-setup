"""Generates the docs tree and the RFC lifecycle (current/done/superseded)."""

from __future__ import annotations

from datetime import date

from agent_native_setup.config import WizardConfig
from agent_native_setup.scaffold import Scaffolder

DOCS_README = """\
# Docs

- `architecture/` — how the system is built and why.
- `rfc/` — proposals and decisions, by lifecycle stage:
  - `current/` — under discussion or in progress
  - `done/` — accepted and shipped
  - `superseded/` — replaced by a later RFC
- `improvements.md` — backlog of deferred ideas and known gaps.
- `contributing.md` — the dev loop.

RFCs are named `YYYY-MM-DD-short-slug.md`. You don't move them by hand: edit the
`Status:` line and the `rfc-status` pre-commit hook relocates the file via `git mv`
(or run `python tools/checks/sync_rfc_status.py`), preserving history.
"""

IMPROVEMENTS = """\
# Improvements backlog

Deferred ideas and known gaps — things not yet decided (so not an RFC) and not
current state (so not `architecture/`). Keep entries concrete; promote anything
that needs a real decision into an RFC in `docs/rfc/current/`.

## Known gaps

- _Add the first gap or deferred idea here._
"""

SYNC_RFC_STATUS = '''\
"""Keep each RFC in the folder that matches its Status (mechanical enforcement).

Lifecycle (docs/README.md): current/ -> done/ -> superseded/. The `Status:`
line in an RFC drives where it belongs:

    Proposed / Accepted -> current/
    Done                -> done/
    Superseded          -> superseded/

When a status changes, this moves the file to the right folder (via `git mv`
when possible) and exits non-zero so the move can be re-staged — mirroring how
formatters behave in pre-commit. Run by the `rfc-status` pre-commit hook.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

RFC_ROOT = Path(__file__).resolve().parents[2] / "docs" / "rfc"
LIFECYCLE_FOLDERS = ("current", "done", "superseded")
STATUS_FOLDER = {
    "proposed": "current",
    "accepted": "current",
    "done": "done",
    "superseded": "superseded",
}
_STATUS_RE = re.compile(r"\\*\\*Status:\\*\\*\\s*([A-Za-z]+)")


def parse_status(text: str) -> str | None:
    """Return the lower-cased Status keyword from an RFC body, if present."""
    match = _STATUS_RE.search(text)
    return match.group(1).lower() if match else None


def target_folder(status: str) -> str | None:
    """Map a Status keyword to its lifecycle folder (None if unrecognised)."""
    return STATUS_FOLDER.get(status.lower())


def find_moves(rfc_root: Path) -> list[tuple[Path, Path]]:
    """Return (source, destination) pairs for RFCs sitting in the wrong folder."""
    moves: list[tuple[Path, Path]] = []
    for folder in LIFECYCLE_FOLDERS:
        directory = rfc_root / folder
        if not directory.is_dir():
            continue
        for rfc in sorted(directory.glob("*.md")):
            status = parse_status(rfc.read_text(encoding="utf-8"))
            destination = target_folder(status) if status else None
            if destination and destination != folder:
                moves.append((rfc, rfc_root / destination / rfc.name))
    return moves


def _move(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["git", "mv", str(source), str(destination)],
            check=True,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        shutil.move(str(source), str(destination))


def main() -> int:
    moves = find_moves(RFC_ROOT)
    for source, destination in moves:
        _move(source, destination)
        rel_from = source.relative_to(RFC_ROOT.parent)
        rel_to = destination.relative_to(RFC_ROOT.parent)
        print(f"moved {rel_from} -> {rel_to} (Status changed)", file=sys.stderr)

    if moves:
        print(
            "RFC(s) moved to match Status — review and `git add` the moves.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

# Python-shaped commit-msg gates (pyproject deps, src/<pkg> packages). Written only
# for Python projects; wired into .pre-commit-config.yaml by the quality generator.
RFC_NEEDED = r'''"""Force a decision when a commit makes a structural change (mechanical enforcement).

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
'''

DOCS_SYNC = r'''"""Remind the author to update the architecture overview when a new component lands.

`AGENTS.md`'s Context pillar relies on `docs/architecture/` staying accurate as the
system grows. A diff can't tell when an *edit* makes prose stale, but it can catch
the one structural moment that almost always should: a brand-new top-level package
under `src/`. This `commit-msg` hook fires on that signal and is satisfied by
*either* a `docs/architecture/` change staged in the same commit *or* a logged
waiver in the commit message:

    Docs-Not-Needed: <reason>

It never writes docs — keeping the overview studyable stays with the author. The
RFC that introduced it lives in `docs/rfc/`.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

WAIVER_RE = re.compile(r"^\s*Docs-Not-Needed:\s*(\S.*?)\s*$", re.IGNORECASE | re.MULTILINE)


def _git(*args: str) -> str | None:
    """Run a git command; return stdout, or None if it fails."""
    try:
        out = subprocess.run(["git", *args], check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout


def _staged() -> list[tuple[str, str]]:
    """(status, path) for each staged change; path is the post-rename name."""
    out = _git("diff", "--cached", "--name-status") or ""
    changes: list[tuple[str, str]] = []
    for line in out.splitlines():
        fields = line.split("\t")
        if len(fields) >= 2:
            changes.append((fields[0][0], fields[-1]))
    return changes


def find_triggers(changes: list[tuple[str, str]]) -> list[str]:
    """Human-readable list of the structural triggers this commit hit."""
    triggers: list[str] = []
    for status, path in changes:
        parts = Path(path).parts
        if status == "A" and len(parts) == 3 and parts[0] == "src" and parts[2] == "__init__.py":
            triggers.append(f"new top-level src package ({parts[1]})")
    return triggers


def is_satisfied(changes: list[tuple[str, str]], message: str) -> bool:
    touched_arch = any(
        path.startswith("docs/architecture/") for status, path in changes if status != "D"
    )
    return touched_arch or bool(WAIVER_RE.search(message))


def main(argv: list[str]) -> int:
    message = Path(argv[0]).read_text(encoding="utf-8") if argv else ""
    changes = _staged()
    triggers = find_triggers(changes)
    if not triggers or is_satisfied(changes, message):
        return 0

    bullet = "\n".join(f"  - {t}" for t in triggers)
    print(
        "Docs check: this commit adds a new component but updates no architecture doc.\n\n"
        f"Triggered by:\n{bullet}\n\n"
        "Do one of:\n"
        "  - update docs/architecture/overview.md to describe it, or\n"
        "  - record why the docs don't need it with a commit-message trailer:\n"
        "        Docs-Not-Needed: <reason>",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
'''

# Stdlib-unittest tests shipped beside the helpers above, so the logic they carry isn't
# scaffolded untested (AGENTS.md §4). Run by the `unittest discover` runner wired into
# the command surface, a pre-push hook, and CI (quality.py / ci.py). unittest — not
# pytest — so they run with only `python` on PATH, even when Python isn't a selected
# language. Kept <=88 cols / default-ruff clean so the always-shipped sync test passes a
# non-Python project's tools/ ruff guard. Dogfooded byte-for-byte (test_scaffold_checks).
TEST_SYNC_RFC_STATUS = r'''"""Tests for the rfc-status folder-sync helper (stdlib unittest)."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

_HELPER = Path(__file__).resolve().parent / "sync_rfc_status.py"
_spec = importlib.util.spec_from_file_location("sync_rfc_status", _HELPER)
assert _spec and _spec.loader
sync_rfc_status = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync_rfc_status)


def _rfc(status: str) -> str:
    return f"# Title\n\n- **Status:** {status}\n"


class ParseStatus(unittest.TestCase):
    def test_reads_status_keyword(self) -> None:
        self.assertEqual(sync_rfc_status.parse_status(_rfc("Accepted")), "accepted")

    def test_missing_status_is_none(self) -> None:
        self.assertIsNone(sync_rfc_status.parse_status("# Title\n"))


class TargetFolder(unittest.TestCase):
    def test_known_statuses_map_to_folders(self) -> None:
        self.assertEqual(sync_rfc_status.target_folder("proposed"), "current")
        self.assertEqual(sync_rfc_status.target_folder("done"), "done")
        self.assertEqual(sync_rfc_status.target_folder("superseded"), "superseded")

    def test_unknown_status_is_none(self) -> None:
        self.assertIsNone(sync_rfc_status.target_folder("draft"))


class FindMoves(unittest.TestCase):
    def test_flags_rfc_sitting_in_the_wrong_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "current").mkdir()
            (root / "done").mkdir()
            (root / "current" / "a.md").write_text(_rfc("Done"))
            (root / "current" / "b.md").write_text(_rfc("Accepted"))
            moves = sync_rfc_status.find_moves(root)
            expected = (root / "current" / "a.md", root / "done" / "a.md")
            self.assertEqual(moves, [expected])


if __name__ == "__main__":
    unittest.main()
'''

TEST_RFC_NEEDED = r'''"""Tests for the rfc-needed commit-msg gate (stdlib unittest)."""

import importlib.util
import unittest
from pathlib import Path

_HELPER = Path(__file__).resolve().parent / "rfc_needed.py"
_spec = importlib.util.spec_from_file_location("rfc_needed", _HELPER)
assert _spec and _spec.loader
rfc_needed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rfc_needed)


class DepNames(unittest.TestCase):
    def test_normalizes_and_strips_specifiers(self) -> None:
        text = '[project]\ndependencies = ["Foo_Bar>=1.0", "baz[extra]~=2"]\n'
        self.assertEqual(rfc_needed.dep_names(text), {"foo-bar", "baz"})


class FindTriggers(unittest.TestCase):
    def test_new_top_level_src_package_fires(self) -> None:
        changes = [("A", "src/widget/__init__.py")]
        self.assertEqual(
            rfc_needed.find_triggers(changes),
            ["new top-level src package (widget)"],
        )

    def test_subpackage_does_not_fire(self) -> None:
        changes = [("A", "src/widget/sub/__init__.py")]
        self.assertEqual(rfc_needed.find_triggers(changes), [])

    def test_architecture_change_fires(self) -> None:
        changes = [("M", "docs/architecture/overview.md")]
        self.assertIn(
            "change under docs/architecture/",
            rfc_needed.find_triggers(changes),
        )


class IsSatisfied(unittest.TestCase):
    def test_staged_rfc_satisfies(self) -> None:
        changes = [("A", "docs/rfc/current/x.md")]
        self.assertTrue(rfc_needed.is_satisfied(changes, "feat: x"))

    def test_waiver_satisfies(self) -> None:
        message = "feat: x\n\nRFC-Not-Needed: tooling-only"
        self.assertTrue(rfc_needed.is_satisfied([], message))

    def test_unsatisfied_without_rfc_or_waiver(self) -> None:
        self.assertFalse(rfc_needed.is_satisfied([], "feat: x"))


if __name__ == "__main__":
    unittest.main()
'''

TEST_DOCS_SYNC = r'''"""Tests for the docs-sync commit-msg gate (stdlib unittest)."""

import importlib.util
import unittest
from pathlib import Path

_HELPER = Path(__file__).resolve().parent / "docs_sync.py"
_spec = importlib.util.spec_from_file_location("docs_sync", _HELPER)
assert _spec and _spec.loader
docs_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(docs_sync)


class FindTriggers(unittest.TestCase):
    def test_new_top_level_src_package_fires(self) -> None:
        changes = [("A", "src/widget/__init__.py")]
        self.assertEqual(
            docs_sync.find_triggers(changes),
            ["new top-level src package (widget)"],
        )

    def test_subpackage_does_not_fire(self) -> None:
        changes = [("A", "src/widget/sub/__init__.py")]
        self.assertEqual(docs_sync.find_triggers(changes), [])


class IsSatisfied(unittest.TestCase):
    def test_arch_change_satisfies(self) -> None:
        changes = [("M", "docs/architecture/overview.md")]
        self.assertTrue(docs_sync.is_satisfied(changes, "feat: x"))

    def test_waiver_satisfies(self) -> None:
        message = "feat: x\n\nDocs-Not-Needed: n/a"
        self.assertTrue(docs_sync.is_satisfied([], message))

    def test_unsatisfied_without_doc_or_waiver(self) -> None:
        changes = [("A", "src/widget/__init__.py")]
        self.assertFalse(docs_sync.is_satisfied(changes, "feat: x"))


if __name__ == "__main__":
    unittest.main()
'''


CONTRIBUTING = """\
# Contributing

## Dev loop

1. Read `AGENTS.md` — the contract and the four execution principles.
2. For anything architectural or hard to reverse, write an RFC first
   (`docs/rfc/current/`, from `docs/rfc/TEMPLATE.md`).
3. Make the change. Keep it surgical.
4. Run the quality gate before committing (see the command surface in `AGENTS.md`).

## Definition of done

- The change traces directly to the task — no drive-by edits.
- It's verified by a test or an explicit check.
- Linters and hooks pass.
{% if existing_project %}

## Adopting on an existing codebase

This repo already had code when the setup landed, so the gate is tuned not to
rewrite it all at once:

- Local commits only format the files you touch (pre-commit runs on staged files).
- CI lints only the files changed in a pull request, so existing code is
  grandfathered until you edit it.
- To clean everything in one pass (optional): run your formatter across the repo
  (see the command surface), commit it on its own, add that commit's SHA to
  `.git-blame-ignore-revs`, and run
  `git config blame.ignoreRevsFile .git-blame-ignore-revs` so `git blame` skips it.
- Non-formatting lint findings in legacy code aren't auto-fixed — resolve them as
  you touch the code, or scope rules in the linter config.
{% endif %}
"""

ARCH_OVERVIEW = """\
# Architecture overview

> Brand-new project — only the agent-native scaffolding exists so far. The tooling
> components below are pre-filled (the wizard built them); add the product
> components and dependency rules as real code lands.

## Components

### Tooling & process

{{ tooling }}

### Product

_TODO: list the application's own components and their responsibilities as they land._

## Dependency rules

_TODO: state which parts may depend on which. Enforce mechanically (e.g. with an
architecture test) once the boundaries stabilize._
"""

RFC_TEMPLATE = """\
# <Title>

- **Status:** Proposed | Accepted | Done | Superseded
- **Date:** YYYY-MM-DD
- **Author:** <name>

## Context

What problem are we solving? What constraints apply?

## Decision

What are we doing, concretely? Note the simplest viable option and why it wins.

## Consequences

What becomes easier, harder, or newly possible? What do we give up?

## Alternatives considered

Briefly: what else we looked at and why we passed.
"""

FIRST_RFC = """\
# Adopt the agent-native project setup

- **Status:** Accepted
- **Date:** {{ today }}
- **Author:** {{ name }} team

## Context

Starting a new project, we want coding agents and humans working from the same
contract from day one, with conventions enforced mechanically rather than by
memory.

## Decision

Adopt this scaffold: a canonical `AGENTS.md` (with per-tool pointers), a docs +
RFC structure, {{ extras }}and the four execution principles as the standard
for every change.

## Consequences

Contributors have one place to look for conventions. Drift is caught by tooling.
The cost is keeping `AGENTS.md` and the docs current as the project evolves.
"""


def _arch_tooling(config: WizardConfig) -> str:
    """Pre-seed the architecture overview with the components the wizard built."""
    bullets = [
        "- **`AGENTS.md`** — the contract every contributor (human or AI) works from: "
        "the navigation map, the command surface, and the four execution principles.",
        "- **`docs/`** — `architecture/` (this map) and `rfc/` (the proposal lifecycle "
        "`current/` → `done/` → `superseded/`).",
        "- **`tools/checks/`** — scripts that enforce the RFC/docs conventions "
        "mechanically (e.g. keeping each RFC in the folder its Status names).",
    ]
    if config.include_quality:
        layers = (
            "pre-commit, command-surface, and CI"
            if config.include_ci and config.use_github_actions
            else "pre-commit and command-surface"
        )
        bullets.append(
            f"- **Quality gate** — linters/formatters wired at the {layers} layers so "
            "violations are caught mechanically."
        )
    if config.include_ci and config.use_github_actions:
        sec = " plus a secrets + dependency scan" if config.include_security else ""
        bullets.append(f"- **CI** (`.github/workflows/`) — the quality gate{sec} on every push/PR.")
    return "\n".join(bullets)


def generate(config: WizardConfig, sc: Scaffolder) -> None:
    sc.write("docs/README.md", DOCS_README)
    sc.render_write("docs/contributing.md", CONTRIBUTING, existing_project=config.existing_project)
    sc.render_write("docs/architecture/overview.md", ARCH_OVERVIEW, tooling=_arch_tooling(config))
    sc.write("docs/improvements.md", IMPROVEMENTS)
    sc.write("docs/rfc/TEMPLATE.md", RFC_TEMPLATE)
    sc.write("tools/checks/sync_rfc_status.py", SYNC_RFC_STATUS)
    sc.write("tools/checks/test_sync_rfc_status.py", TEST_SYNC_RFC_STATUS)
    if "python" in config.languages:  # triggers key on pyproject/src layout
        sc.write("tools/checks/rfc_needed.py", RFC_NEEDED)
        sc.write("tools/checks/test_rfc_needed.py", TEST_RFC_NEEDED)
        sc.write("tools/checks/docs_sync.py", DOCS_SYNC)
        sc.write("tools/checks/test_docs_sync.py", TEST_DOCS_SYNC)
    for stage in ("current", "done", "superseded"):
        sc.write(f"docs/rfc/{stage}/.gitkeep", "")
    extras = []
    if config.include_quality:
        extras.append("linters and pre-commit hooks")
    if config.include_ci and config.use_github_actions:
        extras.append("CI on every push")
    extras_clause = f"{', '.join(extras)}, " if extras else ""
    sc.render_write(
        f"docs/rfc/current/{date.today():%Y-%m-%d}-adopt-agent-native-setup.md",
        FIRST_RFC,
        today=f"{date.today():%Y-%m-%d}",
        name=config.project_name,
        extras=extras_clause,
    )
