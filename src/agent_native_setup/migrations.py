"""The migration registry `update` replays before regenerating (RFCs 2026-06-20, 2026-06-22).

Regenerating from the saved config refreshes the files the wizard *generates*, but it can't
move the files a *user* accumulated when a convention's layout changes — e.g. the RFC
lifecycle rename (`current/` → `active/`). Those transforms live here, in an append-only,
version-tagged registry. Each entry declares a ``kind``:

- ``auto`` — a deterministic, **idempotent** move/rename the tool performs. It guards on the
  old layout, so a re-run is a no-op; ``update`` therefore *attempts every ``auto`` step on
  every run* regardless of version (robust even when versions aren't reliably tagged), and
  its ``version`` is informational/ordering only.
- ``agent`` / ``manual`` — a transform that needs a coding agent (to read the user's content)
  or a human. The tool never performs these; it emits their ``instructions`` into the
  ``UPDATING.md`` runbook for the boundaries actually crossed. These are **version-keyed**:
  span selection (``steps_in_span``) picks the ones in ``(installed, latest]``, in order.

By the §1 contract of RFC 2026-06-22, ``auto`` steps may ship in a compatible (minor, or in
0.x a patch) release; ``agent``/``manual`` steps only at a breaking-series boundary.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from agent_native_setup import versioning


def _noop(target: Path, *, apply: bool = True) -> list[str]:
    """Default `apply` for `agent`/`manual` steps — the tool never performs them itself."""
    return []


@dataclass
class Migration:
    version: str  # semver it shipped in (span selection for agent/manual; ordering for auto)
    kind: str  # "auto" | "agent" | "manual"
    describe: str
    # `auto`: performs the move (apply=True) or previews it (apply=False). Unused otherwise.
    apply: Callable[..., list[str]] = _noop
    # `agent`/`manual`: the runbook text the agent/user follows to do the transform.
    instructions: str = ""


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
        version="0.5.0",  # the RFC-lifecycle rework first shipped in v0.5.0
        kind="auto",
        describe="RFC lifecycle: move current/ and done/ into active/",
        apply=_rfc_lifecycle_rename,
    ),
]


def apply_all(target: Path, *, apply: bool = True) -> list[str]:
    """Run every ``auto`` migration against ``target`` (or, with ``apply=False``, just collect
    what they would do); return the flat list of move actions as ``src → dst`` strings.
    ``auto`` steps are idempotent, so this attempts them all every run regardless of version."""
    actions: list[str] = []
    for migration in MIGRATIONS:
        if migration.kind == "auto":
            actions += migration.apply(target, apply=apply)
    return actions


def steps_in_span(installed: str, latest: str) -> list[Migration]:
    """The ``agent``/``manual`` migration steps in ``(installed, latest]``, ascending — the
    ordered ``UPDATING.md`` runbook sections for the breaking boundaries actually crossed.
    A user many versions behind gets every boundary's instructions, in order."""
    iv, lv = versioning.parse(installed), versioning.parse(latest)
    chosen = [
        m
        for m in MIGRATIONS
        if m.kind in ("agent", "manual") and iv < versioning.parse(m.version) <= lv
    ]
    return sorted(chosen, key=lambda m: versioning.parse(m.version))
