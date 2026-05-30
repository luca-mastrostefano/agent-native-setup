"""Generates the docs tree and the RFC lifecycle (current/done/superseded)."""

from __future__ import annotations

from datetime import date

from ai_setup.config import WizardConfig
from ai_setup.scaffold import Scaffolder

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
`Status:` line and run `task rfc-sync` (also wired as a pre-commit hook) to
relocate the file to the matching folder via `git mv`, preserving history.
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
formatters behave in pre-commit. Run by the `rfc-status` hook and `task rfc-sync`.
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
            ["git", "mv", str(source), str(destination)], check=True, capture_output=True
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
        print("RFC(s) moved to match Status — review and `git add` the moves.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
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
"""

ARCH_OVERVIEW = """\
# Architecture overview

> Brand-new project. Fill this in as the first real components land.

## Components

_TODO: list the main pieces and their responsibilities._

## Dependency rules

_TODO: state which parts may depend on which. Enforce mechanically when stable._
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
# Adopt the AI-native project setup

- **Status:** Accepted
- **Date:** {{ today }}
- **Author:** {{ name }} team

## Context

Starting a new project, we want AI and human contributors working from the same
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


def generate(config: WizardConfig, sc: Scaffolder) -> None:
    sc.write("docs/README.md", DOCS_README)
    sc.write("docs/contributing.md", CONTRIBUTING)
    sc.write("docs/architecture/overview.md", ARCH_OVERVIEW)
    sc.write("docs/improvements.md", IMPROVEMENTS)
    sc.write("docs/rfc/TEMPLATE.md", RFC_TEMPLATE)
    sc.write("tools/checks/sync_rfc_status.py", SYNC_RFC_STATUS)
    for stage in ("current", "done", "superseded"):
        sc.write(f"docs/rfc/{stage}/.gitkeep", "")
    extras = []
    if config.include_quality:
        extras.append("linters and pre-commit hooks")
    if config.include_ci and config.use_github_actions:
        extras.append("CI on every push")
    extras_clause = f"{', '.join(extras)}, " if extras else ""
    sc.render_write(
        f"docs/rfc/current/{date.today():%Y-%m-%d}-adopt-ai-native-setup.md",
        FIRST_RFC,
        today=f"{date.today():%Y-%m-%d}",
        name=config.project_name,
        extras=extras_clause,
    )
