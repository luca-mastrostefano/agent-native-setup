"""Filesystem writer that records created paths and renders Jinja2 strings."""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

from jinja2 import ChainableUndefined, Environment

_env = Environment(trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
# A separate env for evaluating prompt `when` expressions: ChainableUndefined makes *any*
# missing reference — at any depth, e.g. an answer not gathered yet (`answers.x.y`) — evaluate
# to a falsy Undefined rather than raising, so a `when` over not-yet-known answers just skips.
_expr_env = Environment(undefined=ChainableUndefined)


def render(template: str, **ctx: object) -> str:
    return _env.from_string(template).render(**ctx)


def compile_expr(expr: str) -> object:
    """Compile a Jinja *expression* (e.g. a prompt's ``when``). Raises on a syntax error, so a
    bad expression is caught at profile-load time rather than mid-prompt."""
    return _expr_env.compile_expression(expr)


def eval_expr(expr: str, **ctx: object) -> object:
    """Evaluate a Jinja expression against ``ctx``. Any undefined reference (at any depth)
    evaluates to a falsy ``Undefined`` rather than raising."""
    return _expr_env.compile_expression(expr)(**ctx)


class Scaffolder:
    """Writes files under a target root, skipping existing ones, and logs actions."""

    def __init__(self, target: Path, *, force: bool = False) -> None:
        self.target = target
        self.force = force
        self.created: list[str] = []
        self.skipped: list[str] = []
        # Absolute paths this run created from scratch — the only things rollback
        # may delete. Pre-existing files are never recorded here, so an interrupt
        # can't destroy the user's own content.
        self.new_paths: list[Path] = []
        # Pre-existing content this run overwrote (only possible under --force),
        # snapshotted so rollback can put it back. Bytes, not text — the user's
        # original file may not be UTF-8.
        self.replaced_files: list[tuple[Path, bytes]] = []
        self.replaced_links: list[tuple[Path, str]] = []  # (link path, original target)
        # rel path -> fingerprint of what this run wrote there ("sha256:<hex>" for a
        # file, "symlink:<target>" for a link). The provenance manifest serializes this
        # so a later `update` can tell a pristine generated file from a user-edited one.
        self.recorded: dict[str, str] = {}
        # Recorded paths the user owns after we seed them (preserve=True files, plus ones
        # marked seed=True like the architecture overview and the bootstrap RFC). The
        # manifest lists these so `update` leaves them untouched even when pristine;
        # everything else in `recorded` is "managed" and refreshable.
        self.seed: set[str] = set()

    def record(self, rel: str, content: str) -> None:
        """Fingerprint generated content for the manifest (call when writing directly)."""
        self.recorded[rel] = "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()

    def track_new(self, path: Path, *, existed: bool) -> None:
        if not existed:
            self.new_paths.append(path)

    def write(
        self,
        rel: str,
        content: str,
        *,
        preserve: bool = False,
        seed: bool = False,
        transient: bool = False,
    ) -> None:
        path = self.target / rel
        # `preserve` protects human-owned files (e.g. README.md) even under --force.
        if path.exists() and (preserve or not self.force):
            self.skipped.append(rel)
            return
        existed = path.exists()
        if existed:  # force-overwrite — snapshot the original so rollback can restore it
            if path.is_symlink():  # snapshot the link itself, and don't write through it
                self.replaced_links.append((path, os.readlink(path)))
                path.unlink()
            else:
                self.replaced_files.append((path, path.read_bytes()))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.created.append(rel)
        self.track_new(path, existed=existed)
        # `transient` files (ONBOARDING.md, the /onboard command) are deleted during
        # onboarding, so they're left out of the manifest — a baseline must never list a
        # file destined to vanish, or a later update would try to resurrect it.
        if not transient:
            self.record(rel, content)
            # `preserve` (human-owned) and `seed` (seeded then owned, e.g. the architecture
            # overview) both mean: never refresh on update. Recorded as one set.
            if preserve or seed:
                self.seed.add(rel)

    def render_write(
        self, rel: str, template: str, *, preserve: bool = False, seed: bool = False, **ctx: object
    ) -> None:
        self.write(rel, render(template, **ctx), preserve=preserve, seed=seed)

    def symlink(self, link_rel: str, dest_rel: str) -> None:
        """Create ``link_rel`` pointing at ``dest_rel`` (relative to link's dir)."""
        link = self.target / link_rel
        existed = link.exists() or link.is_symlink()
        if existed:
            if not self.force:
                self.skipped.append(link_rel)
                return
            # Snapshot whatever the force-replace removes, so rollback can restore it.
            if link.is_symlink():
                self.replaced_links.append((link, os.readlink(link)))
            elif link.is_file():
                self.replaced_files.append((link, link.read_bytes()))
            link.unlink()
        link.parent.mkdir(parents=True, exist_ok=True)
        rel_dest = os.path.relpath((self.target / dest_rel), start=link.parent)
        link.symlink_to(rel_dest)
        self.created.append(f"{link_rel} -> {rel_dest}")
        self.track_new(link, existed=existed)
        self.recorded[link_rel] = f"symlink:{rel_dest}"

    def overlay(self, rel: str, content: str, *, seed: bool = True) -> bool:
        """Write a profile-composition file at ``rel``. ``seed=True`` marks it write-once
        (never refreshed on update); ``seed=False`` makes it managed (refreshed when the
        profile ships a new version). Unlike ``write`` (first-writer-wins), this *supersedes*
        a file the base layer wrote in this same run — a later layer is meant to win. A file
        that **pre-existed** this scaffold is the user's: left untouched unless ``--force``,
        keeping the non-destructive contract. Returns ``True`` if it wrote, ``False`` if it
        skipped a pre-existing user file (so the caller knows which paths the profile owns)."""
        path = self.target / rel
        created_this_run = path in self.new_paths
        preexisting = (path.exists() or path.is_symlink()) and not created_this_run
        if preexisting and not self.force:
            self.skipped.append(rel)
            return False
        if preexisting:  # --force over a user's own file: snapshot so rollback restores it
            if path.is_symlink():
                self.replaced_links.append((path, os.readlink(path)))
            else:
                self.replaced_files.append((path, path.read_bytes()))
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():  # the base may have placed a symlink here — replace it with a file
            path.unlink()
        path.write_text(content, encoding="utf-8")
        if rel not in self.created:
            self.created.append(rel)
        if not created_this_run and not preexisting:
            self.new_paths.append(path)  # a brand-new path this overlay created
        self.record(rel, content)
        # The overlay is authoritative for this path: a managed overlay must *clear* a seed
        # mark the base layer set (e.g. README.md), or it would never refresh on update.
        if seed:
            self.seed.add(rel)
        else:
            self.seed.discard(rel)
        return True

    def rollback(self) -> int:
        """Undo this run: delete what it created, restore what it overwrote,
        then prune dirs it emptied.

        Deletion only touches paths recorded in ``new_paths``, so files that
        predate this run survive an interrupted scaffold untouched; files a
        ``--force`` run overwrote are restored from their snapshots.
        """
        rolled_back = 0
        for path in reversed(self.new_paths):
            try:
                if path.is_symlink() or path.is_file():
                    path.unlink()
                    rolled_back += 1
                elif path.is_dir():
                    shutil.rmtree(path)
                    rolled_back += 1
            except OSError:
                pass
        for path, content in reversed(self.replaced_files):
            try:
                if path.is_symlink():  # don't write through a symlink that replaced the file
                    path.unlink()
                path.write_bytes(content)
                rolled_back += 1
            except OSError:
                pass
        for link, target in reversed(self.replaced_links):
            try:
                if link.is_symlink() or link.exists():
                    link.unlink()
                link.symlink_to(target)
                rolled_back += 1
            except OSError:
                pass
        for path in self.new_paths:
            parent = path.parent
            while parent != self.target and parent.is_dir():
                try:
                    parent.rmdir()  # succeeds only while empty
                except OSError:
                    break
                parent = parent.parent
        return rolled_back
