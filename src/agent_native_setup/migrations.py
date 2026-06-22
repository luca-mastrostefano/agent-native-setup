"""Structural migrations `update` replays before regenerating (RFC 2026-06-20).

Regenerating from the saved config refreshes the files the wizard *generates*, but it can't
move the files a *user* accumulated when a convention's layout changes — e.g. the RFC
lifecycle rename (`current/` → `active/`). Those moves live here.

Each migration is **structural only** (move/rename — never rewrites file *contents*, which
would be a merge problem) and **idempotent**: it guards on the old layout still being
present, so running it on an already-migrated repo is a no-op. Because of that, `update`
simply attempts them all every run rather than version-gating — robust even when versions
aren't reliably tagged. The `since` field documents the change that introduced each one.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Migration:
    since: str  # the change that introduced this structural move (for ordering/docs)
    describe: str
    # Mutate the tree (apply=True) or just report what it would do (apply=False).
    apply: Callable[..., list[str]]


def _move_dir_contents(target: Path, src_rel: str, dst_rel: str, *, apply: bool) -> list[str]:
    """Plan (and, when ``apply``, perform) moving every file under ``src_rel`` into
    ``dst_rel`` (skipping .gitkeep), then drop the now-empty source dir. No-op when
    ``src_rel`` is absent — the idempotency guard. ``apply=False`` mutates nothing, so
    ``--dry-run`` can preview the moves."""
    src = target / src_rel
    if not src.is_dir():
        return []
    dst = target / dst_rel
    actions: list[str] = []
    for item in sorted(src.iterdir()):
        if item.name == ".gitkeep":
            continue
        destination = dst / item.name
        if destination.exists():  # don't clobber something already in the new home
            continue
        if apply:
            dst.mkdir(parents=True, exist_ok=True)
            shutil.move(str(item), str(destination))
        actions.append(f"{src_rel}/{item.name} → {dst_rel}/{item.name}")
    if apply:  # drain the legacy folder (its .gitkeep too) and remove it if empty
        gitkeep = src / ".gitkeep"
        if gitkeep.exists() and not any(p.name != ".gitkeep" for p in src.iterdir()):
            gitkeep.unlink()
        try:
            src.rmdir()
        except OSError:
            pass
    return actions


def _rfc_lifecycle_rename(target: Path, *, apply: bool) -> list[str]:
    """Old RFC lifecycle (`current/` + `done/`) → the `active/` folder.

    Moves only; an RFC's own `Status:` line is the user's content to restamp (surfaced in
    UPDATING.md), since rewriting it would cross into content transformation.
    """
    actions = _move_dir_contents(target, "docs/rfc/current", "docs/rfc/active", apply=apply)
    actions += _move_dir_contents(target, "docs/rfc/done", "docs/rfc/active", apply=apply)
    return actions


MIGRATIONS: list[Migration] = [
    Migration(
        since="rfc-lifecycle-rework",
        describe="RFC lifecycle: move current/ and done/ into active/",
        apply=_rfc_lifecycle_rename,
    ),
]


def apply_all(target: Path, *, apply: bool = True) -> list[str]:
    """Run every migration against ``target`` (or, with ``apply=False``, just collect what
    they would do); return the flat list of move actions as ``src → dst`` strings."""
    actions: list[str] = []
    for migration in MIGRATIONS:
        actions += migration.apply(target, apply=apply)
    return actions
