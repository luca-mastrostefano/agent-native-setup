"""Filesystem writer that records created paths and renders Jinja2 strings."""

from __future__ import annotations

import os
from pathlib import Path

from jinja2 import Environment

_env = Environment(trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)


def render(template: str, **ctx: object) -> str:
    return _env.from_string(template).render(**ctx)


class Scaffolder:
    """Writes files under a target root, skipping existing ones, and logs actions."""

    def __init__(self, target: Path, *, force: bool = False) -> None:
        self.target = target
        self.force = force
        self.created: list[str] = []
        self.skipped: list[str] = []

    def write(self, rel: str, content: str, *, preserve: bool = False) -> None:
        path = self.target / rel
        # `preserve` protects human-owned files (e.g. README.md) even under --force.
        if path.exists() and (preserve or not self.force):
            self.skipped.append(rel)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.created.append(rel)

    def render_write(
        self, rel: str, template: str, *, preserve: bool = False, **ctx: object
    ) -> None:
        self.write(rel, render(template, **ctx), preserve=preserve)

    def symlink(self, link_rel: str, dest_rel: str) -> None:
        """Create ``link_rel`` pointing at ``dest_rel`` (relative to link's dir)."""
        link = self.target / link_rel
        if link.exists() or link.is_symlink():
            if not self.force:
                self.skipped.append(link_rel)
                return
            link.unlink()
        link.parent.mkdir(parents=True, exist_ok=True)
        rel_dest = os.path.relpath((self.target / dest_rel), start=link.parent)
        link.symlink_to(rel_dest)
        self.created.append(f"{link_rel} -> {rel_dest}")
